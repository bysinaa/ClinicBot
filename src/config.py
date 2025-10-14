import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}

def _env_int_list(name: str) -> list[int]:
    raw = os.getenv(name)
    if not raw:
        return []
    values = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            print(f"[WARN] Ignoring invalid admin id '{part}' in {name}")
    return values


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
    skip_db_init: bool = _env_flag("SKIP_DB_INIT", default=False)
    admin_ids: tuple[int, ...] = tuple(_env_int_list("ADMIN_IDS"))


settings = Settings()
if not settings.bot_token:
    print("[WARN] TELEGRAM_BOT_TOKEN is empty. Set it in your .env")
