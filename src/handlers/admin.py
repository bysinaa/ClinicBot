from __future__ import annotations

import html
import re
from typing import Optional, Sequence, Union
from datetime import date, datetime, time, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from persiantools.jdatetime import JalaliDate
from sqlalchemy import select

from src.config import settings
from src.database import SessionLocal
from src.keyboards import (
    admin_menu_inline,
    admin_schedule_add_day_picker_keyboard,
    admin_schedule_days_keyboard,
    admin_schedule_months_keyboard,
    admin_schedule_slot_capacity_keyboard,
    admin_schedule_slot_end_keyboard,
    admin_schedule_slot_start_keyboard,
    admin_schedule_slots_keyboard,
    admin_contact_keyboard,
)
from src.models import (
    Appointment,
    AppointmentStatus,
    OnlineConsultRequestStatus,
    PaymentStatus,
    Role,
    ScheduleDay,
    User,
)
from src.services.booking import (
    SlotSummary,
    count_slot_bookings,
    create_schedule_day,
    create_schedule_slot,
    delete_schedule_day,
    delete_schedule_slot,
    get_day_slot_summaries,
    get_slot_by_id,
    list_schedule_days,
    set_schedule_day_active,
    set_schedule_slot_active,
)
from src.services.clinic import clear_location, get_profile_cached, update_profile
from src.services.online_consult import (
    get_request,
    list_requests,
    update_status as update_online_status,
)
from src.services.pdf_reports import generate_appointment_pdf
from src.states import AdminContactStates, AdminScheduleStates, AdminStates
from src.utils.jalali import format_jalali_day, gregorian_to_jalali, jalali_month_name

ADMIN_MENU_TEXT = "Admin menu. Choose an option:"
ADMIN_PENDING_EMPTY = "No pending appointments."
SCHEDULE_EMPTY_TEXT = "No schedule has been configured yet. Use \"Add day\" to begin."
SCHEDULE_MONTH_PROMPT = "Select a month to manage:"
SCHEDULE_DAY_PROMPT = "Select a day:"
SCHEDULE_DATE_PROMPT = "تاریخ مورد نظر را از میان دکمه‌ها انتخاب کنید."
SCHEDULE_DATE_INVALID = "The date is invalid or outside the next 6 months."
SCHEDULE_DAY_ADDED = "Day {label} added successfully."
SCHEDULE_DAY_TOGGLED = "Day status changed to {status}."
SCHEDULE_DAY_DELETED = "Day removed."
SCHEDULE_DAY_DELETE_BLOCKED = "Cannot remove this day while active bookings exist."
SLOT_START_PROMPT = "زمان شروع بازه را انتخاب کنید."
SLOT_END_PROMPT = "زمان پایان بازه را انتخاب کنید."
SLOT_CAPACITY_PROMPT = "ظرفیت بازه را انتخاب کنید."
SLOT_TIME_INVALID = "Invalid time."
SLOT_RANGE_INVALID = "End time must be after start time."
SLOT_CAPACITY_INVALID = "Capacity must be positive."
SLOT_CREATED = "Slot created successfully."
SLOT_NO_END_AVAILABLE = "بعد از این زمان شروع، گزینه‌ای برای پایان وجود ندارد."
SLOT_DRAFT_INCOMPLETE = "اطلاعات بازه ناقص است. لطفاً دوباره تلاش کنید."
SLOT_TOGGLED = "Slot status changed to {status}."
SLOT_DELETE_SUCCESS = "Slot removed."
SLOT_DELETE_BLOCKED = "Slot has bookings and cannot be removed; deactivate instead."
CONTACT_MENU_TITLE = "اطلاعات فعلی مطب"
CONTACT_PHONE_PROMPT = "شماره تماس مطب را وارد کنید (۱۱ رقم، مثلاً 02112345678 یا 09121234567)."
CONTACT_PHONE_LABEL_PROMPT = "متن دکمه تماس را وارد کنید."
CONTACT_PHONE_INVALID = "شماره تماس وارد شده معتبر نیست. لطفاً دوباره امتحان کنید."
CONTACT_PHONE_SAVED = "شماره تماس با موفقیت ذخیره شد."
CONTACT_PHONE_LABEL_SAVED = "عنوان دکمه تماس با موفقیت ذخیره شد."
CONTACT_ADDRESS_PROMPT = "متن آدرس مطب را وارد کنید."
CONTACT_ADDRESS_SAVED = "آدرس با موفقیت ذخیره شد."
CONTACT_LOCATION_PROMPT = "موقعیت مکانی مطب را ارسال کنید یا کلمه «لغو» را بفرستید."
CONTACT_LOCATION_SAVED = "موقعیت مکانی با موفقیت ذخیره شد."
CONTACT_LOCATION_CLEARED = "موقعیت مکانی حذف شد."
CONTACT_ACTION_CANCELLED = "عملیات لغو شد."
ONLINE_ADMIN_EMPTY = "No online consult requests found."
ONLINE_ADMIN_PROMPT = "Latest online consult requests (up to 20):"
ONLINE_ADMIN_ACTION_DONE = "Request status updated."
ONLINE_ADMIN_NEED_RECEIPT = "No receipt has been uploaded for this request yet."
ONLINE_ADMIN_APPROVED_NOTE = "Payment confirmed. The consultant will respond soon."
ONLINE_ADMIN_REJECTED_NOTE = "Payment was not approved. Please retry if needed."
STATE_MONTH_MAP = "schedule_months"
STATE_SELECTED_MONTH = "schedule_selected_month"
STATE_SELECTED_DAY_ID = "schedule_selected_day_id"
STATE_SELECTED_DAY_JDATE = "schedule_selected_day_jdate"
STATE_SLOT_DRAFT = "schedule_slot_draft"
CONTACT_FLOW_FLAG = "contact_flow_active"
STATE_DAY_PICK_FILTER = "schedule_day_picker_filter"
STATE_DAY_PICK_PAGE = "schedule_day_picker_page"
DAY_PICKER_PAGE_SIZE = 6
SLOT_CAPACITY_OPTIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 8, 10)
_TIME_CHOICES: tuple[str, ...] = tuple(
    [f"{hour:02d}:{minute:02d}" for hour in range(8, 21) for minute in (0, 30)]
    + ["21:00"]
)
SCHEDULE_DAY_PICKER_EMPTY = "تمام روزهای بازه انتخابی از قبل در برنامه ثبت شده‌اند."
CONTACT_CANCEL_TOKENS = {"لغو", "cancel", "/cancel"}

BOOKING_RANGE_DAYS = 180
router = Router(name="admin")




