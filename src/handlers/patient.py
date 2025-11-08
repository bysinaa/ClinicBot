# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from persiantools.jdatetime import JalaliDate
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.config import settings
from src.database import SessionLocal
from src.keyboards import (
    admin_menu_inline,
    booking_days_keyboard,
    booking_months_keyboard,
    booking_slots_keyboard,
    main_menu_inline,
)
from src.models import Appointment, AppointmentStatus, PaymentStatus, Role, User
from src.services.ai_consultation import consult_medical
from src.services.booking import (
    SlotAvailability,
    count_user_bookings_for_day,
    get_available_days,
    get_day_availability,
    get_slot_by_id,
)
from src.services.clinic import get_profile
from src.services.online_consult import (
    OnlineConsultRequestStatus,
    attach_receipt as attach_online_receipt,
    create_request as create_online_request,
    get_latest_request_for_user,
    user_has_active_request,
)
from src.states import BookingStates, OnlineConsultStates

MessageLike = Union[Message, CallbackQuery]
from src.utils.jalali import (
    format_jalali_day,
    gregorian_to_jalali,
    jalali_month_name,
)

router = Router(name="patient")

PATIENT_MENU_TEXT = "لطفاً یکی از گزینه‌های منوی بیماران را انتخاب کنید:"
BOOKING_START_PROMPT = "ابتدا ماه مورد نظر برای رزرو نوبت را انتخاب کنید:"
BOOKING_DAY_PROMPT = "لطفاً تاریخ دلخواه را انتخاب نمایید:"
BOOKING_SLOT_PROMPT = "یکی از بازه‌های زمانی آزاد را انتخاب کنید:"
BOOKING_NO_AVAILABILITY = "در حال حاضر نوبت فعالی برای رزرو وجود ندارد. لطفاً بعداً دوباره بررسی کنید."
BOOKING_NEED_REGISTER = "برای رزرو نوبت ابتدا باید ثبت‌نام خود را کامل کنید."
BOOKING_LIMIT_REACHED = "شما در این تاریخ به سقف مجاز رزرو رسیده‌اید."
BOOKING_SLOT_FULL = "این بازه زمانی در حال حاضر تکمیل شده است. لطفاً گزینه دیگری را امتحان کنید."
BOOKING_DAY_EMPTY = "برای این تاریخ بازه‌ای ثبت نشده است. لطفاً تاریخ دیگری را انتخاب کنید."
BOOKING_CONFIRMATION_TEMPLATE = (
    "نوبت #{id} با موفقیت ثبت شد.\n"
    "تاریخ: {date_label}\n"
    "بازه زمانی: {time_label}\n"
    "لطفاً تصویر رسید پرداخت را ارسال کنید تا نوبت تأیید شود."
)
BOOKING_RECEIPT_PROMPT = (
    "لطفاً تصویر رسید پرداخت مربوط به نوبت #{id} را ارسال کنید. در صورت نیاز می‌توانید بعدها نیز رسید را بارگذاری نمایید."
)
BOOKING_RECEIPT_REMINDER = "برای تکمیل رزرو باید تصویر رسید پرداخت را ارسال کنید."
BOOKING_RECEIPT_SAVED = "رسید پرداخت ثبت شد. پس از بررسی ادمین نتیجه اطلاع‌رسانی می‌شود."

CONTACT_MISSING_PHONE = "شماره تماس ثبت نشده است. لطفاً با پشتیبانی مجموعه هماهنگ کنید."
ADDRESS_FALLBACK = "آدرس مطب هنوز ثبت نشده است."
ADDRESS_SELECT_PROMPT = "برای دریافت موقعیت، یکی از شعبه‌ها را انتخاب کنید."
ADDRESS_BRANCH_FALLBACK = "اطلاعات {label} هنوز ثبت نشده است."
CONTACT_SECTION_TITLES = {
    "tehran": "شعبه تهران (شهرک غرب)",
    "karaj": "شعبه کرج (برج طاق کسری)",
    "other": "سایر خطوط پشتیبانی",
}


