import asyncio
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent.parent))

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from src.config import settings
from src.database import init_db
from src.middlewares.auth import UserMiddleware
from feature_broadcast_aiogram_plugin_fixed import build_broadcast_router
from src.handlers import common, patient, admin
from src.handlers.patient_broadcast import router as patient_broadcast_router
from src.handlers.user_registration import router as user_registration_router


def _is_admin(chat_id: int) -> bool:
    return chat_id in settings.admin_ids


def _warn_if_mojibake() -> None:
    """Log a warning if we detect mojibake patterns in key keyboards."""

    markers = ("Ã", "Â", "�")

    try:
        from src.keyboards import admin_menu_inline, main_menu, main_menu_inline
    except Exception as exc:  # pragma: no cover - defensive during boot
        print(f"[WARN] Mojibake check skipped: {exc}")
        return

    def check_label(label: str, origin: str) -> None:
        if label and any(marker in label for marker in markers):
            print(f"[WARN] Suspected mojibake in {origin}: {label!r}")

    for origin, markup in (
        ("admin_inline", admin_menu_inline()),
        ("main_inline", main_menu_inline()),
    ):
        for row in getattr(markup, "inline_keyboard", []):
            for button in row:
                check_label(getattr(button, "text", ""), origin)

    reply_markup = main_menu()
    for row in getattr(reply_markup, "keyboard", []):
        for button in row:
            check_label(getattr(button, "text", ""), "main_reply")


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
    dp = Dispatcher(storage=MemoryStorage())
    _warn_if_mojibake()
    # Middlewares
    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(UserMiddleware())
    # Routers
    broadcast_router = build_broadcast_router(
        is_admin_func=_is_admin,
        db_path="subscribers.db",
        send_delay_seconds=0.05,
        enable_stats_command=True,
        stats_command_name="stats",
        broadcast_command_name="broadcast",
        admin_broadcast_callback_data="admin:broadcast",
    )
    dp.include_router(broadcast_router)
    dp.include_router(patient_broadcast_router)
    dp.include_router(user_registration_router)
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




