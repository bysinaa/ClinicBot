from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from persiantools.jdatetime import JalaliDate
from sqlalchemy import select

from src.config import settings
from src.database import SessionLocal
from src.keyboards import (
    booking_days_keyboard,
    booking_months_keyboard,
    booking_slots_keyboard,
)
from src.models import Appointment, PaymentStatus, User
from src.services.booking import (
    SlotAvailability,
    count_user_bookings_for_day,
    get_available_days,
    get_day_availability,
    get_slot_by_id,
)
from src.services.payment import link_receipt
from src.services.clinic import get_profile
from src.services.ai_consultation import consult_medical
from src.services.online_consult import (
    OnlineConsultRequestStatus,
    attach_receipt as attach_online_receipt,
    create_request as create_online_request,
    get_latest_request_for_user,
    user_has_active_request,
)
from src.states import BookingStates, OnlineConsultStates
from src.utils.jalali import (
    format_jalali_day,
    gregorian_to_jalali,
    gregorian_to_jalali_str,
    jalali_month_name,
)

router = Router(name="patient")

BOOKING_START_PROMPT = "یکی از ماه‌های دارای نوبت را انتخاب کنید:"
BOOKING_DAY_PROMPT = "یک تاریخ را انتخاب کنید:"  # Jalali dates  # Jalali dates
BOOKING_SLOT_PROMPT = "یکی از بازه‌های زمانی زیر را انتخاب کنید:"  # Inline slots list  # Inline slots list
BOOKING_NO_AVAILABILITY = "در حال حاضر نوبت فعالی تعریف نشده است. لطفاً بعداً بررسی کنید."
BOOKING_NEED_REGISTER = "ابتدا ثبت‌نام خود را کامل کنید، سپس می‌توانید نوبت رزرو کنید."
BOOKING_LIMIT_REACHED = "شما در این تاریخ حداکثر ۲ نوبت رزرو کرده‌اید و امکان رزرو بیشتر وجود ندارد."
BOOKING_SLOT_FULL = "ظرفیت این بازه تکمیل شده است. لطفاً بازه دیگری را انتخاب کنید."
BOOKING_CONFIRMATION = (
    "نوبت شما ثبت شد. برای تکمیل فرایند، رسید پرداخت را به صورت عکس ارسال کنید تا ادمین تأیید کند."
)
BOOKING_DAY_EMPTY = "در این تاریخ نوبتی موجود نیست. تاریخ دیگری را انتخاب کنید."

ONLINE_CONSULT_PROMPT_NEW = "Please send your question to begin the online consult."
ONLINE_CONSULT_PENDING = "Your question is recorded. Please send the payment receipt photo for review."
ONLINE_CONSULT_WAITING = "Receipt received. Your request is waiting for admin review."
ONLINE_CONSULT_APPROVED = "Payment confirmed. The consultant will reply soon."
ONLINE_CONSULT_REJECTED = "Payment was not approved. You can submit a new request."
ONLINE_CONSULT_COMPLETED = "Your online consult is complete. Submit a new request for additional questions."
ONLINE_CONSULT_NEED_REGISTER = "Please complete registration before using online consult."
ONLINE_CONSULT_RECEIPT_PROMPT = "Send the bank transfer receipt as a photo."
ONLINE_CONSULT_ALREADY_ACTIVE = "You already have an online consult in progress."
ONLINE_CONSULT_RECEIPT_RECEIVED = "Online consult receipt received ✅\nWe will notify you after admin approval."
ONLINE_CONSULT_CANCELLED = "Operation cancelled."
ONLINE_STATE_REQUEST_ID = "online_request_id"
STATE_MONTHS_KEY = "booking_months"
STATE_SELECTED_MONTH = "selected_month"
STATE_SELECTED_DAY = "selected_day"
STATE_APPOINTMENT_ID = "appointment_id"

BOOKING_RANGE_DAYS = 60
BOOKING_MAX_PER_DAY = 2


async def _ensure_registered(session, tg_user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_user_id))
    return result.scalar_one_or_none()


def _build_month_map(days: List[date]) -> Dict[str, Dict[str, Any]]:
    month_data: Dict[str, Dict[str, Any]] = {}
    for g_date in days:
        jalali = gregorian_to_jalali(g_date)
        month_key = f"{jalali.year}-{jalali.month:02d}"
        month_label = f"{jalali_month_name(jalali.month)} {jalali.year}"
        day_entry = {
            "jdate": jalali.strftime("%Y-%m-%d"),
            "label": format_jalali_day(jalali),
        }
        month_info = month_data.setdefault(
            month_key,
            {
                "label": month_label,
                "days": [],
            },
        )
        month_info["days"].append(day_entry)
    for info in month_data.values():
        info["days"].sort(key=lambda item: item["jdate"])
    return dict(sorted(month_data.items(), key=lambda item: item[0]))