def _normalize_dial_number(raw_number: str | None) -> str | None:
    """Return a +<country><number> format suitable for Telegram contact cards."""
    if not raw_number:
        return None
    stripped = raw_number.strip()
    digits = "".join(ch for ch in stripped if ch.isdigit() or ch == "+")
    if not digits:
        return None
    normalized = digits
    if normalized.startswith("++"):
        normalized = normalized[1:]
    if normalized.startswith("+"):
        body = "".join(ch for ch in normalized if ch.isdigit())
        return f"+{body}"
    digits_only = "".join(ch for ch in normalized if ch.isdigit())
    if digits_only.startswith("0098"):
        return f"+{digits_only[2:]}"
    if digits_only.startswith("00"):
        return f"+{digits_only[2:]}"
    if digits_only.startswith("98"):
        return f"+{digits_only}"
    if digits_only.startswith("0"):
        return f"+98{digits_only[1:]}"
    return f"+{digits_only}"


def _group_contact_numbers(pairs: Sequence[tuple[str, str]] | None) -> dict[str, list[tuple[str, str]]]:
    buckets: dict[str, list[tuple[str, str]]] = {"tehran": [], "karaj": [], "other": []}
    if not pairs:
        return buckets
    for label, phone in pairs:
        clean_label = (label or "").strip()
        clean_phone = (phone or "").strip()
        if not clean_phone:
            continue
        normalized_label = (
            clean_label.replace("ي", "ی")
            .replace("ك", "ک")
            .replace("ة", "ه")
            .lower()
        )
        key = "other"
        if "تهران" in normalized_label:
            key = "tehran"
        elif "کرج" in normalized_label:
            key = "karaj"
        buckets[key].append((clean_label or "شماره تماس", clean_phone))
    return buckets


def _build_contact_overview(pairs: Sequence[tuple[str, str]] | None) -> str:
    intro = (settings.clinic_contact_text or "").strip()
    lines: list[str] = [intro] if intro else []
    sections = _group_contact_numbers(pairs)
    for key in ("tehran", "karaj", "other"):
        entries = sections[key]
        if not entries:
            continue
        if lines:
            lines.append("")
        lines.append(f"{CONTACT_SECTION_TITLES[key]}:")
        for label, phone in entries:
            lines.append(f"• {label}: {phone}")
    if not lines:
        return CONTACT_MISSING_PHONE
    return "\n".join(lines).strip()


def _available_address_options() -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    if settings.clinic_address_tehran or (settings.clinic_tehran_lat is not None and settings.clinic_tehran_lon is not None):
        options.append(("tehran", "مطب تهران"))
    if settings.clinic_address_karaj or (settings.clinic_karaj_lat is not None and settings.clinic_karaj_lon is not None):
        options.append(("karaj", "مطب کرج"))
    return options


def _address_city_info(city_key: str) -> dict[str, str | float | None] | None:
    mapping = {
        "tehran": {
            "label": "مطب تهران",
            "address": settings.clinic_address_tehran,
            "lat": settings.clinic_tehran_lat,
            "lon": settings.clinic_tehran_lon,
        },
        "karaj": {
            "label": "مطب کرج",
            "address": settings.clinic_address_karaj,
            "lat": settings.clinic_karaj_lat,
            "lon": settings.clinic_karaj_lon,
        },
    }
    return mapping.get(city_key)


def _address_keyboard(options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if options:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"address:city:{slug}") for slug, label in options])
    rows.append(
        [
            InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home"),
            InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_location_with_text(bot, chat_id: int, *, lat: float | None, lon: float | None, text: str | None) -> None:
    if lat is None or lon is None:
        if text:
            await bot.send_message(chat_id=chat_id, text=text)
        return
    await bot.send_location(chat_id=chat_id, latitude=lat, longitude=lon)
    if text:
        await bot.send_message(chat_id=chat_id, text=text)

ONLINE_CONSULT_PROMPT_NEW = "لطفاً سؤال خود را ارسال کنید تا درخواست مشاوره آنلاین ثبت شود."
ONLINE_CONSULT_NEED_REGISTER = "برای استفاده از مشاوره آنلاین ابتدا باید ثبت‌نام کنید."
ONLINE_CONSULT_ALREADY_ACTIVE = "شما یک درخواست فعال در حال بررسی دارید."
ONLINE_CONSULT_RECEIPT_PROMPT = "تصویر رسید پرداخت را ارسال کنید یا عبارت cancel را برای لغو بنویسید."
ONLINE_CONSULT_RECEIPT_CONFIRMED = "رسید پرداخت دریافت شد. پس از بررسی ادمین اطلاع‌رسانی می‌شود."
ONLINE_CONSULT_CANCELLED = "فرایند مشاوره آنلاین لغو شد."

def _admin_receipt_keyboard(appointment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="تأیید پرداخت", callback_data=f"admin:payment:approve:{appointment_id}"),
            InlineKeyboardButton(text="رد پرداخت", callback_data=f"admin:payment:reject:{appointment_id}"),
        ]]
    )


