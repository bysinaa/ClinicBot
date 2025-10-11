import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Settings:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tazanachi.db")
    admin_secret: str = os.getenv("ADMIN_SECRET", "change_this_admin_secret")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    redis_url: str | None = os.getenv("REDIS_URL") or None

settings = Settings()
if not settings.bot_token:
    print("[WARN] TELEGRAM_BOT_TOKEN is empty. Set it in your .env")