def _is_admin_user(telegram_id: int, current_user: Optional[User]) -> bool:
    if current_user and current_user.role == Role.admin:
        return True
    return telegram_id in settings.admin_ids


async def _show_admin_menu(message: Message, *, edit: bool, text: Optional[str] = None) -> None:
    markup = admin_menu_inline()
    content = text or ADMIN_MENU_TEXT
    if edit:
        try:
            await message.edit_text(content, reply_markup=markup)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=markup)
    else:
        await message.answer(content, reply_markup=markup)


def _extract_id_from_callback(data: str) -> int | None:
    try:
        return int(data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


async def _fetch_pending_rows(limit: int = 50) -> list[tuple[Appointment, User]]:
    async with SessionLocal() as session:
        query = (
            select(Appointment, User)
            .join(User, User.id == Appointment.user_id)
            .where(Appointment.status == AppointmentStatus.pending)
            .order_by(Appointment.created_at.desc())
        )
        if limit:
            query = query.limit(limit)
        result = await session.execute(query)
        return result.all()


def _pending_list_keyboard(rows: Sequence[tuple[Appointment, User]]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for appt, user in rows:
        label = f"#{appt.id} | {user.full_name or '-'} | {appt.jdate} {appt.time_slot or '-'}"
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"admin:pending:view:{appt.id}")]
        )
    buttons.append([InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="admin:pending:refresh")])
    buttons.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show_pending_list(
    target: MessageLike,
    *,
    edit: Optional[bool] = None,
) -> None:
    rows = await _fetch_pending_rows()
    message, default_edit = _resolve_message(target)
    do_edit = default_edit if edit is None else edit
    if not rows:
        content = ADMIN_PENDING_EMPTY
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]]
        )
    else:
        content = "نوبت‌های در انتظار تایید. برای مدیریت هر مورد یکی از دکمه‌ها را انتخاب کنید."
        keyboard = _pending_list_keyboard(rows)
    if do_edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _update_appointment_status(
    appt_id: int,
    *,
    status: AppointmentStatus,
    payment_status: PaymentStatus | None = None,
) -> Appointment | None:
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            return None
        appt.status = status
        if payment_status is not None and hasattr(appt, "payment_status"):
            appt.payment_status = payment_status
        await session.commit()
        await session.refresh(appt)
        return appt


async def _fetch_user_appointments_summary(session, user_id: int) -> list[dict[str, str]]:
    result = await session.execute(
        select(Appointment)
        .where(Appointment.user_id == user_id)
        .order_by(Appointment.created_at.desc())
    )
    appointments = result.scalars().all()
    return [
        {
            "jdate": item.jdate,
            "time_slot": item.time_slot or "-",
            "status": item.status.value,
        }
        for item in appointments
    ]