async def _notify_admins_payment(bot, appointment_info: dict, file_id: str) -> None:
    if not settings.admin_ids:
        return
    caption_lines = [
        f"رسید پرداخت جدید برای نوبت #{appointment_info['id']}",
        f"بیمار: {appointment_info['patient_name']}",
        f"تاریخ: {appointment_info['jdate']}",
        f"بازه زمانی: {appointment_info['time_label']}",
        f"شماره تماس: {appointment_info['phone']}",
    ]
    caption = "\n".join(caption_lines)
    markup = _admin_receipt_keyboard(appointment_info['id'])
    for admin_id in settings.admin_ids:
        try:
            await bot.send_photo(chat_id=admin_id, photo=file_id, caption=caption, reply_markup=markup)
        except Exception:
            continue

# ----------------------------- State Keys -----------------------------
STATE_MONTHS_KEY = "booking_months"
STATE_SELECTED_MONTH = "selected_month"
STATE_SELECTED_DAY = "selected_day"
STATE_APPOINTMENT_ID = "appointment_id"
ONLINE_STATE_REQUEST_ID = "online_request_id"

BOOKING_RANGE_DAYS = 180
BOOKING_MAX_PER_DAY = 2


# ----------------------------- Helper Functions -----------------------------
def _is_registered(user: Optional[User]) -> bool:
    return bool(user and user.phone)


def _is_admin_user(current_user: Optional[User], telegram_id: int) -> bool:
    if current_user and current_user.role == Role.admin:
        return True
    return telegram_id in settings.admin_ids


def _menu_keyboard(current_user: Optional[User], telegram_id: int) -> InlineKeyboardMarkup:
    if _is_admin_user(current_user, telegram_id):
        return admin_menu_inline()
    return main_menu_inline(is_registered=_is_registered(current_user))


def _resolve_message(target: MessageLike) -> tuple[Message, bool]:
    if isinstance(target, CallbackQuery):
        return target.message, True
    return target, False


async def _respond(
    target: MessageLike,
    text: str,
    *,
    keyboard: Optional[InlineKeyboardMarkup] = None,
    edit: Optional[bool] = None,
) -> Message:
    message, default_edit = _resolve_message(target)
    do_edit = default_edit if edit is None else edit
    if do_edit:
        try:
            return await message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest:
            return await message.answer(text, reply_markup=keyboard)
    return await message.answer(text, reply_markup=keyboard)


async def _show_main_menu(
    target: MessageLike,
    state: FSMContext,
    current_user: Optional[User],
    *,
    telegram_id: Optional[int] = None,
    text: Optional[str] = None,
    edit: Optional[bool] = None,
) -> None:
    if telegram_id is None:
        if isinstance(target, CallbackQuery):
            telegram_id = target.from_user.id
        elif isinstance(target, Message):
            telegram_id = target.from_user.id
    telegram_id = telegram_id or 0
    keyboard = _menu_keyboard(current_user, telegram_id)
    await _respond(target, text or PATIENT_MENU_TEXT, keyboard=keyboard, edit=edit)


async def _ensure_registered_user(
    target: MessageLike,
    state: FSMContext,
    current_user: Optional[User],
) -> bool:
    if isinstance(target, CallbackQuery):
        telegram_id = target.from_user.id
    elif isinstance(target, Message):
        telegram_id = target.from_user.id
    else:
        telegram_id = 0
    if _is_admin_user(current_user, telegram_id) or _is_registered(current_user):
        return True
    await state.clear()
    await _show_main_menu(
        target,
        state,
        current_user,
        telegram_id=telegram_id,
        text=BOOKING_NEED_REGISTER,
        edit=True,
    )
    return False