async def _load_month_keyboard(state: FSMContext) -> InlineKeyboardMarkup | None:
    async with SessionLocal() as session:
        today = date.today()
        end = today + timedelta(days=BOOKING_RANGE_DAYS)
        schedule_days = await get_available_days(session, today, end)
        if not schedule_days:
            await state.update_data({STATE_MONTHS_KEY: {}})
            return None
        day_list = [day.date for day in schedule_days]
        month_map = _build_month_map(day_list)
        await state.update_data({STATE_MONTHS_KEY: month_map})
        months_keyboard = booking_months_keyboard(
            [(info["label"], key) for key, info in month_map.items()]
        )
        return months_keyboard


async def _show_months(message: Message, state: FSMContext, *, edit: bool) -> None:
    keyboard = await _load_month_keyboard(state)
    if not keyboard:
        if edit:
            await message.edit_text(BOOKING_NO_AVAILABILITY)
        else:
            await message.answer(BOOKING_NO_AVAILABILITY)
        await state.clear()
        return
    await state.set_state(BookingStates.choosing_month)
    if edit:
        await message.edit_text(BOOKING_START_PROMPT, reply_markup=keyboard)
    else:
        await message.answer(BOOKING_START_PROMPT, reply_markup=keyboard)


@router.callback_query(F.data == "menu:contact")
async def menu_contact(c: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        profile = await get_profile(session)
    if profile.phone_number:
        label = profile.phone_label or "تماس با مطب"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=label, url=f"tel:{profile.phone_number}")],
            [InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")],
        ])
        text_msg = f"برای تماس روی دکمه زیر بزنید:\n{profile.phone_number}"
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]])
        text_msg = "شماره تماس ثبت نشده است. لطفاً با ادمین مجموعه هماهنگ شوید."
    await c.message.edit_text(text_msg, reply_markup=keyboard)
    await c.answer()


@router.callback_query(F.data == "menu:address")
async def menu_address(c: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        profile = await get_profile(session)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]])
    text_msg = profile.address_text or "آدرس مطب هنوز ثبت نشده است."
    await c.message.edit_text(text_msg, reply_markup=keyboard)
    if profile.location_lat is not None and profile.location_lon is not None:
        await c.message.bot.send_location(
            chat_id=c.message.chat.id,
            latitude=profile.location_lat,
            longitude=profile.location_lon,
        )
    await c.answer()


@router.callback_query(F.data == "menu:online")
async def menu_online(c: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        user = await _ensure_registered(session, c.from_user.id)
        if not user:
            await c.message.edit_text(
                ONLINE_CONSULT_NEED_REGISTER,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back", callback_data="menu:home")]]
                ),
            )
            await c.answer()
            return
        latest = await get_latest_request_for_user(session, user.id)
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    if latest is None or latest.status in {OnlineConsultRequestStatus.completed, OnlineConsultRequestStatus.rejected}:
        keyboard_rows.append([InlineKeyboardButton(text="Start online consult", callback_data="online:start")])
        text_msg = "To get an online consultation, tap \"Start online consult\" and send your question."
    else:
        if latest.status == OnlineConsultRequestStatus.pending:
            keyboard_rows.append([
                InlineKeyboardButton(text="Upload receipt", callback_data=f"online:receipt:{latest.id}"),
            ])
            text_msg = ONLINE_CONSULT_PENDING
        elif latest.status == OnlineConsultRequestStatus.awaiting_confirmation:
            text_msg = ONLINE_CONSULT_WAITING
        elif latest.status == OnlineConsultRequestStatus.approved:
            text_msg = ONLINE_CONSULT_APPROVED
        else:
            text_msg = ONLINE_CONSULT_COMPLETED
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="menu:home")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    await c.message.edit_text(text_msg, reply_markup=keyboard)
    await c.answer()


@router.callback_query(F.data == "online:start")
async def online_start(c: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        user = await _ensure_registered(session, c.from_user.id)
        if not user:
            await c.answer(ONLINE_CONSULT_NEED_REGISTER, show_alert=True)
            return
        if await user_has_active_request(session, user.id):
            await c.answer(ONLINE_CONSULT_ALREADY_ACTIVE, show_alert=True)
            return
    await state.set_state(OnlineConsultStates.waiting_question)
    await state.update_data({ONLINE_STATE_REQUEST_ID: None})
    await c.message.edit_text(
        ONLINE_CONSULT_PROMPT_NEW,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Cancel", callback_data="menu:online")]]
        ),
    )
    await c.answer()


