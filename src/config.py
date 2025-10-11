import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/clinicbot",
    )
    admin_secret: str = os.getenv("ADMIN_SECRET", "change_this_admin_secret")
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    redis_url: str | None = os.getenv("REDIS_URL") or None
    telegram_proxy_url: str | None = os.getenv("TELEGRAM_PROXY_URL") or None
    telegram_proxy_enabled: bool = _env_flag(
        "TELEGRAM_PROXY_ENABLED", default=os.getenv("TELEGRAM_PROXY_URL") is not None
    )


settings = Settings()
if not settings.bot_token:
    print("[WARN] TELEGRAM_BOT_TOKEN is empty. Set it in your .env")