def _build_month_map(days: Iterable[date]) -> Dict[str, Dict[str, Any]]:
    month_data: Dict[str, Dict[str, Any]] = {}
    for g_date in days:
        jalali = gregorian_to_jalali(g_date)
        month_key = f"{jalali.year:04d}-{jalali.month:02d}"
        day_entry = {
            "jdate": jalali.strftime("%Y-%m-%d"),
            "label": format_jalali_day(jalali),
        }
        month_info = month_data.setdefault(
            month_key,
            {
                "label": f"{jalali_month_name(jalali.month)} {jalali.year}",
                "days": [],
            },
        )
        month_info["days"].append(day_entry)
    for info in month_data.values():
        info["days"].sort(key=lambda item: item["jdate"])
    return dict(sorted(month_data.items(), key=lambda item: item[0]))


async def _refresh_month_map(state: FSMContext) -> Dict[str, Dict[str, Any]]:
    async with SessionLocal() as session:
        today = date.today()
        end = today + timedelta(days=BOOKING_RANGE_DAYS)
        schedule_days = await get_available_days(session, today, end)
    month_map = _build_month_map(day.date for day in schedule_days)
    await state.update_data(
        {
            STATE_MONTHS_KEY: month_map,
            STATE_SELECTED_MONTH: None,
            STATE_SELECTED_DAY: None,
        }
    )
    return month_map


def _month_keyboard(month_map: Dict[str, Dict[str, Any]]) -> InlineKeyboardMarkup:
    items = [(info["label"], key) for key, info in month_map.items()]
    return booking_months_keyboard(items)


def _day_keyboard(month_map: Dict[str, Dict[str, Any]], month_key: str) -> InlineKeyboardMarkup:
    days = month_map[month_key]["days"]
    items = [(item["label"], item["jdate"]) for item in days]
    return booking_days_keyboard(items, month_key)


def _slot_keyboard(slots: Sequence[SlotAvailability], jdate: str) -> InlineKeyboardMarkup:
    return booking_slots_keyboard(slots, jdate)


async def _latest_open_appointment(session, user_id: int) -> Optional[Appointment]:
    result = await session.execute(
        select(Appointment)
        .where(Appointment.user_id == user_id)
        .order_by(Appointment.created_at.desc())
        .limit(1)
    )
    appt = result.scalars().first()
    if appt and appt.status != AppointmentStatus.canceled:
        return appt
    return None


# ----------------------------- منوی اصلی -----------------------------
@router.callback_query(F.data == "menu:home")
async def menu_home(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    await state.clear()
    await _show_main_menu(c, state, current_user, edit=True)
    await c.answer()


# ----------------------------- اطلاعات تماس -----------------------------
@router.callback_query(F.data == "menu:contact")
async def menu_contact(c: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        profile = await get_profile(session)
    contact_pairs: list[tuple[str, str]] = list(settings.clinic_contact_numbers)
    if not contact_pairs and profile.phone_number:
        contact_pairs = [(profile.phone_label or "شماره کلینیک", profile.phone_number)]
    await state.update_data({"contact_numbers": contact_pairs})
    text = _build_contact_overview(contact_pairs)
    keyboard_rows: List[List[InlineKeyboardButton]] = []
    for idx, (label, phone) in enumerate(contact_pairs):
        button_text = f"{label} • {phone}"
        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=button_text,
                    callback_data=f"contact:call:{idx}",
                )
            ]
        )
    keyboard_rows.append(
        [
            InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home"),
            InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home"),
        ]
    )
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await _respond(c, text, keyboard=markup, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("contact:call:"))
async def menu_contact_call(c: CallbackQuery, state: FSMContext):
    idx_token = c.data.split(":", 2)[-1]
    try:
        index = int(idx_token)
    except ValueError:
        await c.answer("درخواست نامعتبر است.", show_alert=True)
        return
    data = await state.get_data()
    contact_pairs: list[tuple[str, str]] = data.get("contact_numbers") or list(settings.clinic_contact_numbers)
    if not contact_pairs:
        async with SessionLocal() as session:
            profile = await get_profile(session)
        if profile.phone_number:
            contact_pairs = [(profile.phone_label or "شماره کلینیک", profile.phone_number)]
    if index < 0 or index >= len(contact_pairs):
        await c.answer("این شماره در دسترس نیست.", show_alert=True)
        return
    label, raw_number = contact_pairs[index]
    number = _normalize_dial_number(raw_number)
    if not number:
        await c.answer("ارسال شماره ممکن نشد.", show_alert=True)
        return
    await c.message.answer_contact(phone_number=number, first_name=label)
    await c.answer("شماره تماس ارسال شد.")