@router.message(OnlineConsultStates.waiting_question)
async def online_collect_question(m: Message, state: FSMContext):
    if not m.text:
        await m.answer("Please provide a bit more detail in your question.")
        return
    raw = m.text.strip()
    if raw.lower() in {"cancel", "/cancel"}:
        await state.clear()
        await m.answer(ONLINE_CONSULT_CANCELLED)
        return
    if len(raw) < 5:
        await m.answer("Please provide a bit more detail in your question.")
        return
    async with SessionLocal() as session:
        user = await _ensure_registered(session, m.from_user.id)
        if not user:
            await m.answer(ONLINE_CONSULT_NEED_REGISTER)
            await state.clear()
            return
        request = await create_online_request(session, user, m.text)
    await state.set_state(OnlineConsultStates.waiting_receipt)
    await state.update_data({ONLINE_STATE_REQUEST_ID: request.id})
    await m.answer(ONLINE_CONSULT_RECEIPT_PROMPT)


@router.callback_query(F.data.startswith("online:receipt:"))
async def online_prompt_receipt(c: CallbackQuery, state: FSMContext):
    request_id = int(c.data.split(":", 2)[2])
    await state.set_state(OnlineConsultStates.waiting_receipt)
    await state.update_data({ONLINE_STATE_REQUEST_ID: request_id})
    await c.message.answer(ONLINE_CONSULT_RECEIPT_PROMPT)
    await c.answer()


@router.message(OnlineConsultStates.waiting_receipt, F.photo)
async def online_receive_receipt(m: Message, state: FSMContext):
    data = await state.get_data()
    request_id = data.get(ONLINE_STATE_REQUEST_ID)
    if not request_id:
        await state.clear()
        await m.answer(ONLINE_CONSULT_CANCELLED)
        return
    file_id = m.photo[-1].file_id
    async with SessionLocal() as session:
        success = await attach_online_receipt(session, request_id, file_id)
    if not success:
        await m.answer("در ذخیره رسید مشکلی پیش آمد. لطفاً دوباره تلاش کنید.")
        return
    await state.clear()
    await m.answer(ONLINE_CONSULT_RECEIPT_RECEIVED)


@router.message(OnlineConsultStates.waiting_receipt)
async def online_waiting_receipt_text(m: Message, state: FSMContext):
    if m.text and m.text.strip().lower() in {"cancel", "/cancel", "لغو"}:
        await state.clear()
        await m.answer(ONLINE_CONSULT_CANCELLED)
    else:
        await m.answer("Please send the payment receipt as a photo, or type 'cancel' to abort.")


@router.callback_query(F.data == "menu:receipt")
async def menu_receipt(c: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]])
    text_msg = "برای ارسال رسید، تصویر را همراه با شناسه نوبت ارسال کنید یا از دکمه‌های نوبت رزرو شده استفاده کنید."
    await c.message.edit_text(text_msg, reply_markup=keyboard)
    await c.answer()


