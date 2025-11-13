import os
from dataclasses import dataclass
from urllib.parse import urlparse
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


def _env_proxy_url(name: str) -> str | None:
    raw = os.getenv(name)
    if not raw:
        return None
    value = raw.strip()
    if not value:
        return None
    if "://" not in value:
        value = f"socks5://{value}"
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        print(f"[WARN] Invalid proxy url provided in {name}: {raw}")
        return None
    return value


def _env_phone_pairs(name: str) -> list[tuple[str, str]]:
    raw = os.getenv(name)
    if not raw:
        return []
    pairs: list[tuple[str, str]] = []
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            label, number = chunk.split(":", 1)
        else:
            label, number = "تماس", chunk
        label = label.strip()
        number = number.strip()
        if not number:
            continue
        pairs.append((label or "تماس", number))
    return pairs


DEFAULT_CONTACT_TEXT = (
    "🌸 به صفحه رسمی دکتر مریم میرفتاحی خوش آمدید ✨\n\n"
    "در این صفحه با جدیدترین مطالب علمی، نکات تخصصی مراقبتی و پاسخ به سوالات رایج همراه شما هستیم.\n"
    "💬 در صورت داشتن هرگونه سؤال، می‌توانید همین‌جا پیام بگذارید تا راهنمایی شوید.\n\n"
    "💙 امیدواریم حضور شما آغاز مسیری سالم‌تر، زیباتر و شاداب‌تر باشد."
)


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
    telegram_proxy_url: str | None = _env_proxy_url("TELEGRAM_PROXY_URL")
    telegram_proxy_enabled: bool = _env_flag(
        "TELEGRAM_PROXY_ENABLED", default=os.getenv("TELEGRAM_PROXY_URL") is not None
    )
    skip_db_init: bool = _env_flag("SKIP_DB_INIT", default=False)
    admin_ids: tuple[int, ...] = tuple(_env_int_list("ADMIN_IDS"))
    clinic_phone_number: str | None = _env_text("CLINIC_PHONE_NUMBER")
    clinic_phone_label: str = _env_text("CLINIC_PHONE_LABEL", default="تماس با مطب") or "تماس با مطب"
    clinic_contact_text: str = _env_text("CLINIC_CONTACT_TEXT", default=DEFAULT_CONTACT_TEXT) or DEFAULT_CONTACT_TEXT
    clinic_contact_numbers: tuple[tuple[str, str], ...] = tuple(_env_phone_pairs("CLINIC_CONTACT_NUMBERS"))
    clinic_address_text: str | None = _env_text("CLINIC_ADDRESS_TEXT")
    clinic_address_tehran: str | None = _env_text("CLINIC_ADDRESS_TEHRAN")
    clinic_address_karaj: str | None = _env_text("CLINIC_ADDRESS_KARAJ")
    clinic_location_lat: float | None = _env_float("CLINIC_LOCATION_LAT")
    clinic_location_lon: float | None = _env_float("CLINIC_LOCATION_LON")
    clinic_tehran_lat: float | None = _env_float("CLINIC_TEHRAN_LAT")
    clinic_tehran_lon: float | None = _env_float("CLINIC_TEHRAN_LON")
    clinic_karaj_lat: float | None = _env_float("CLINIC_KARAJ_LAT")
    clinic_karaj_lon: float | None = _env_float("CLINIC_KARAJ_LON")
    pdf_stamp_path: str | None = _env_text("PDF_STAMP_PATH")
    pdf_font_path: str | None = _env_text("PDF_FONT_PATH")


settings = Settings()
if not settings.bot_token:
    print("[WARN] TELEGRAM_BOT_TOKEN is empty. Set it in your .env")