@router.callback_query(F.data == "menu:address")
async def menu_address(c: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        profile = await get_profile(session)
    options = _available_address_options()
    if options:
        body_parts = [profile.address_text] if profile.address_text else []
        body_parts.append(ADDRESS_SELECT_PROMPT)
        text = "\n\n".join(body_parts)
        markup = _address_keyboard(options)
        await _respond(c, text or ADDRESS_SELECT_PROMPT, keyboard=markup, edit=True)
    else:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home"),
                    InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="menu:home"),
                ]
            ]
        )
        text = profile.address_text or ADDRESS_FALLBACK
        await _respond(c, text, keyboard=markup, edit=True)
        await _send_location_with_text(
            c.message.bot,
            c.message.chat.id,
            lat=profile.location_lat,
            lon=profile.location_lon,
            text=text,
        )
    await c.answer()


@router.callback_query(F.data.startswith("address:city:"))
async def menu_address_city(c: CallbackQuery, state: FSMContext):
    city_key = c.data.split(":", 2)[-1]
    options = _available_address_options()
    info = _address_city_info(city_key)
    if not info or city_key not in {slug for slug, _ in options}:
        await c.answer("اطلاعات این شعبه موجود نیست.", show_alert=True)
        return
    text = info["address"] or ADDRESS_BRANCH_FALLBACK.format(label=info["label"])
    markup = _address_keyboard(options)
    await _respond(c, text, keyboard=markup, edit=True)
    await _send_location_with_text(
        c.message.bot,
        c.message.chat.id,
        lat=info["lat"],
        lon=info["lon"],
        text=f"{info['label']}\n{text}" if text else info["label"],
    )
    await c.answer()