@router.callback_query(F.data == "menu:book")
async def start_booking_from_menu(c: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        user = await _ensure_registered(session, c.from_user.id)
    if not user:
        await c.message.edit_text(BOOKING_NEED_REGISTER)
        await state.clear()
        await c.answer()
        return
    await _show_months(c.message, state, edit=True)
    await c.answer()


@router.message(F.text == "رزرو نوبت")
async def start_booking_command(m: Message, state: FSMContext):
    async with SessionLocal() as session:
        user = await _ensure_registered(session, m.from_user.id)
    if not user:
        await m.answer(BOOKING_NEED_REGISTER)
        return
    await _show_months(m, state, edit=False)


@router.callback_query(BookingStates.choosing_month, F.data.startswith("book:month:"))
async def choose_month(c: CallbackQuery, state: FSMContext):
    month_key = c.data.split(":", 2)[2]
    data = await state.get_data()
    month_map = data.get(STATE_MONTHS_KEY, {})
    info = month_map.get(month_key)
    if not info:
        await c.answer("ماه انتخابی نامعتبر است.", show_alert=True)
        return
    days_keyboard = booking_days_keyboard(
        [(day["label"], day["jdate"]) for day in info["days"]],
        month_key,
    )
    await state.update_data({STATE_SELECTED_MONTH: month_key})
    await state.set_state(BookingStates.choosing_day)
    await c.message.edit_text(BOOKING_DAY_PROMPT, reply_markup=days_keyboard)
    await c.answer()


@router.callback_query(BookingStates.choosing_day, F.data.startswith("book:day:"))
async def choose_day(c: CallbackQuery, state: FSMContext):
    jdate = c.data.split(":", 2)[2]
    data = await state.get_data()
    month_key = data.get(STATE_SELECTED_MONTH)
    month_map = data.get(STATE_MONTHS_KEY, {})
    valid = False
    if month_key and month_key in month_map:
        valid = any(day["jdate"] == jdate for day in month_map[month_key]["days"])
    if not valid:
        await c.answer("تاریخ انتخابی معتبر نیست.", show_alert=True)
        return
    async with SessionLocal() as session:
        availability = await get_day_availability(session, jdate)
    if not availability:
        await c.message.edit_text(BOOKING_DAY_EMPTY)
        await state.set_state(BookingStates.choosing_month)
        await c.answer()
        return
    keyboard = booking_slots_keyboard(availability, jdate)
    await state.update_data({STATE_SELECTED_DAY: jdate})
    await state.set_state(BookingStates.choosing_slot)
    await c.message.edit_text(BOOKING_SLOT_PROMPT, reply_markup=keyboard)
    await c.answer()


@router.callback_query(F.data == "book:back:month")
async def back_to_month(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    month_map = data.get(STATE_MONTHS_KEY, {})
    if not month_map:
        await c.message.edit_text(BOOKING_NO_AVAILABILITY)
        await state.clear()
        await c.answer()
        return
    keyboard = booking_months_keyboard(
        [(info["label"], key) for key, info in month_map.items()]
    )
    await state.set_state(BookingStates.choosing_month)
    await c.message.edit_text(BOOKING_START_PROMPT, reply_markup=keyboard)
    await c.answer()


@router.callback_query(F.data.startswith("book:back:day:"))
async def back_to_days(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    month_key = data.get(STATE_SELECTED_MONTH)
    month_map = data.get(STATE_MONTHS_KEY, {})
    if not month_key or month_key not in month_map:
        await c.answer()
        return
    keyboard = booking_days_keyboard(
        [(day["label"], day["jdate"]) for day in month_map[month_key]["days"]],
        month_key,
    )
    await state.set_state(BookingStates.choosing_day)
    await c.message.edit_text(BOOKING_DAY_PROMPT, reply_markup=keyboard)
    await c.answer()


@router.callback_query(BookingStates.choosing_slot, F.data.startswith("book:slot:"))
async def choose_slot(c: CallbackQuery, state: FSMContext):
    slot_id = int(c.data.split(":", 2)[2])
    data = await state.get_data()
    jdate = data.get(STATE_SELECTED_DAY)
    if not jdate:
        await c.answer("تاریخ مشخص نیست.", show_alert=True)
        return
    async with SessionLocal() as session:
        user = await _ensure_registered(session, c.from_user.id)
        if not user:
            await c.answer(BOOKING_NEED_REGISTER, show_alert=True)
            await state.clear()
            return
        # Confirm slot exists and has capacity
        slot = await get_slot_by_id(session, slot_id)
        if not slot or not slot.is_active or not slot.day.is_active:
            await c.answer("این بازه دیگر فعال نیست.", show_alert=True)
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
        appointment = Appointment(
            user_id=user.id,
            slot_id=slot_id,
            jdate=jdate,
            time_slot=slot_info.start_time,
            payment_status=PaymentStatus.unpaid,
        )
        session.add(appointment)
        await session.commit()
        await session.refresh(appointment)
        await state.update_data({STATE_APPOINTMENT_ID: appointment.id})
    await state.set_state(BookingStates.waiting_receipt)
    await c.message.edit_text(BOOKING_CONFIRMATION)
    await c.answer()


@router.message(BookingStates.waiting_receipt, F.photo)
async def receive_receipt(m: Message, state: FSMContext):
    data = await state.get_data()
    appointment_id = data.get(STATE_APPOINTMENT_ID)
    if not appointment_id:
        await m.answer("نوبتی برای ثبت رسید یافت نشد.")
        await state.clear()
        return
    file_id = m.photo[-1].file_id
    async with SessionLocal() as session:
        await link_receipt(session, appointment_id, file_id)
    await state.clear()
    await m.answer("رسید دریافت شد ✅\nپس از بررسی ادمین نتیجه اعلام می‌شود.")


@router.message(F.caption.regexp(r"^\s*#?(\d+)\s*$"), F.photo.as_("ph"))
async def receipt_with_caption(m: Message, ph, state: FSMContext, regexp):
    appt_id = int(regexp.group(1))
    file_id = ph[-1].file_id
    async with SessionLocal() as session:
        ok = await link_receipt(session, appt_id, file_id)
    if ok:
        await m.answer("رسید به نوبت پیوند خورد ✅")
    else:
        await m.answer("شناسه نوبت نامعتبر است.")


@router.message()
async def maybe_consult(m: Message):
    # Only run AI consult fallback when the integration is configured
    if not settings.openai_api_key:
        return
    if m.text and len(m.text) > 6:
        answer = await consult_medical(m.text)
        await m.answer(answer)
