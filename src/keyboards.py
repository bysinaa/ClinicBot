# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from persiantools.jdatetime import JalaliDate

from feature_broadcast_aiogram_plugin_fixed import get_broadcast_admin_button

if TYPE_CHECKING:  # pragma: no cover
    from src.services.booking import SlotAvailability, SlotSummary

_MOJIBAKE_MARKERS = ("Ã", "Â", "Ø")


def _assert_unicode(text: str) -> str:
    assert isinstance(text, str), "Text must be a Unicode str"
    if any(marker in text for marker in _MOJIBAKE_MARKERS):
        try:
            print(f"[warn] mojibake detected in text: {text!r}")
        except UnicodeEncodeError:
            safe = text.encode("unicode_escape").decode("ascii", "ignore")
            print(f"[warn] mojibake detected in text: {safe}")
    return text


# Public constants so handlers can reuse the exact labels ---------------------

REGISTER_TEXT = "ثبت‌نام 👤"
BOOK_APPOINTMENT_TEXT = "رزرو نوبت 🗓️"
CLINIC_CONTACT_TEXT = "تماس با کلینیک ☎️"
CLINIC_ADDRESS_TEXT = "آدرس و موقعیت 📍"
ONLINE_CONSULT_TEXT = "مشاوره آنلاین 💬"
SEND_RECEIPT_TEXT = "ارسال رسید پرداخت 📤"
SMART_ASSIST_TEXT = "دستیار هوشمند 🤖"
BACK_TO_MENU_TEXT = "بازگشت به منو ⬅️"
CANCEL_TEXT = "انصراف ✖️"

ADMIN_SCHEDULE_TEXT = "مدیریت برنامه نوبت‌ها 🗂️"
ADMIN_ONLINE_TEXT = "درخواست‌های مشاوره آنلاین 📥"
ADMIN_PENDING_TEXT = "درخواست‌های در انتظار بررسی ⏳"
ADMIN_PDF_TEXT = "گزارش‌های PDF 📄"
ADMIN_BROADCAST_TEXT = "پیام همگانی 📢"

ADD_DAY_TEXT = "افزودن روز جدید ➕"
ADD_SLOT_TEXT = "افزودن بازه زمانی ➕"
TOGGLE_SLOT_DISABLE_TEXT = "غیرفعال‌سازی بازه ⛔"
TOGGLE_SLOT_ENABLE_TEXT = "فعال‌سازی بازه ✅"
DELETE_SLOT_TEXT = "حذف بازه 🗑️"
TOGGLE_DAY_DISABLE_TEXT = "غیرفعال‌سازی روز ⛔"
TOGGLE_DAY_ENABLE_TEXT = "فعال‌سازی روز ✅"
EXPORT_DAY_PDF_TEXT = "دریافت PDF روز 📄"
DELETE_DAY_TEXT = "حذف روز 🗑️"
BACK_TO_DAYS_TEXT = "بازگشت به فهرست روزها ⬅️"
BACK_TO_MONTHS_TEXT = "بازگشت به فهرست ماه‌ها ⬅️"

PREV_PAGE_TEXT = "صفحه قبل ◀️"
NEXT_PAGE_TEXT = "صفحه بعد ▶️"


# Main menu keyboards --------------------------------------------------------