# ----------------------------- رزرو نوبت -----------------------------
@router.callback_query(F.data == "menu:book")
async def menu_book(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not await _ensure_registered_user(c, state, current_user):
        await c.answer()
        return
    month_map = await _refresh_month_map(state)
    if not month_map:
        await state.clear()
        await _show_main_menu(c, state, current_user, text=BOOKING_NO_AVAILABILITY, edit=True)
        await c.answer()
        return
    await state.set_state(BookingStates.choosing_month)
    keyboard = _month_keyboard(month_map)
    await _respond(c, BOOKING_START_PROMPT, keyboard=keyboard, edit=True)
    await c.answer()


@router.callback_query(BookingStates.choosing_month, F.data.startswith("book:month:"))
async def choose_month(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    month_key = c.data.split(":", 2)[2]
    data = await state.get_data()
    month_map: Dict[str, Dict[str, Any]] = data.get(STATE_MONTHS_KEY, {})
    if month_key not in month_map:
        month_map = await _refresh_month_map(state)
        if month_key not in month_map:
            await _respond(c, BOOKING_NO_AVAILABILITY, edit=True)
            await state.clear()
            await _show_main_menu(c, state, current_user, edit=True)
            await c.answer()
            return
    if not month_map[month_key]["days"]:
        await _respond(c, BOOKING_DAY_EMPTY, edit=True)
        await c.answer()
        return
    keyboard = _day_keyboard(month_map, month_key)
    await state.update_data({STATE_SELECTED_MONTH: month_key})
    await state.set_state(BookingStates.choosing_day)
    await _respond(c, BOOKING_DAY_PROMPT, keyboard=keyboard, edit=True)
    await c.answer()


@router.callback_query(BookingStates.choosing_day, F.data.startswith("book:day:"))
async def choose_day(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    jdate = c.data.split(":", 2)[2]
    data = await state.get_data()
    month_key = data.get(STATE_SELECTED_MONTH)
    month_map: Dict[str, Dict[str, Any]] = data.get(STATE_MONTHS_KEY, {})
    if not month_key or month_key not in month_map:
        await menu_book(c, state, current_user)
        await c.answer()
        return
    if not any(day["jdate"] == jdate for day in month_map[month_key]["days"]):
        await c.answer("تاریخ انتخابی معتبر نیست.", show_alert=True)
        return
    async with SessionLocal() as session:
        availability = await get_day_availability(session, jdate)
    if not availability:
        await _respond(c, BOOKING_DAY_EMPTY, edit=True)
        await state.set_state(BookingStates.choosing_month)
        keyboard = _month_keyboard(month_map)
        await _respond(c, BOOKING_START_PROMPT, keyboard=keyboard, edit=True)
        await c.answer()
        return
    keyboard = _slot_keyboard(availability, jdate)
    await state.update_data({STATE_SELECTED_DAY: jdate})
    await state.set_state(BookingStates.choosing_slot)
    await _respond(c, BOOKING_SLOT_PROMPT, keyboard=keyboard, edit=True)
    await c.answer()


@router.callback_query(BookingStates.choosing_slot, F.data.startswith("book:slot:"))
async def choose_slot(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    slot_id = int(c.data.split(":", 2)[2])
    data = await state.get_data()
    jdate: Optional[str] = data.get(STATE_SELECTED_DAY)
    if not jdate:
        await c.answer("لطفاً ابتدا تاریخ را انتخاب کنید.", show_alert=True)
        return
    async with SessionLocal() as session:
        user = await _ensure_registered(session, c.from_user.id)
        if not user:
            await c.answer(BOOKING_NEED_REGISTER, show_alert=True)
            await state.clear()
            return
        slot = await get_slot_by_id(session, slot_id)
        if not slot or not slot.is_active or not slot.day.is_active:
            await c.answer("این بازه دیگر در دسترس نیست.", show_alert=True)
            return
        availability = await get_day_availability(session, jdate)
        availability_map = {item.slot_id: item for item in availability}
        slot_info = availability_map.get(slot_id)
        if not slot_info or slot_info.remaining <= 0:
            await c.answer(BOOKING_SLOT_FULL, show_alert=True)
            return
        existing_count = await count_user_bookings_for_day(session, user.id, jdate)
        if existing_count >= BOOKING_MAX_PER_DAY:
            await c.answer(BOOKING_LIMIT_REACHED, show_alert=True)
            return
        time_label = f"{slot_info.start_time} - {slot_info.end_time}"
        appointment = Appointment(
            user_id=user.id,
            slot_id=slot_id,
            jdate=jdate,
            time_slot=time_label,
            payment_status=PaymentStatus.unpaid,
        )
        session.add(appointment)
        await session.commit()
        await session.refresh(appointment)
        await state.update_data({STATE_APPOINTMENT_ID: appointment.id})
    await state.set_state(BookingStates.waiting_receipt)
    year, month, day = map(int, jdate.split("-"))
    jalali = JalaliDate(year, month, day)
    date_label = format_jalali_day(jalali)
    time_label = f"{slot_info.start_time} - {slot_info.end_time}"
    confirmation = BOOKING_CONFIRMATION_TEMPLATE.format(
        id=appointment.id,
        date_label=date_label,
        time_label=time_label,
    )
    await _respond(
        c,
        confirmation,
        keyboard=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]]
        ),
        edit=True,
    )
    await c.answer()


@router.callback_query(F.data == "book:back:month")
async def back_to_month(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    data = await state.get_data()
    month_map: Dict[str, Dict[str, Any]] = data.get(STATE_MONTHS_KEY, {})
    if not month_map:
        month_map = await _refresh_month_map(state)
    if not month_map:
        await state.clear()
        await _show_main_menu(c, state, current_user, text=BOOKING_NO_AVAILABILITY, edit=True)
        await c.answer()
        return
    keyboard = _month_keyboard(month_map)
    await state.set_state(BookingStates.choosing_month)
    await _respond(c, BOOKING_START_PROMPT, keyboard=keyboard, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("book:back:day:"))
async def back_to_days(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    month_key = data.get(STATE_SELECTED_MONTH)
    month_map: Dict[str, Dict[str, Any]] = data.get(STATE_MONTHS_KEY, {})
    if not month_key or month_key not in month_map:
        await c.answer()
        return
    keyboard = _day_keyboard(month_map, month_key)
    await state.set_state(BookingStates.choosing_day)
    await _respond(c, BOOKING_DAY_PROMPT, keyboard=keyboard, edit=True)
    await c.answer()


@router.message(BookingStates.waiting_receipt, F.photo)
async def receive_receipt(m: Message, state: FSMContext):
    data = await state.get_data()
    appointment_id = data.get(STATE_APPOINTMENT_ID)
    if not appointment_id:
        await m.answer(BOOKING_RECEIPT_REMINDER)
        return
    file_id = m.photo[-1].file_id
    async with SessionLocal() as session:
        appointment = await session.get(
            Appointment,
            appointment_id,
            options=(
                selectinload(Appointment.user),
                selectinload(Appointment.slot),
            ),
        )
        if not appointment:
            await m.answer("نوبت مورد نظر یافت نشد.")
            await state.clear()
            return
        appointment.receipt_file_id = file_id
        appointment.payment_status = PaymentStatus.awaiting_confirmation
        await session.commit()
        await session.refresh(appointment)
        user = appointment.user
        slot = appointment.slot
        if slot:
            time_label = f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}"
        else:
            time_label = appointment.time_slot or "-"
        notify_info = {
            "id": appointment.id,
            "jdate": appointment.jdate,
            "time_label": time_label,
            "patient_name": (user.full_name if user and user.full_name else "-"),
            "phone": (user.phone if user and user.phone else "-"),
        }
    await state.clear()
    await m.answer(BOOKING_RECEIPT_SAVED)
    await _notify_admins_payment(m.bot, notify_info, file_id)


@router.message(BookingStates.waiting_receipt)
async def receive_receipt_text(m: Message):
    await m.answer(BOOKING_RECEIPT_REMINDER)


# ----------------------------- ارسال رسید از منو -----------------------------
@router.callback_query(F.data == "menu:receipt")
async def menu_receipt(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not await _ensure_registered_user(c, state, current_user):
        await c.answer()
        return
    async with SessionLocal() as session:
        user = await _ensure_registered(session, c.from_user.id)
        if not user:
            await _respond(c, BOOKING_NEED_REGISTER, edit=True)
            await c.answer()
            return
        appointment = await _latest_open_appointment(session, user.id)
    if not appointment:
        await _respond(
            c,
            "نوبت فعالی برای ارسال رسید یافت نشد. در صورت ثبت نوبت جدید، از همین بخش می‌توانید رسید را ارسال کنید.",
            keyboard=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]]
            ),
            edit=True,
        )
        await c.answer()
        return
    await state.set_state(BookingStates.waiting_receipt)
    await state.update_data({STATE_APPOINTMENT_ID: appointment.id})
    await _respond(
        c,
        BOOKING_RECEIPT_PROMPT.format(id=appointment.id),
        keyboard=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]]
        ),
        edit=True,
    )
    await c.answer()


