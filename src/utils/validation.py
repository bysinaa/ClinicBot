# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from datetime import date, datetime

from src.utils.national_id import is_valid_iran_national_id as _legacy_validator

_TRANSLATION_TABLE = str.maketrans(
    {
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "٬": ",",
        "٫": ".",
        "،": ",",
        "؛": ";",
        "٪": "%",
        "−": "-",
        "–": "-",
        "—": "-",
    }
)


def to_english_digits(value: str) -> str:
    """Convert Persian/Arabic digits and common symbols to their ASCII equivalents."""
    if not value:
        return ""
    return value.translate(_TRANSLATION_TABLE)


def is_valid_national_id(code: str) -> bool:
    digits = to_english_digits(code)
    digits = "".join(ch for ch in digits if ch.isdigit())
    if not digits:
        return False
    return _legacy_validator(digits)


def normalize_phone(raw: str) -> str | None:
    if not raw:
        return None
    raw = to_english_digits(raw)
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("09") and len(digits) == 11:
        return "+98" + digits[1:]
    if digits.startswith("9") and len(digits) == 10:
        return "+98" + digits
    if raw.startswith("+98") and digits.startswith("989") and len(digits) == 12:
        return "+98" + digits[2:]
    return None


def parse_birthdate(raw: str) -> date | None:
    if not raw:
        return None
    token = to_english_digits(raw.strip()).replace("/", "-")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
        return None
    try:
        return datetime.strptime(token, "%Y-%m-%d").date()
    except ValueError:
        return None
