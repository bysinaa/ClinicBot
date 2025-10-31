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


def _env_text(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    if not value:
        return default
    return value


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        print(f"[WARN] Ignoring invalid float '{raw}' in {name}")
        return None


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
    clinic_phone_number: str | None = _env_text("CLINIC_PHONE_NUMBER")
    clinic_phone_label: str = _env_text("CLINIC_PHONE_LABEL", default="تماس با مطب") or "تماس با مطب"
    clinic_address_text: str | None = _env_text("CLINIC_ADDRESS_TEXT")
    clinic_location_lat: float | None = _env_float("CLINIC_LOCATION_LAT")
    clinic_location_lon: float | None = _env_float("CLINIC_LOCATION_LON")


settings = Settings()
if not settings.bot_token:
    print("[WARN] TELEGRAM_BOT_TOKEN is empty. Set it in your .env")