# ----------------------------- مشاوره آنلاین -----------------------------
def _online_status_text(status: OnlineConsultRequestStatus) -> str:
    mapping = {
        OnlineConsultRequestStatus.pending: "در انتظار دریافت رسید پرداخت",
        OnlineConsultRequestStatus.awaiting_confirmation: "در انتظار تأیید ادمین",
        OnlineConsultRequestStatus.approved: "تأیید شده و در انتظار پاسخ",
        OnlineConsultRequestStatus.rejected: "رد شده",
        OnlineConsultRequestStatus.completed: "تکمیل شده",
    }
    return mapping.get(status, status.value)


def _online_request_summary(request, label: str) -> str:
    return (
        f"{label}\n"
        f"وضعیت: {_online_status_text(request.status)}\n"
        f"ثبت: {request.created_at:%Y-%m-%d %H:%M}"
    )


@router.callback_query(F.data == "menu:online")
async def menu_online(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not await _ensure_registered_user(c, state, current_user):
        await c.answer()
        return
    async with SessionLocal() as session:
        user = await _ensure_registered(session, c.from_user.id)
        if not user:
            await _respond(c, ONLINE_CONSULT_NEED_REGISTER, edit=True)
            await c.answer()
            return
        latest = await get_latest_request_for_user(session, user.id)
    if latest and latest.status in {
        OnlineConsultRequestStatus.pending,
        OnlineConsultRequestStatus.awaiting_confirmation,
        OnlineConsultRequestStatus.approved,
    }:
        text = _online_request_summary(latest, "شما یک درخواست فعال دارید.")
        keyboard_rows: List[List[InlineKeyboardButton]] = []
        if latest.status == OnlineConsultRequestStatus.pending:
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        text="ارسال رسید پرداخت",
                        callback_data=f"online:receipt:{latest.id}",
                    )
                ]
            )
        keyboard_rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")])
        await _respond(
            c,
            text,
            keyboard=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
            edit=True,
        )
        await c.answer()
        return
    await state.set_state(OnlineConsultStates.waiting_question)
    await state.update_data({ONLINE_STATE_REQUEST_ID: None})
    await _respond(
        c,
        ONLINE_CONSULT_PROMPT_NEW,
        keyboard=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="لغو", callback_data="menu:home")]]
        ),
        edit=True,
    )
    await c.answer()