def main_menu(is_registered: bool = False) -> ReplyKeyboardMarkup:
    keyboard: list[list[KeyboardButton]] = []
    if not is_registered:
        keyboard.append([KeyboardButton(text=_assert_unicode(REGISTER_TEXT))])
    keyboard.append([KeyboardButton(text=_assert_unicode(BOOK_APPOINTMENT_TEXT))])
    keyboard.append([KeyboardButton(text=_assert_unicode(CLINIC_CONTACT_TEXT))])
    keyboard.append([KeyboardButton(text=_assert_unicode(CLINIC_ADDRESS_TEXT))])
    keyboard.append([KeyboardButton(text=_assert_unicode(ONLINE_CONSULT_TEXT))])
    keyboard.append([KeyboardButton(text=_assert_unicode(SEND_RECEIPT_TEXT))])
    keyboard.append([KeyboardButton(text=_assert_unicode(SMART_ASSIST_TEXT))])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def main_menu_inline(is_registered: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not is_registered:
        rows.append(
            [InlineKeyboardButton(text=_assert_unicode(REGISTER_TEXT), callback_data="patient:register")]
        )
    rows.append(
        [InlineKeyboardButton(text=_assert_unicode(BOOK_APPOINTMENT_TEXT), callback_data="menu:book")]
    )
    rows.append(
        [InlineKeyboardButton(text=_assert_unicode(CLINIC_CONTACT_TEXT), callback_data="menu:contact")]
    )
    rows.append(
        [InlineKeyboardButton(text=_assert_unicode(CLINIC_ADDRESS_TEXT), callback_data="menu:address")]
    )
    rows.append(
        [InlineKeyboardButton(text=_assert_unicode(ONLINE_CONSULT_TEXT), callback_data="menu:online")]
    )
    rows.append(
        [InlineKeyboardButton(text=_assert_unicode(SEND_RECEIPT_TEXT), callback_data="menu:receipt")]
    )
    rows.append(
        [InlineKeyboardButton(text=_assert_unicode(SMART_ASSIST_TEXT), callback_data="menu:consult")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dates_keyboard(dates: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_assert_unicode(label), callback_data=f"date:{label}")]
        for label in dates
    ]
    rows.append([InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def times_keyboard(times: list[str], jdate: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for time_label in times:
        rows.append(
            [InlineKeyboardButton(text=_assert_unicode(time_label), callback_data=f"time:{jdate}:{time_label}")]
        )
    rows.append([InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu_inline() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=_assert_unicode(ADMIN_SCHEDULE_TEXT), callback_data="admin:schedule")],
        [InlineKeyboardButton(text=_assert_unicode(ADMIN_ONLINE_TEXT), callback_data="admin:online")],
        [InlineKeyboardButton(text=_assert_unicode(ADMIN_PENDING_TEXT), callback_data="admin:pending")],
        [get_broadcast_admin_button(text=ADMIN_BROADCAST_TEXT, callback_data="pbcast:start")],
        [InlineKeyboardButton(text=_assert_unicode(ADMIN_PDF_TEXT), callback_data="admin:pdf")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Registration helpers -------------------------------------------------------

_BIRTH_MONTHS: list[tuple[str, int]] = [
    ("فروردین", 1),
    ("اردیبهشت", 2),
    ("خرداد", 3),
    ("تیر", 4),
    ("مرداد", 5),
    ("شهریور", 6),
    ("مهر", 7),
    ("آبان", 8),
    ("آذر", 9),
    ("دی", 10),
    ("بهمن", 11),
    ("اسفند", 12),
]


def birth_year_keyboard(page: int, *, min_age: int = 10, max_age: int = 90) -> InlineKeyboardMarkup:
    today = JalaliDate.today()
    max_year = today.year - min_age
    min_year = today.year - max_age
    years = list(range(max_year, min_year - 1, -1))
    page_size = 9
    start = page * page_size
    chunk = years[start : start + page_size]
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, year in enumerate(chunk):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(text=str(year), callback_data=f"bdate:y:{year}")
        )
    navigation: list[InlineKeyboardButton] = []
    if start > 0:
        navigation.append(
            InlineKeyboardButton(text=_assert_unicode(PREV_PAGE_TEXT), callback_data=f"bdate:y_page:{page - 1}")
        )
    if start + page_size < len(years):
        navigation.append(
            InlineKeyboardButton(text=_assert_unicode(NEXT_PAGE_TEXT), callback_data=f"bdate:y_page:{page + 1}")
        )
    if navigation:
        buttons.append(navigation)
    buttons.append([InlineKeyboardButton(text=_assert_unicode(CANCEL_TEXT), callback_data="bdate:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def birth_month_keyboard() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (name, month) in enumerate(_BIRTH_MONTHS):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(text=_assert_unicode(name), callback_data=f"bdate:m:{month}")
        )
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(PREV_PAGE_TEXT), callback_data="bdate:back:year"),
            InlineKeyboardButton(text=_assert_unicode(CANCEL_TEXT), callback_data="bdate:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def birth_day_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    days_in_month = JalaliDate.days_in_month(month, year)
    buttons: list[list[InlineKeyboardButton]] = []
    for day in range(1, days_in_month + 1):
        if (day - 1) % 7 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(text=str(day), callback_data=f"bdate:d:{day}")
        )
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(PREV_PAGE_TEXT), callback_data="bdate:back:month"),
            InlineKeyboardButton(text=_assert_unicode(CANCEL_TEXT), callback_data="bdate:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Booking helpers ------------------------------------------------------------

def booking_months_keyboard(months: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (label, month_key) in enumerate(months):
        if idx % 2 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(text=_assert_unicode(label), callback_data=f"book:month:{month_key}")
        )
    buttons.append([InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def booking_days_keyboard(days: Sequence[tuple[str, str]], month_key: str) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (label, jdate) in enumerate(days):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(text=_assert_unicode(label), callback_data=f"book:day:{jdate}")
        )
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MONTHS_TEXT), callback_data="book:back:month"),
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def booking_slots_keyboard(slots: Sequence["SlotAvailability"], jdate: str) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for slot in slots:
        remaining = max(slot.capacity - slot.booked, 0)
        if remaining <= 0:
            status_text = "تکمیل شده ⛔"
        else:
            status_text = f"ظرفیت باقی‌مانده: {remaining}"
        label = f"{slot.start_time} تا {slot.end_time} | {status_text}"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=_assert_unicode(label),
                    callback_data=f"book:slot:{slot.slot_id}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_DAYS_TEXT), callback_data=f"book:back:day:{jdate}"),
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Admin schedule helpers -----------------------------------------------------

def admin_schedule_months_keyboard(months: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (label, month_key) in enumerate(months):
        if idx % 2 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(text=_assert_unicode(label), callback_data=f"admin:schedule:month:{month_key}")
        )
    buttons.append([InlineKeyboardButton(text=_assert_unicode(ADD_DAY_TEXT), callback_data="admin:schedule:add_day")])
    buttons.append([InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_days_keyboard(
    days: Sequence[tuple[str, str]],
    month_key: str,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (label, jdate) in enumerate(days):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(text=_assert_unicode(label), callback_data=f"admin:schedule:day:{jdate}")
        )
    buttons.append(
        [
            InlineKeyboardButton(
                text=_assert_unicode(ADD_DAY_TEXT),
                callback_data=f"admin:schedule:add_day:{month_key}",
            )
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text=_assert_unicode(BACK_TO_MONTHS_TEXT),
                callback_data="admin:schedule:back:months",
            ),
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_slots_keyboard(
    day_id: int,
    jdate: str,
    slots: Sequence["SlotSummary"],
    day_active: bool,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for slot in slots:
        status_text = "فعال ✅" if slot.is_active else "غیرفعال ⛔"
        remaining = getattr(slot, "remaining", max(slot.capacity - slot.booked, 0))
        label = (
            f"{slot.start_time} تا {slot.end_time} | وضعیت: {status_text} | "
            f"ظرفیت: {slot.capacity} | باقی\u200cمانده: {remaining}"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text=_assert_unicode(label),
                    callback_data=f"admin:schedule:slot_info:{slot.slot_id}",
                )
            ]
        )
        toggle_text = TOGGLE_SLOT_DISABLE_TEXT if slot.is_active else TOGGLE_SLOT_ENABLE_TEXT
        buttons.append(
            [
                InlineKeyboardButton(
                    text=_assert_unicode(toggle_text),
                    callback_data=f"admin:schedule:slot_toggle:{slot.slot_id}",
                ),
                InlineKeyboardButton(
                    text=_assert_unicode(DELETE_SLOT_TEXT),
                    callback_data=f"admin:schedule:slot_delete:{slot.slot_id}",
                ),
            ]
        )
    toggle_day_text = TOGGLE_DAY_DISABLE_TEXT if day_active else TOGGLE_DAY_ENABLE_TEXT
    buttons.append(
        [InlineKeyboardButton(text=_assert_unicode(ADD_SLOT_TEXT), callback_data=f"admin:schedule:add_slot:{day_id}")]
    )
    buttons.append(
        [InlineKeyboardButton(text=_assert_unicode(toggle_day_text), callback_data=f"admin:schedule:toggle_day:{day_id}")]
    )
    buttons.append(
        [
            InlineKeyboardButton(
                text=_assert_unicode(EXPORT_DAY_PDF_TEXT),
                callback_data=f"admin:schedule:export:{day_id}:{jdate}",
            )
        ]
    )
    buttons.append(
        [InlineKeyboardButton(text=_assert_unicode(DELETE_DAY_TEXT), callback_data=f"admin:schedule:delete_day:{day_id}")]
    )
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_DAYS_TEXT), callback_data=f"admin:schedule:back:days:{jdate}"),
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_report_months_keyboard(months: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, (label, month_key) in enumerate(months):
        if idx % 2 == 0:
            rows.append([])
        rows[-1].append(
            InlineKeyboardButton(text=_assert_unicode(label), callback_data=f"admin:pdf:month:{month_key}")
        )
    rows.append([InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_report_days_keyboard(
    days: Sequence[tuple[str, str]],
    month_key: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, (label, jdate) in enumerate(days):
        if idx % 2 == 0:
            rows.append([])
        rows[-1].append(
            InlineKeyboardButton(text=_assert_unicode(label), callback_data=f"admin:pdf:day:{jdate}")
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=_assert_unicode(BACK_TO_MONTHS_TEXT),
                callback_data="admin:pdf",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_schedule_add_day_picker_keyboard(
    days: Sequence[tuple[str, str]],
    *,
    page: int,
    has_prev: bool,
    has_next: bool,
    month_key: str | None,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for label, jdate in days:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=_assert_unicode(label),
                    callback_data=f"admin:schedule:add_day_select:{jdate}",
                )
            ]
        )
    nav_buttons: list[InlineKeyboardButton] = []
    filter_token = month_key or "-"
    if has_prev:
        nav_buttons.append(
            InlineKeyboardButton(
                text=_assert_unicode(PREV_PAGE_TEXT),
                callback_data=f"admin:schedule:add_day_page:{page - 1}:{filter_token}",
            )
        )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text=_assert_unicode(NEXT_PAGE_TEXT),
                callback_data=f"admin:schedule:add_day_page:{page + 1}:{filter_token}",
            )
        )
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(CANCEL_TEXT), callback_data="admin:schedule:add_day_back"),
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_slot_start_keyboard(times: Sequence[str]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, label in enumerate(times):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(
                text=_assert_unicode(label),
                callback_data=f"admin:schedule:slot_start:{label.replace(':', '-')}",
            )
        )
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(CANCEL_TEXT), callback_data="admin:schedule:slot_back:detail"),
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_slot_end_keyboard(times: Sequence[str]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, label in enumerate(times):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(
                text=_assert_unicode(label),
                callback_data=f"admin:schedule:slot_end:{label.replace(':', '-')}",
            )
        )
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_DAYS_TEXT), callback_data="admin:schedule:slot_back:start"),
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_slot_capacity_keyboard(capacities: Sequence[int]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, value in enumerate(capacities):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(
                text=str(value),
                callback_data=f"admin:schedule:slot_capacity:{value}",
            )
        )
    buttons.append(
        [
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_DAYS_TEXT), callback_data="admin:schedule:slot_back:end"),
            InlineKeyboardButton(text=_assert_unicode(BACK_TO_MENU_TEXT), callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


__all__ = [
    "REGISTER_TEXT",
    "BOOK_APPOINTMENT_TEXT",
    "CLINIC_CONTACT_TEXT",
    "CLINIC_ADDRESS_TEXT",
    "ONLINE_CONSULT_TEXT",
    "SEND_RECEIPT_TEXT",
    "SMART_ASSIST_TEXT",
    "BACK_TO_MENU_TEXT",
    "CANCEL_TEXT",
    "ADMIN_SCHEDULE_TEXT",
    "ADMIN_ONLINE_TEXT",
    "ADMIN_PENDING_TEXT",
    "ADMIN_PDF_TEXT",
    "ADMIN_BROADCAST_TEXT",
    "main_menu",
    "main_menu_inline",
    "dates_keyboard",
    "times_keyboard",
    "admin_menu_inline",
    "birth_year_keyboard",
    "birth_month_keyboard",
    "birth_day_keyboard",
    "booking_months_keyboard",
    "booking_days_keyboard",
    "booking_slots_keyboard",
    "admin_schedule_months_keyboard",
    "admin_schedule_days_keyboard",
    "admin_schedule_slots_keyboard",
    "admin_report_months_keyboard",
    "admin_report_days_keyboard",
    "admin_schedule_add_day_picker_keyboard",
    "admin_schedule_slot_start_keyboard",
    "admin_schedule_slot_end_keyboard",
    "admin_schedule_slot_capacity_keyboard",
]
