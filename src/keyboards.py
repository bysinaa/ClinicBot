# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Sequence, TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from persiantools.jdatetime import JalaliDate

from src.utils.jalali import jalali_month_name, jalali_weekday_name

if TYPE_CHECKING:  # pragma: no cover
    from src.services.booking import SlotAvailability, SlotSummary


def main_menu(is_registered: bool = False) -> ReplyKeyboardMarkup:
    keyboard: list[list[KeyboardButton]] = []
    if not is_registered:
        keyboard.append([KeyboardButton(text="ثبت‌نام")])
    keyboard.append([KeyboardButton(text="رزرو نوبت")])
    keyboard.append([KeyboardButton(text="اطلاعات تماس")])
    keyboard.append([KeyboardButton(text="مشاوره آنلاین")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def main_menu_inline(is_registered: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not is_registered:
        rows.append([InlineKeyboardButton(text="ثبت‌نام", callback_data="menu:register")])
    rows.append([InlineKeyboardButton(text="رزرو نوبت", callback_data="menu:book")])
    rows.append([InlineKeyboardButton(text="اطلاعات تماس", callback_data="menu:contact")])
    rows.append([InlineKeyboardButton(text="آدرس مطب", callback_data="menu:address")])
    rows.append([InlineKeyboardButton(text="مشاوره آنلاین", callback_data="menu:online")])
    rows.append([InlineKeyboardButton(text="ارسال رسید پرداخت", callback_data="menu:receipt")])
    rows.append([InlineKeyboardButton(text="مشاوره هوشمند", callback_data="menu:consult")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def dates_keyboard(dates: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=d, callback_data=f"date:{d}")] for d in dates]
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def times_keyboard(times: list[str], jdate: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for t in times:
        rows.append([InlineKeyboardButton(text=t, callback_data=f"time:{jdate}:{t}")])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_menu_inline() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="مدیریت برنامه زمانی", callback_data="admin:schedule")],
        [InlineKeyboardButton(text="درخواست‌های ویزیت آنلاین", callback_data="admin:online")],
        [InlineKeyboardButton(text="نوبت‌های در انتظار", callback_data="admin:pending")],
        [InlineKeyboardButton(text="ارسال پیام", callback_data="admin:message")],
        [InlineKeyboardButton(text="گزارش PDF", callback_data="admin:pdf")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# Registration helpers -----------------------------------------------------

_BIRTH_MONTHS = [
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
        buttons[-1].append(InlineKeyboardButton(text=str(year), callback_data=f"bdate:y:{year}"))
    navigation: list[InlineKeyboardButton] = []
    if start > 0:
        navigation.append(InlineKeyboardButton(text="قبلی", callback_data=f"bdate:y_page:{page - 1}"))
    if start + page_size < len(years):
        navigation.append(InlineKeyboardButton(text="بعدی", callback_data=f"bdate:y_page:{page + 1}"))
    if navigation:
        buttons.append(navigation)
    buttons.append([InlineKeyboardButton(text="لغو", callback_data="bdate:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def birth_month_keyboard() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (name, month) in enumerate(_BIRTH_MONTHS):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(text=name, callback_data=f"bdate:m:{month}"))
    buttons.append([
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data="bdate:back:year"),
        InlineKeyboardButton(text="لغو", callback_data="bdate:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def birth_day_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    days_in_month = JalaliDate.days_in_month(month, year)
    buttons: list[list[InlineKeyboardButton]] = []
    for day in range(1, days_in_month + 1):
        if (day - 1) % 7 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(text=str(day), callback_data=f"bdate:d:{day}"))
    buttons.append([
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data="bdate:back:month"),
        InlineKeyboardButton(text="لغو", callback_data="bdate:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Booking helpers ----------------------------------------------------------

def booking_months_keyboard(months: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    """months: iterable of (label, month_key)."""
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (label, month_key) in enumerate(months):
        if idx % 2 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(text=label, callback_data=f"book:month:{month_key}"))
    buttons.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def booking_days_keyboard(days: Sequence[tuple[str, str]], month_key: str) -> InlineKeyboardMarkup:
    """days: iterable of (label, jdate)."""
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (label, jdate) in enumerate(days):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(text=label, callback_data=f"book:day:{jdate}"))
    buttons.append([
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data="book:back:month"),
        InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def booking_slots_keyboard(
    slots: Sequence["SlotAvailability"],
    jdate: str,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for slot in slots:
        label = f"{slot.start_time} - {slot.end_time}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"book:slot:{slot.slot_id}")])
    buttons.append([
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"book:back:day:{jdate}"),
        InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_schedule_months_keyboard(months: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (label, month_key) in enumerate(months):
        if idx % 2 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(text=label, callback_data=f"admin:schedule:month:{month_key}"))
    buttons.append([InlineKeyboardButton(text="افزودن روز جدید", callback_data="admin:schedule:add_day")])
    buttons.append([InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_days_keyboard(
    days: Sequence[tuple[str, str]],
    month_key: str,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, (label, jdate) in enumerate(days):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(InlineKeyboardButton(text=label, callback_data=f"admin:schedule:day:{jdate}"))
    buttons.append([
        InlineKeyboardButton(text="افزودن روز", callback_data=f"admin:schedule:add_day:{month_key}"),
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin:schedule:back:months"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_slots_keyboard(
    day_id: int,
    jdate: str,
    slots: Sequence["SlotSummary"],
    day_active: bool,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for slot in slots:
        status = "فعال" if slot.is_active else "غیرفعال"
        label = f"{slot.start_time} - {slot.end_time} | وضعیت: {status}"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"admin:schedule:slot_info:{slot.slot_id}"),
        ])
        toggle_text = "غیرفعال کردن بازه" if slot.is_active else "فعال کردن بازه"
        buttons.append([
            InlineKeyboardButton(text=toggle_text, callback_data=f"admin:schedule:slot_toggle:{slot.slot_id}"),
            InlineKeyboardButton(text="حذف بازه", callback_data=f"admin:schedule:slot_delete:{slot.slot_id}"),
        ])
    toggle_day_text = "غیرفعال کردن روز" if day_active else "فعال کردن روز"
    buttons.append([InlineKeyboardButton(text="افزودن بازه جدید", callback_data=f"admin:schedule:add_slot:{day_id}")])
    buttons.append([InlineKeyboardButton(text=toggle_day_text, callback_data=f"admin:schedule:toggle_day:{day_id}")])
    buttons.append([InlineKeyboardButton(text="خروجی PDF بیماران", callback_data=f"admin:schedule:export:{day_id}:{jdate}")])
    buttons.append([InlineKeyboardButton(text="حذف روز", callback_data=f"admin:schedule:delete_day:{day_id}")])
    buttons.append([
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data=f"admin:schedule:back:days:{jdate}"),
        InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_report_months_keyboard(months: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, (label, month_key) in enumerate(months):
        if idx % 2 == 0:
            rows.append([])
        rows[-1].append(InlineKeyboardButton(text=label, callback_data=f"admin:pdf:month:{month_key}"))
    rows.append([InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_report_days_keyboard(
    days: Sequence[tuple[str, str]],
    month_key: str,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx, (label, jdate) in enumerate(days):
        if idx % 2 == 0:
            rows.append([])
        rows[-1].append(InlineKeyboardButton(text=label, callback_data=f"admin:pdf:day:{jdate}"))
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت به ماه‌ها", callback_data="admin:pdf")])
    rows.append([InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_message_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="پیام به بیمار مشخص", callback_data="admin:message:single")],
            [InlineKeyboardButton(text="پیام همگانی", callback_data="admin:message:all")],
            [InlineKeyboardButton(text="یادآوری نوبت‌ها", callback_data="admin:message:reminder")],
            [InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home")],
        ]
    )


def admin_message_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ ارسال پیام", callback_data="admin:message:confirm"),
                InlineKeyboardButton(text="❌ لغو", callback_data="admin:message:cancel"),
            ]
        ]
    )


def admin_message_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ لغو", callback_data="admin:message:cancel")]
        ]
    )


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
        buttons.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"admin:schedule:add_day_select:{jdate}",
            )
        ])
    nav_buttons: list[InlineKeyboardButton] = []
    filter_token = month_key or "-"
    if has_prev:
        nav_buttons.append(
            InlineKeyboardButton(
                text="قبلی",
                callback_data=f"admin:schedule:add_day_page:{page - 1}:{filter_token}",
            )
        )
    if has_next:
        nav_buttons.append(
            InlineKeyboardButton(
                text="بعدی",
                callback_data=f"admin:schedule:add_day_page:{page + 1}:{filter_token}",
            )
        )
    if nav_buttons:
        buttons.append(nav_buttons)
    buttons.append([
        InlineKeyboardButton(text="لغو", callback_data="admin:schedule:add_day_back"),
        InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_slot_start_keyboard(times: Sequence[str]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, label in enumerate(times):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"admin:schedule:slot_start:{label.replace(':', '-')}",
            )
        )
    buttons.append([
        InlineKeyboardButton(text="لغو", callback_data="admin:schedule:slot_back:detail"),
        InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_schedule_slot_end_keyboard(times: Sequence[str]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for idx, label in enumerate(times):
        if idx % 3 == 0:
            buttons.append([])
        buttons[-1].append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"admin:schedule:slot_end:{label.replace(':', '-')}",
            )
        )
    buttons.append([
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin:schedule:slot_back:start"),
        InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home"),
    ])
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
    buttons.append([
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin:schedule:slot_back:end"),
        InlineKeyboardButton(text="بازگشت به خانه", callback_data="menu:home"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)