@router.message(OnlineConsultStates.waiting_question)
async def online_question(m: Message, state: FSMContext):
    question = (m.text or "").strip()
    if not question:
        await m.answer("سؤال نامعتبر است. لطفاً دوباره تلاش کنید.")
        return
    async with SessionLocal() as session:
        user = await _ensure_registered(session, m.from_user.id)
        if not user:
            await m.answer(ONLINE_CONSULT_NEED_REGISTER)
            await state.clear()
            return
        if await user_has_active_request(session, user.id):
            await m.answer(ONLINE_CONSULT_ALREADY_ACTIVE)
            await state.clear()
            return
        request = await create_online_request(session, user, question)
    await state.set_state(OnlineConsultStates.waiting_receipt)
    await state.update_data({ONLINE_STATE_REQUEST_ID: request.id})
    await m.answer(
        "سؤال شما ثبت شد. لطفاً رسید پرداخت را به صورت عکس ارسال کنید یا «cancel» بفرستید.",
    )


@router.message(OnlineConsultStates.waiting_receipt, F.photo)
async def online_receipt_photo(m: Message, state: FSMContext):
    data = await state.get_data()
    request_id = data.get(ONLINE_STATE_REQUEST_ID)
    if not request_id:
        await m.answer(ONLINE_CONSULT_CANCELLED)
        await state.clear()
        return
    file_id = m.photo[-1].file_id
    async with SessionLocal() as session:
        success = await attach_online_receipt(session, request_id, file_id)
    if not success:
        await m.answer("ارسال رسید با مشکل مواجه شد. لطفاً دوباره تلاش کنید.")
        return
    await state.clear()
    await m.answer(ONLINE_CONSULT_RECEIPT_CONFIRMED)


@router.message(OnlineConsultStates.waiting_receipt)
async def online_receipt_text(m: Message, state: FSMContext):
    if (m.text or "").strip().lower() in {"cancel", "/cancel", "لغو"}:
        await state.clear()
        await m.answer(ONLINE_CONSULT_CANCELLED)
        return
    await m.answer(ONLINE_CONSULT_RECEIPT_PROMPT)


# ----------------------------- مشاوره هوشمند -----------------------------
@router.callback_query(F.data == "menu:consult")
async def menu_consult(c: CallbackQuery, state: FSMContext):
    if not settings.openai_api_key:
        await _respond(
            c,
            "امکان مشاوره هوشمند فعال نیست. لطفاً با پشتیبانی تماس بگیرید.",
            keyboard=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]]
            ),
            edit=True,
        )
        await c.answer()
        return
    await _respond(
        c,
        "سؤال پزشکی خود را به صورت متن ارسال کنید. پاسخ هوشمند با هدف اطلاع‌رسانی عمومی ارائه می‌شود.",
        keyboard=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]]
        ),
        edit=True,
    )
    await c.answer()


@router.message(StateFilter(None))
async def fallback_ai_consult(m: Message):
    if not settings.openai_api_key:
        return
    if m.text and len(m.text.strip()) >= 5:
        response = await consult_medical(m.text)
        await m.answer(response)


# ----------------------------- توابع کمکی ثبت نام -----------------------------
async def _ensure_registered(session, tg_user_id: int) -> Optional[User]:
    result = await session.execute(select(User).where(User.tg_id == tg_user_id))
    return result.scalar_one_or_none()