async def _show_pending_detail(
    target: MessageLike,
    appt_id: int,
    *,
    edit: Optional[bool] = None,
) -> None:
    message, default_edit = _resolve_message(target)
    do_edit = default_edit if edit is None else edit
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            content = "این نوبت پیدا نشد یا قبلاً تغییر کرده است."
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin:pending")]]
            )
            if do_edit:
                try:
                    await message.edit_text(content, reply_markup=keyboard)
                except TelegramBadRequest:
                    await message.answer(content, reply_markup=keyboard)
            else:
                await message.answer(content, reply_markup=keyboard)
            return
        user = await session.get(User, appt.user_id)
    status_map = {
        AppointmentStatus.pending: "در انتظار",
        AppointmentStatus.confirmed: "تایید شده",
        AppointmentStatus.canceled: "لغو شده",
    }
    payment_value = getattr(appt, "payment_status", None)
    payment_label = getattr(payment_value, "value", "-")
    lines = [
        f"نوبت #{appt.id}",
        f"وضعیت: {status_map.get(appt.status, appt.status.value)}",
        f"پرداخت: {payment_label}",
        f"تاریخ: {appt.jdate}",
        f"ساعت: {appt.time_slot or '-'}",
    ]
    if user:
        lines.append(f"بیمار: {user.full_name or '-'}")
        lines.append(f"شماره تماس: {user.phone or '-'}")
    if appt.notes:
        lines.append(f"یادداشت: {appt.notes}")
    content = "\n".join(lines)
    buttons: list[list[InlineKeyboardButton]] = []
    if appt.status == AppointmentStatus.pending:
        buttons.append([
            InlineKeyboardButton(text="✅ تایید نوبت", callback_data=f"admin:pending:confirm:{appt.id}"),
            InlineKeyboardButton(text="❌ لغو نوبت", callback_data=f"admin:pending:cancel:{appt.id}"),
        ])
    buttons.append([InlineKeyboardButton(text="📄 صدور PDF", callback_data=f"admin:pending:pdf:{appt.id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ بازگشت به فهرست", callback_data="admin:pending")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    if do_edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _send_pdf_hint(message: Message, *, edit: bool) -> None:
    text = "برای ساخت PDF از فهرست نوبت‌ها، روی دکمه «📄 صدور PDF» همان نوبت بزنید."
    await _show_admin_menu(message, edit=edit, text=text)


async def _refresh_schedule_month_map(state: FSMContext) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    async with SessionLocal() as session:
        today = date.today()
        end = today + timedelta(days=BOOKING_RANGE_DAYS)
        days = await list_schedule_days(session, today, end)
        month_map: Dict[str, Dict[str, object]] = {}
        for day in days:
            jalali = gregorian_to_jalali(day.date)
            month_key = f"{jalali.year}-{jalali.month:02d}"
            month_label = f"{jalali_month_name(jalali.month)} {jalali.year}"
            summaries = await get_day_slot_summaries(session, day.id)
            slot_total = len(summaries)
            active_slots = sum(1 for s in summaries if s.is_active)
            day_label = f"{format_jalali_day(jalali)} | {'فعال' if day.is_active else 'غیرفعال'} | بازه‌ها: {active_slots}/{slot_total}"
            month_entry = month_map.setdefault(
                month_key,
                {
                    "label": month_label,
                    "days": [],
                },
            )
            month_entry["days"].append(
                {
                    "id": day.id,
                    "jdate": jalali.strftime("%Y-%m-%d"),
                    "label": day_label,
                    "active": day.is_active,
                }
            )
        # sort days inside each month
        for entry in month_map.values():
            entry["days"].sort(key=lambda item: item["jdate"])  # type: ignore[index]
            total_days = len(entry["days"])  # type: ignore[index]
            active_days = sum(1 for item in entry["days"] if item["active"])  # type: ignore[index]
            entry["label"] = f"{entry['label']} ({active_days}/{total_days} روز فعال)"  # type: ignore[index]
        ordered = dict(sorted(month_map.items(), key=lambda item: item[0]))
    await state.update_data({STATE_MONTH_MAP: ordered})
    return ordered  # type: ignore[return-value]


def _encode_time_token(value: str) -> str:
    return value.replace(":", "-")


def _decode_time_token(value: str) -> str:
    return value.replace("-", ":")


def _start_time_choices() -> list[str]:
    return list(_TIME_CHOICES[:-1])


def _end_time_choices(start_value: str) -> list[str]:
    try:
        idx = _TIME_CHOICES.index(start_value)
    except ValueError:
        return []
    return list(_TIME_CHOICES[idx + 1 :])


async def _build_day_picker_options(month_key: str | None) -> list[tuple[str, str]]:
    today = date.today()
    end = today + timedelta(days=BOOKING_RANGE_DAYS)
    async with SessionLocal() as session:
        scheduled = await list_schedule_days(session, today, end)
    scheduled_dates = {day.date for day in scheduled}
    options: list[tuple[str, str]] = []
    total_days = (end - today).days
    for offset in range(total_days + 1):
        current = today + timedelta(days=offset)
        if current in scheduled_dates:
            continue
        jalali = gregorian_to_jalali(current)
        jdate = jalali.strftime("%Y-%m-%d")
        if month_key and not jdate.startswith(month_key):
            continue
        options.append((format_jalali_day(jalali), jdate))
    return options


async def _show_day_picker(
    message: Message,
    state: FSMContext,
    *,
    month_key: str | None,
    page: int,
    edit: bool,
) -> None:
    options = await _build_day_picker_options(month_key)
    total_pages = (len(options) - 1) // DAY_PICKER_PAGE_SIZE + 1 if options else 0
    if total_pages:
        page = max(0, min(page, total_pages - 1))
        start = page * DAY_PICKER_PAGE_SIZE
        chunk = options[start : start + DAY_PICKER_PAGE_SIZE]
    else:
        page = 0
        chunk = []
    keyboard = admin_schedule_add_day_picker_keyboard(
        chunk,
        page=page,
        has_prev=page > 0,
        has_next=total_pages > 0 and page < total_pages - 1,
        month_key=month_key,
    )
    await state.set_state(AdminScheduleStates.awaiting_day_input)
    await state.update_data(
        {
            STATE_DAY_PICK_FILTER: month_key,
            STATE_DAY_PICK_PAGE: page,
        }
    )
    content = SCHEDULE_DATE_PROMPT if chunk else SCHEDULE_DAY_PICKER_EMPTY
    if edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _show_schedule_months(message: Message, state: FSMContext, *, edit: bool) -> None:
    month_map = await _refresh_schedule_month_map(state)
    month_rows = [(info["label"], key) for key, info in month_map.items()]
    keyboard = admin_schedule_months_keyboard(month_rows)
    await state.set_state(AdminScheduleStates.selecting_month)
    content = SCHEDULE_MONTH_PROMPT if month_rows else SCHEDULE_EMPTY_TEXT
    if edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _show_schedule_days(
    target: MessageLike,
    state: FSMContext,
    month_key: str,
    *,
    edit: Optional[bool] = None,
) -> None:
    message, default_edit = _resolve_message(target)
    do_edit = default_edit if edit is None else edit
    month_map = await _refresh_schedule_month_map(state)
    if not month_map:
        await _show_schedule_months(message, state, edit=do_edit)
        return
    if month_key not in month_map:
        await _show_schedule_months(message, state, edit=do_edit)
        return
    info = month_map[month_key]
    rows = [(day["label"], day["jdate"]) for day in info["days"]]
    keyboard = admin_schedule_days_keyboard(rows, month_key)
    await state.update_data({STATE_SELECTED_MONTH: month_key})
    await state.set_state(AdminScheduleStates.selecting_day)
    content_lines = [info["label"]]
    if rows:
        content_lines.append(SCHEDULE_DAY_PROMPT)
    else:
        content_lines.append(SCHEDULE_EMPTY_TEXT)
    content = "\n".join(content_lines)
    if do_edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _show_schedule_day_detail(
    target: MessageLike,
    state: FSMContext,
    day_id: int,
    jdate: str,
    *,
    edit: Optional[bool] = None,
) -> None:
    message, default_edit = _resolve_message(target)
    do_edit = default_edit if edit is None else edit
    async with SessionLocal() as session:
        day = await session.get(ScheduleDay, day_id)
        if not day:
            await state.update_data(
                {
                    STATE_SELECTED_DAY_ID: None,
                    STATE_SELECTED_DAY_JDATE: None,
                }
            )
            await _show_schedule_days(message, state, jdate[:7], edit=do_edit)
            return
        summaries = list(await get_day_slot_summaries(session, day_id))
    jalali = gregorian_to_jalali(day.date)
    status_text = "فعال" if day.is_active else "غیرفعال"
    active_slots = sum(1 for s in summaries if s.is_active)
    total_slots = len(summaries)
    lines = [
        f"{format_jalali_day(jalali)} ({jdate})",
        f"وضعیت روز: {status_text}",
        f"تعداد بازه‌های فعال: {active_slots}/{total_slots}",
    ]
    if day.notes:
        lines.append(f"یادداشت: {day.notes}")
    if not summaries:
        lines.append("هیچ بازه‌ای برای این روز ثبت نشده است.")
    content = "\n".join(lines)
    keyboard = admin_schedule_slots_keyboard(day_id, jdate, summaries, day.is_active)
    await state.update_data(
        {
            STATE_SELECTED_MONTH: jdate[:7],
            STATE_SELECTED_DAY_ID: day_id,
            STATE_SELECTED_DAY_JDATE: jdate,
        }
    )
    await state.set_state(AdminScheduleStates.selecting_day)
    if do_edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _show_contact_menu(
    target: MessageLike,
    state: FSMContext,
    *,
    edit: Optional[bool] = None,
) -> None:
    message, default_edit = _resolve_message(target)
    do_edit = default_edit if edit is None else edit
    summary, has_location = await _format_contact_summary()
    content = f"{CONTACT_MENU_TITLE}\n\n{summary}"
    keyboard = admin_contact_keyboard(has_location)
    if do_edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _format_contact_summary() -> tuple[str, bool]:
    async with SessionLocal() as session:
        profile = await get_profile_cached(session)
    phone = profile.phone_number or "تعریف نشده"
    phone_label = profile.phone_label or "تماس با مطب"
    address = profile.address_text or "ثبت نشده"
    has_location = profile.location_lat is not None and profile.location_lon is not None
    location = "ثبت شده" if has_location else "ثبت نشده"
    lines = [
        f"شماره تماس: {phone}",
        f"عنوان دکمه تماس: {phone_label}",
        f"آدرس: {address}",
        f"موقعیت مکانی: {location}",
    ]
    return "\n".join(lines), has_location


def _format_online_status(status: OnlineConsultRequestStatus) -> str:
    labels = {
        OnlineConsultRequestStatus.pending: "Waiting for receipt",
        OnlineConsultRequestStatus.awaiting_confirmation: "Awaiting approval",
        OnlineConsultRequestStatus.approved: "Approved",
        OnlineConsultRequestStatus.rejected: "Rejected",
        OnlineConsultRequestStatus.completed: "Completed",
    }
    return labels.get(status, status.value)


def _online_action_keyboard(request_id: int, status: OnlineConsultRequestStatus) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status == OnlineConsultRequestStatus.awaiting_confirmation:
        rows.append([
            InlineKeyboardButton(text="Approve", callback_data=f"admin:online:approve:{request_id}"),
            InlineKeyboardButton(text="Reject", callback_data=f"admin:online:reject:{request_id}"),
        ])
    elif status == OnlineConsultRequestStatus.approved:
        rows.append([
            InlineKeyboardButton(text="Mark as completed", callback_data=f"admin:online:complete:{request_id}"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin:online")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_request_summary(request, user) -> str:
    lines = [
        f"ID: #{request.id}",
        f"Status: {_format_online_status(request.status)}",
        f"User: {user.full_name or '-'}",
        f"Submitted: {request.created_at:%Y-%m-%d %H:%M}",
        "Question:",
        request.question,
    ]
    if request.admin_notes:
        lines.append("")
        lines.append("Admin notes:")
        lines.append(request.admin_notes)
    if request.answer:
        lines.append("")
        lines.append("Answer:")
        lines.append(request.answer)
    return "\n".join(lines)


async def _show_online_requests(message: Message, *, edit: bool) -> None:
    async with SessionLocal() as session:
        requests = await list_requests(session, limit=20)
    if not requests:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")]])
        if edit:
            await message.edit_text(ONLINE_ADMIN_EMPTY, reply_markup=keyboard)
        else:
            await message.answer(ONLINE_ADMIN_EMPTY, reply_markup=keyboard)
        return
    lines = [ONLINE_ADMIN_PROMPT]
    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for req in requests:
        status_label = _format_online_status(req.status)
        lines.append(f"#{req.id} | {req.created_at:%Y-%m-%d} | {status_label}")
        keyboard_rows.append([
            InlineKeyboardButton(text=f"View request #{req.id}", callback_data=f"admin:online:view:{req.id}"),
        ])
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    content = "\n".join(lines)
    if edit:
        await message.edit_text(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


@router.callback_query(F.data == "admin:contact")
async def admin_contact_menu(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("You do not have access.", show_alert=True)
        return
    await state.clear()
    await _show_contact_menu(c, state)
    await c.answer()


@router.callback_query(F.data == "admin:contact:back")
async def admin_contact_back(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await _show_admin_menu(c.message, edit=True)
    await c.answer()


@router.callback_query(F.data == "admin:contact:phone")
async def admin_contact_phone_prompt(c: CallbackQuery, state: FSMContext):
    await state.update_data({CONTACT_FLOW_FLAG: True})
    await state.set_state(AdminContactStates.awaiting_phone_number)
    await c.message.answer(CONTACT_PHONE_PROMPT)
    await c.answer()


@router.callback_query(F.data == "admin:contact:phone_label")
async def admin_contact_phone_label_prompt(c: CallbackQuery, state: FSMContext):
    await state.update_data({CONTACT_FLOW_FLAG: False})
    await state.set_state(AdminContactStates.awaiting_phone_label)
    await c.message.answer(CONTACT_PHONE_LABEL_PROMPT)
    await c.answer()


@router.callback_query(F.data == "admin:contact:address")
async def admin_contact_address_prompt(c: CallbackQuery, state: FSMContext):
    await state.update_data({CONTACT_FLOW_FLAG: False})
    await state.set_state(AdminContactStates.awaiting_address)
    await c.message.answer(CONTACT_ADDRESS_PROMPT)
    await c.answer()


@router.callback_query(F.data == "admin:contact:location")
async def admin_contact_location_prompt(c: CallbackQuery, state: FSMContext):
    await state.update_data({CONTACT_FLOW_FLAG: False})
    await state.set_state(AdminContactStates.awaiting_location)
    await c.message.answer(CONTACT_LOCATION_PROMPT)
    await c.answer()


@router.callback_query(F.data == "admin:contact:location_clear")
async def admin_contact_location_clear(c: CallbackQuery, state: FSMContext):
    async with SessionLocal() as session:
        await clear_location(session)
    await state.clear()
    await _show_contact_menu(c, state, edit=True)
    await c.answer(CONTACT_LOCATION_CLEARED, show_alert=True)


@router.message(AdminContactStates.awaiting_phone_number)
async def admin_contact_set_phone(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    data = await state.get_data()
    flow = data.get(CONTACT_FLOW_FLAG, False)
    if _is_cancel_text(text):
        await state.clear()
        await m.answer(CONTACT_ACTION_CANCELLED)
        await _show_contact_menu(m, state, edit=False)
        return
    if not _is_valid_phone(text):
        await m.answer(CONTACT_PHONE_INVALID)
        await m.answer(CONTACT_PHONE_PROMPT)
        return
    normalized = _normalize_phone(text)
    async with SessionLocal() as session:
        await update_profile(session, phone_number=normalized)
    await state.clear()
    if flow:
        await m.answer(CONTACT_PHONE_SAVED)
        await state.set_state(AdminContactStates.awaiting_phone_label)
        await state.update_data({CONTACT_FLOW_FLAG: True})
        await m.answer(CONTACT_PHONE_LABEL_PROMPT)
    else:
        await m.answer(CONTACT_PHONE_SAVED)
        await _show_contact_menu(m, state, edit=False)


@router.message(AdminContactStates.awaiting_phone_label)
async def admin_contact_set_phone_label(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    data = await state.get_data()
    flow = data.get(CONTACT_FLOW_FLAG, False)
    if _is_cancel_text(text):
        await state.clear()
        await m.answer(CONTACT_ACTION_CANCELLED)
        await _show_contact_menu(m, state, edit=False)
        return
    if not text:
        await m.answer(CONTACT_PHONE_LABEL_PROMPT)
        return
    async with SessionLocal() as session:
        await update_profile(session, phone_label=text)
    await state.clear()
    if flow:
        await m.answer(CONTACT_PHONE_LABEL_SAVED)
        await state.set_state(AdminContactStates.awaiting_address)
        await state.update_data({CONTACT_FLOW_FLAG: True})
        await m.answer(CONTACT_ADDRESS_PROMPT)
    else:
        await m.answer(CONTACT_PHONE_LABEL_SAVED)
        await _show_contact_menu(m, state, edit=False)


@router.message(AdminContactStates.awaiting_address)
async def admin_contact_set_address(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    data = await state.get_data()
    flow = data.get(CONTACT_FLOW_FLAG, False)
    if _is_cancel_text(text):
        await state.clear()
        await m.answer(CONTACT_ACTION_CANCELLED)
        await _show_contact_menu(m, state, edit=False)
        return
    if not text:
        await m.answer(CONTACT_ADDRESS_PROMPT)
        return
    async with SessionLocal() as session:
        await update_profile(session, address_text=text)
    await state.clear()
    if flow:
        await m.answer(CONTACT_ADDRESS_SAVED)
        await state.set_state(AdminContactStates.awaiting_location)
        await state.update_data({CONTACT_FLOW_FLAG: True})
        await m.answer(CONTACT_LOCATION_PROMPT)
    else:
        await m.answer(CONTACT_ADDRESS_SAVED)
        await _show_contact_menu(m, state, edit=False)


@router.message(AdminContactStates.awaiting_location, F.location)
async def admin_contact_set_location(m: Message, state: FSMContext):
    loc = m.location
    async with SessionLocal() as session:
        await update_profile(session, location_lat=loc.latitude, location_lon=loc.longitude)
    await state.clear()
    await m.answer(CONTACT_LOCATION_SAVED)
    await _show_contact_menu(m, state, edit=False)


@router.message(AdminContactStates.awaiting_location)
async def admin_contact_location_wait(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    if _is_cancel_text(text):
        await state.clear()
        await m.answer(CONTACT_ACTION_CANCELLED)
        await _show_contact_menu(m, state, edit=False)
        return
    await state.clear()
    await m.answer("موقعیت ثبت نشد؛ می‌توانید بعداً از منوی تنظیمات آن را اضافه کنید.")
    await _show_contact_menu(m, state, edit=False)


async def _show_online_request_detail(message: Message, request_id: int, *, edit: bool) -> None:
    async with SessionLocal() as session:
        request = await get_request(session, request_id)
        if not request:
            await message.answer("Request not found.")
            return
        user = await session.get(User, request.user_id)
    content = _format_request_summary(request, user)
    keyboard = _online_action_keyboard(request.id, request.status)
    if edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)
    if request.receipt_file_id:
        await message.bot.send_photo(chat_id=message.chat.id, photo=request.receipt_file_id)


@router.callback_query(F.data == "admin:online")
async def admin_online_menu(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("You do not have access.", show_alert=True)
        return
    await _show_online_requests(c.message, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:online:view:"))
async def admin_online_view(c: CallbackQuery):
    request_id = int(c.data.split(":", 2)[2])
    await _show_online_request_detail(c.message, request_id, edit=True)
    await c.answer()


async def _notify_user(bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except Exception:
        pass


async def _handle_online_status_update(c: CallbackQuery, request_id: int, new_status: OnlineConsultRequestStatus) -> None:
    async with SessionLocal() as session:
        request = await get_request(session, request_id)
        if not request:
            await c.answer("Request not found.", show_alert=True)
            return
        if new_status in {OnlineConsultRequestStatus.approved, OnlineConsultRequestStatus.completed} and not request.receipt_file_id:
            await c.answer(ONLINE_ADMIN_NEED_RECEIPT, show_alert=True)
            return
        await update_online_status(session, request_id, new_status)
        user = await session.get(User, request.user_id)
    if new_status == OnlineConsultRequestStatus.approved:
        await _notify_user(c.message.bot, user.tg_id, ONLINE_ADMIN_APPROVED_NOTE)
    elif new_status == OnlineConsultRequestStatus.rejected:
        await _notify_user(c.message.bot, user.tg_id, ONLINE_ADMIN_REJECTED_NOTE)
    await c.answer(ONLINE_ADMIN_ACTION_DONE, show_alert=True)
    await _show_online_request_detail(c.message, request_id, edit=True)


@router.callback_query(F.data.startswith("admin:online:approve:"))
async def admin_online_approve(c: CallbackQuery):
    request_id = int(c.data.split(":", 3)[3])
    await _handle_online_status_update(c, request_id, OnlineConsultRequestStatus.approved)


@router.callback_query(F.data.startswith("admin:online:reject:"))
async def admin_online_reject(c: CallbackQuery):
    request_id = int(c.data.split(":", 3)[3])
    await _handle_online_status_update(c, request_id, OnlineConsultRequestStatus.rejected)


@router.callback_query(F.data.startswith("admin:online:complete:"))
async def admin_online_complete(c: CallbackQuery):
    request_id = int(c.data.split(":", 3)[3])
    await _handle_online_status_update(c, request_id, OnlineConsultRequestStatus.completed)


@router.callback_query(F.data == "admin:schedule")
async def admin_schedule_menu(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("اجازه دسترسی ندارید.", show_alert=True)
        return
    await state.clear()
    await _show_schedule_months(c.message, state, edit=True)
    await c.answer()


@router.callback_query(AdminScheduleStates.selecting_month, F.data.startswith("admin:schedule:month:"))
async def admin_schedule_choose_month(c: CallbackQuery, state: FSMContext):
    month_key = c.data.split(":", 2)[2]
    await _show_schedule_days(c, state, month_key)


@router.callback_query(F.data == "admin:schedule:back:months")
async def admin_schedule_back_months(c: CallbackQuery, state: FSMContext):
    await _show_schedule_months(c.message, state, edit=True)
    await c.answer()


@router.callback_query(AdminScheduleStates.selecting_day, F.data.startswith("admin:schedule:day:"))
async def admin_schedule_choose_day(c: CallbackQuery, state: FSMContext):
    jdate = c.data.split(":", 2)[2]
    data = await state.get_data()
    month_key = data.get(STATE_SELECTED_MONTH)
    month_map = data.get(STATE_MONTH_MAP, {})
    day_entry = None
    if month_key and month_key in month_map:
        for item in month_map[month_key]["days"]:
            if item["jdate"] == jdate:
                day_entry = item
                break
    if not day_entry:
        await c.answer("تاریخ انتخابی معتبر نیست.", show_alert=True)
        return
    await _show_schedule_day_detail(c.message, state, day_entry["id"], jdate, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:schedule:back:days:"))
async def admin_schedule_back_days(c: CallbackQuery, state: FSMContext):
    jdate = c.data.split(":", 3)[3]
    data = await state.get_data()
    month_key = data.get(STATE_SELECTED_MONTH)
    if not month_key:
        await admin_schedule_back_months(c, state)
        return
    await _show_schedule_days(c, state, month_key)


@router.callback_query(F.data == "admin:schedule:add_day")
@router.callback_query(F.data.startswith("admin:schedule:add_day:"))
async def admin_schedule_add_day_prompt(c: CallbackQuery, state: FSMContext):
    month_key: str | None = None
    if c.data != "admin:schedule:add_day":
        parts = c.data.split(":", 3)
        if len(parts) > 3:
            month_key = parts[3] or None
            if month_key == "-":
                month_key = None
    await _show_day_picker(c.message, state, month_key=month_key, page=0, edit=True)
    await c.answer()


@router.callback_query(AdminScheduleStates.awaiting_day_input, F.data.startswith("admin:schedule:add_day_page:"))
async def admin_schedule_add_day_page(c: CallbackQuery, state: FSMContext):
    parts = c.data.split(":", 4)
    try:
        page = int(parts[3])
    except (IndexError, ValueError):
        page = 0
    filter_token = parts[4] if len(parts) > 4 else "-"
    month_key = None if filter_token in {"-", ""} else filter_token
    await _show_day_picker(c.message, state, month_key=month_key, page=page, edit=True)
    await c.answer()


@router.callback_query(AdminScheduleStates.awaiting_day_input, F.data.startswith("admin:schedule:add_day_select:"))
async def admin_schedule_add_day_select(c: CallbackQuery, state: FSMContext):
    try:
        jdate = c.data.split(":", 3)[3]
    except IndexError:
        await c.answer(SCHEDULE_DATE_INVALID, show_alert=True)
        return
    try:
        year, month, day = map(int, jdate.split("-"))
        jalali = JalaliDate(year, month, day)
    except ValueError:
        await c.answer(SCHEDULE_DATE_INVALID, show_alert=True)
        return
    target_gregorian = jalali.to_gregorian()
    today = date.today()
    if not (today <= target_gregorian <= today + timedelta(days=BOOKING_RANGE_DAYS)):
        await c.answer(SCHEDULE_DATE_INVALID, show_alert=True)
        return
    async with SessionLocal() as session:
        await create_schedule_day(session, target_gregorian)
    await c.answer(SCHEDULE_DAY_ADDED.format(label=format_jalali_day(jalali)))
    month_key = jdate[:7]
    await _show_schedule_days(c, state, month_key)


@router.callback_query(AdminScheduleStates.awaiting_day_input, F.data == "admin:schedule:add_day_back")
async def admin_schedule_add_day_back(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    month_key = data.get(STATE_DAY_PICK_FILTER) or data.get(STATE_SELECTED_MONTH)
    if month_key:
        await _show_schedule_days(c, state, month_key)
    else:
        await _show_schedule_months(c.message, state, edit=True)
    await c.answer()


@router.message(AdminScheduleStates.awaiting_day_input)
async def admin_schedule_add_day_input(m: Message, state: FSMContext):
    await m.answer("لطفاً تاریخ را با استفاده از دکمه‌ها انتخاب کنید.")


@router.callback_query(F.data.startswith("admin:schedule:toggle_day:"))
async def admin_schedule_toggle_day(c: CallbackQuery, state: FSMContext):
    day_id = int(c.data.split(":", 2)[2])
    async with SessionLocal() as session:
        day = await session.get(ScheduleDay, day_id)
        if not day:
            await c.answer("روز یافت نشد.", show_alert=True)
            return
        new_status = not day.is_active
        await set_schedule_day_active(session, day_id, new_status)
    data = await state.get_data()
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    await c.answer(SCHEDULE_DAY_TOGGLED.format(status="فعال" if new_status else "غیرفعال"))
    if jdate:
        await _show_schedule_day_detail(c.message, state, day_id, jdate, edit=True)


@router.callback_query(F.data.startswith("admin:schedule:delete_day:"))
async def admin_schedule_delete_day(c: CallbackQuery, state: FSMContext):
    day_id = int(c.data.split(":", 2)[2])
    async with SessionLocal() as session:
        summaries = await get_day_slot_summaries(session, day_id)
        has_bookings = False
        for slot in summaries:
            if await count_slot_bookings(session, slot.slot_id) > 0:
                has_bookings = True
                break
        if has_bookings:
            await c.answer(SCHEDULE_DAY_DELETE_BLOCKED, show_alert=True)
            return
        success = await delete_schedule_day(session, day_id)
    if not success:
        await c.answer("حذف انجام نشد.", show_alert=True)
        return
    await c.answer(SCHEDULE_DAY_DELETED)
    await _show_schedule_months(c.message, state, edit=True)


@router.callback_query(F.data.startswith("admin:schedule:add_slot:"))
async def admin_schedule_add_slot_prompt(c: CallbackQuery, state: FSMContext):
    day_id = int(c.data.split(":", 2)[2])
    await state.update_data({STATE_SLOT_DRAFT: {"day_id": day_id}})
    await state.set_state(AdminScheduleStates.awaiting_slot_start)
    keyboard = admin_schedule_slot_start_keyboard(_start_time_choices())
    try:
        await c.message.edit_text(SLOT_START_PROMPT, reply_markup=keyboard)
    except TelegramBadRequest:
        await c.message.answer(SLOT_START_PROMPT, reply_markup=keyboard)
    await c.answer()


def _parse_time(value: str) -> Optional[time]:
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError:
        return None


@router.callback_query(AdminScheduleStates.awaiting_slot_start, F.data.startswith("admin:schedule:slot_start:"))
async def admin_schedule_slot_start(c: CallbackQuery, state: FSMContext):
    try:
        token = c.data.split(":", 3)[3]
    except IndexError:
        await c.answer(SLOT_TIME_INVALID, show_alert=True)
        return
    start_str = _decode_time_token(token)
    if not _parse_time(start_str):
        await c.answer(SLOT_TIME_INVALID, show_alert=True)
        return
    data = await state.get_data()
    draft = dict(data.get(STATE_SLOT_DRAFT, {}))
    draft["start"] = start_str
    await state.update_data({STATE_SLOT_DRAFT: draft})
    end_choices = _end_time_choices(start_str)
    if not end_choices:
        await c.answer(SLOT_NO_END_AVAILABLE, show_alert=True)
        return
    await state.set_state(AdminScheduleStates.awaiting_slot_end)
    keyboard = admin_schedule_slot_end_keyboard(end_choices)
    try:
        await c.message.edit_text(SLOT_END_PROMPT, reply_markup=keyboard)
    except TelegramBadRequest:
        await c.message.answer(SLOT_END_PROMPT, reply_markup=keyboard)
    await c.answer()


@router.callback_query(AdminScheduleStates.awaiting_slot_end, F.data.startswith("admin:schedule:slot_end:"))
async def admin_schedule_slot_end(c: CallbackQuery, state: FSMContext):
    try:
        token = c.data.split(":", 3)[3]
    except IndexError:
        await c.answer(SLOT_TIME_INVALID, show_alert=True)
        return
    end_str = _decode_time_token(token)
    end_time = _parse_time(end_str)
    if not end_time:
        await c.answer(SLOT_TIME_INVALID, show_alert=True)
        return
    data = await state.get_data()
    draft = dict(data.get(STATE_SLOT_DRAFT, {}))
    start_str = draft.get("start")
    if not start_str:
        keyboard = admin_schedule_slot_start_keyboard(_start_time_choices())
        await state.set_state(AdminScheduleStates.awaiting_slot_start)
        try:
            await c.message.edit_text(SLOT_START_PROMPT, reply_markup=keyboard)
        except TelegramBadRequest:
            await c.message.answer(SLOT_START_PROMPT, reply_markup=keyboard)
        await c.answer()
        return
    start_time = _parse_time(start_str)
    if not start_time or end_time <= start_time:
        await c.answer(SLOT_RANGE_INVALID, show_alert=True)
        return
    draft["end"] = end_str
    await state.update_data({STATE_SLOT_DRAFT: draft})
    await state.set_state(AdminScheduleStates.awaiting_slot_capacity)
    keyboard = admin_schedule_slot_capacity_keyboard(SLOT_CAPACITY_OPTIONS)
    try:
        await c.message.edit_text(SLOT_CAPACITY_PROMPT, reply_markup=keyboard)
    except TelegramBadRequest:
        await c.message.answer(SLOT_CAPACITY_PROMPT, reply_markup=keyboard)
    await c.answer()


@router.callback_query(AdminScheduleStates.awaiting_slot_capacity, F.data.startswith("admin:schedule:slot_capacity:"))
async def admin_schedule_slot_capacity(c: CallbackQuery, state: FSMContext):
    try:
        capacity = int(c.data.split(":", 3)[3])
    except (IndexError, ValueError):
        await c.answer(SLOT_CAPACITY_INVALID, show_alert=True)
        return
    if capacity <= 0:
        await c.answer(SLOT_CAPACITY_INVALID, show_alert=True)
        return
    data = await state.get_data()
    draft = data.get(STATE_SLOT_DRAFT, {})
    day_id = draft.get("day_id")
    start_str = draft.get("start")
    end_str = draft.get("end")
    if not all([day_id, start_str, end_str]):
        await c.answer(SLOT_DRAFT_INCOMPLETE, show_alert=True)
        return
    start_time = _parse_time(start_str)
    end_time = _parse_time(end_str)
    if not start_time or not end_time:
        await c.answer(SLOT_TIME_INVALID, show_alert=True)
        return
    async with SessionLocal() as session:
        await create_schedule_slot(session, int(day_id), start_time, end_time, capacity)
    await state.update_data({STATE_SLOT_DRAFT: {}})
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    await c.answer(SLOT_CREATED)
    if jdate and day_id:
        await _show_schedule_day_detail(c.message, state, int(day_id), jdate, edit=True)
    else:
        await _show_schedule_months(c.message, state, edit=True)


@router.callback_query(F.data == "admin:schedule:slot_back:detail")
async def admin_schedule_slot_back_detail(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    day_id = data.get(STATE_SELECTED_DAY_ID)
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    await state.update_data({STATE_SLOT_DRAFT: {}})
    if day_id and jdate:
        await _show_schedule_day_detail(c.message, state, int(day_id), jdate, edit=True)
    else:
        await _show_schedule_months(c.message, state, edit=True)
    await c.answer()


@router.callback_query(AdminScheduleStates.awaiting_slot_end, F.data == "admin:schedule:slot_back:start")
async def admin_schedule_slot_back_start(c: CallbackQuery, state: FSMContext):
    await state.set_state(AdminScheduleStates.awaiting_slot_start)
    keyboard = admin_schedule_slot_start_keyboard(_start_time_choices())
    try:
        await c.message.edit_text(SLOT_START_PROMPT, reply_markup=keyboard)
    except TelegramBadRequest:
        await c.message.answer(SLOT_START_PROMPT, reply_markup=keyboard)
    await c.answer()


@router.callback_query(AdminScheduleStates.awaiting_slot_capacity, F.data == "admin:schedule:slot_back:end")
async def admin_schedule_slot_back_end(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    draft = data.get(STATE_SLOT_DRAFT, {})
    start_str = draft.get("start")
    if not start_str:
        await admin_schedule_slot_back_start(c, state)
        return
    end_choices = _end_time_choices(start_str)
    if not end_choices:
        await admin_schedule_slot_back_start(c, state)
        return
    await state.set_state(AdminScheduleStates.awaiting_slot_end)
    keyboard = admin_schedule_slot_end_keyboard(end_choices)
    try:
        await c.message.edit_text(SLOT_END_PROMPT, reply_markup=keyboard)
    except TelegramBadRequest:
        await c.message.answer(SLOT_END_PROMPT, reply_markup=keyboard)
    await c.answer()


@router.message(AdminScheduleStates.awaiting_slot_start)
@router.message(AdminScheduleStates.awaiting_slot_end)
@router.message(AdminScheduleStates.awaiting_slot_capacity)
async def admin_schedule_slot_text_input(m: Message, state: FSMContext):
    await m.answer("لطفاً از دکمه‌ها برای انتخاب گزینه استفاده کنید.")




@router.callback_query(F.data.startswith("admin:schedule:slot_toggle:"))
async def admin_schedule_slot_toggle(c: CallbackQuery, state: FSMContext):
    slot_id = int(c.data.split(":", 2)[2])
    async with SessionLocal() as session:
        slot = await get_slot_by_id(session, slot_id)
        if not slot:
            await c.answer("بازه یافت نشد.", show_alert=True)
            return
        new_status = not slot.is_active
        await set_schedule_slot_active(session, slot_id, new_status)
    data = await state.get_data()
    day_id = data.get(STATE_SELECTED_DAY_ID)
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    await c.answer(SLOT_TOGGLED.format(status="فعال" if new_status else "غیرفعال"))
    if day_id and jdate:
        await _show_schedule_day_detail(c.message, state, day_id, jdate, edit=True)


@router.callback_query(F.data.startswith("admin:schedule:slot_delete:"))
async def admin_schedule_slot_delete(c: CallbackQuery, state: FSMContext):
    slot_id = int(c.data.split(":", 2)[2])
    async with SessionLocal() as session:
        booked = await count_slot_bookings(session, slot_id)
        if booked > 0:
            await c.answer(SLOT_DELETE_BLOCKED, show_alert=True)
            return
        success = await delete_schedule_slot(session, slot_id)
    if not success:
        await c.answer("حذف بازه انجام نشد.", show_alert=True)
        return
    await c.answer(SLOT_DELETE_SUCCESS)
    data = await state.get_data()
    day_id = data.get(STATE_SELECTED_DAY_ID)
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    if day_id and jdate:
        await _show_schedule_day_detail(c.message, state, day_id, jdate, edit=True)


@router.callback_query(F.data.startswith("admin:schedule:slot_info:"))
async def admin_schedule_slot_info(c: CallbackQuery):
    slot_id = c.data.split(":", 2)[2]
    await c.answer(f"شناسه بازه: {slot_id}")


@router.callback_query(F.data == "admin:pending")
async def pending_from_menu(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("اجازه دسترسی ندارید.", show_alert=True)
        return
    await state.clear()
    await _show_pending_list(c, edit=True)
    await c.answer()


@router.callback_query(F.data == "admin:pending:refresh")
async def pending_refresh(c: CallbackQuery):
    await _show_pending_list(c, edit=True)
    await c.answer()


@router.message(F.text == "نوبت‌های در انتظار")
async def pending_list(m: Message):
    await _show_pending_list(m, edit=False)


@router.callback_query(F.data.startswith("admin:pending:view:"))
async def pending_view(c: CallbackQuery):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("شناسه نوبت نامعتبر است.", show_alert=True)
        return
    await _show_pending_detail(c, appt_id, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:pending:confirm:"))
async def pending_confirm(c: CallbackQuery):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("شناسه نوبت نامعتبر است.", show_alert=True)
        return
    appt = await _update_appointment_status(
        appt_id,
        status=AppointmentStatus.confirmed,
        payment_status=PaymentStatus.settled,
    )
    if not appt:
        await c.answer("نوبت پیدا نشد.", show_alert=True)
        await _show_pending_list(c, edit=True)
        return
    await c.answer("نوبت تایید شد ✅", show_alert=True)
    await _show_pending_detail(c, appt_id, edit=True)


@router.callback_query(F.data.startswith("admin:pending:cancel:"))
async def pending_cancel(c: CallbackQuery):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("شناسه نوبت نامعتبر است.", show_alert=True)
        return
    appt = await _update_appointment_status(
        appt_id,
        status=AppointmentStatus.canceled,
        payment_status=PaymentStatus.rejected,
    )
    if not appt:
        await c.answer("نوبت پیدا نشد.", show_alert=True)
        await _show_pending_list(c, edit=True)
        return
    await c.answer("نوبت لغو شد.", show_alert=True)
    await _show_pending_detail(c, appt_id, edit=True)


@router.callback_query(F.data.startswith("admin:pending:pdf:"))
async def pending_pdf(c: CallbackQuery):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("شناسه نوبت نامعتبر است.", show_alert=True)
        return
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            await c.answer("نوبت پیدا نشد.", show_alert=True)
            return
        user = await session.get(User, appt.user_id)
        appointments = await _fetch_user_appointments_summary(session, user.id)
    path = generate_appointment_pdf(
        "./reports",
        appt.id,
        user.full_name or "-",
        appt.jdate,
        appt.time_slot,
        appt.status.value,
        appointments=appointments,
    )
    await c.message.answer_document(
        FSInputFile(path),
        caption=f"گزارش PDF نوبت #{appt_id}",
    )
    await c.answer("فایل PDF ارسال شد.")


@router.callback_query(F.data == "admin:pdf")
async def pdf_hint_from_menu(c: CallbackQuery, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("اجازه دسترسی ندارید.", show_alert=True)
        return
    await _send_pdf_hint(c.message, edit=True)
    await c.answer()


@router.message(F.text == "گزارش PDF")
async def admin_pdf(m: Message):
    await _send_pdf_hint(m, edit=False)


@router.message(F.text.regexp(r"^/confirm_(\d+)$"))
async def admin_confirm(m: Message, regexp):
    appt_id = int(regexp.group(1))
    appt = await _update_appointment_status(
        appt_id,
        status=AppointmentStatus.confirmed,
        payment_status=PaymentStatus.settled,
    )
    if not appt:
        await m.answer("شناسه نوبت نامعتبر است.")
        return
    await m.answer(f"نوبت #{appt_id} تأیید شد ✅")


@router.message(F.text.regexp(r"^/cancel_(\d+)$"))
async def admin_cancel(m: Message, regexp):
    appt_id = int(regexp.group(1))
    appt = await _update_appointment_status(
        appt_id,
        status=AppointmentStatus.canceled,
        payment_status=PaymentStatus.rejected,
    )
    if not appt:
        await m.answer("شناسه نوبت نامعتبر است.")
        return
    await m.answer(f"نوبت #{appt_id} لغو شد ❌")


@router.message(F.text.regexp(r"^/pdf_(\d+)$"))
async def pdf_report(m: Message, regexp):
    appt_id = int(regexp.group(1))
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            await m.answer("شناسه نوبت نامعتبر است.")
            return
        user = await session.get(User, appt.user_id)
        appointments = await _fetch_user_appointments_summary(session, user.id)
    path = generate_appointment_pdf(
        "./reports",
        appt.id,
        user.full_name or "-",
        appt.jdate,
        appt.time_slot,
        appt.status.value,
        appointments=appointments,
    )
    await m.answer_document(FSInputFile(path), caption=f"گزارش نوبت #{appt_id}")
MessageLike = Union[Message, CallbackQuery]


def _resolve_message(target: MessageLike) -> tuple[Message, bool]:
    if isinstance(target, CallbackQuery):
        return target.message, True
    return target, False


def _is_cancel_text(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in CONTACT_CANCEL_TOKENS


PERSIAN_DIGIT_MAP = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')


def _normalize_phone(value: str) -> str:
    translated = value.translate(PERSIAN_DIGIT_MAP)
    digits = re.sub(r"\D", "", translated)
    return digits


def _is_valid_phone(value: str) -> bool:
    digits = _normalize_phone(value)
    return len(digits) == 11 and digits.startswith("0")
