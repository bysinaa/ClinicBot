import asyncio
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from src.config import settings
from src.database import init_db
from src.middlewares.auth import UserMiddleware
from src.handlers import common, patient, admin

async def main():
    if settings.skip_db_init:
        print("[WARN] Database initialization skipped (SKIP_DB_INIT=1).")
    else:
        await init_db()
    session = None
    if settings.telegram_proxy_enabled and settings.telegram_proxy_url:
        try:
            session = AiohttpSession(proxy=settings.telegram_proxy_url)
        except RuntimeError as error:
            print(f"[WARN] Proxy disabled: {error}")
            session = None
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )
    try:
        await bot.get_me()
    except TelegramUnauthorizedError as error:
        print("[ERROR] Telegram rejected the provided bot token. Update TELEGRAM_BOT_TOKEN.")
        await bot.session.close()
        raise SystemExit(1) from error
    dp = Dispatcher()
    # Middlewares
    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())
    # Routers
    dp.include_router(common.router)
    dp.include_router(patient.router)
    dp.include_router(admin.router)
    print("Bot is up. Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot)
    except TelegramNetworkError as error:
        print(f"[WARN] Polling stopped: {error}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")
