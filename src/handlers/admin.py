# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence, Tuple, Union

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from persiantools.jdatetime import JalaliDate
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

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
    admin_report_days_keyboard,
    admin_report_months_keyboard,
    ADMIN_PENDING_TEXT,
    ADMIN_PDF_TEXT,
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
    SlotCreationError,
    SlotOverlapError,
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
    update_schedule_slot,
)
from src.services.clinic import get_profile_cached
from src.services.online_consult import (
    get_request,
    list_requests,
    update_status as update_online_status,
)
from src.services.pdf_reports import generate_appointment_pdf, generate_day_summary_pdf
from src.states import AdminPdfStates, AdminScheduleStates, AdminStates
from src.utils.jalali import format_jalali_day, gregorian_to_jalali, jalali_month_name

ADMIN_MENU_TEXT = "منوی مدیریت. لطفاً یک گزینه را انتخاب کنید:"
ADMIN_PENDING_EMPTY = "نوبتی در انتظار بررسی وجود ندارد."
SCHEDULE_EMPTY_TEXT = "هیچ برنامه‌ای ثبت نشده است. برای شروع «افزودن روز» را انتخاب کنید."
SCHEDULE_MONTH_PROMPT = "ماه مورد نظر برای مدیریت را انتخاب کنید:"
SCHEDULE_DAY_PROMPT = "روز مورد نظر را انتخاب کنید:"
SCHEDULE_DATE_PROMPT = "تاریخ مورد نظر را از میان دکمه‌ها انتخاب کنید."
SCHEDULE_DATE_INVALID = "تاریخ نامعتبر است یا خارج از بازه شش‌ماههٔ پیشِ‌رو قرار دارد."
SCHEDULE_DAY_ADDED = "روز {label} با موفقیت افزوده شد."
SCHEDULE_DAY_TOGGLED = "وضعیت روز به {status} تغییر کرد."
SCHEDULE_DAY_DELETED = "روز حذف شد."
SCHEDULE_DAY_DELETE_BLOCKED = "تا زمانی که برای این روز نوبت فعال وجود دارد نمی‌توان آن را حذف کرد."
SLOT_START_PROMPT = "زمان شروع بازه را انتخاب کنید."
SLOT_END_PROMPT = "زمان پایان بازه را انتخاب کنید."
SLOT_CAPACITY_PROMPT = "ظرفیت بازه را انتخاب کنید."
SLOT_TIME_INVALID = "زمان وارد‌شده معتبر نیست."
SLOT_RANGE_INVALID = "زمان پایان باید بعد از زمان شروع باشد."
SLOT_CAPACITY_INVALID = "ظرفیت باید بزرگ‌تر از صفر باشد."
SLOT_CREATED = "بازهٔ زمانی با موفقیت ایجاد شد."
SLOT_UPDATED = "بازهٔ زمانی با موفقیت ویرایش شد."
SLOT_OVERLAP_EXISTS = "این بازه با بازهٔ {start} تا {end} تداخل دارد."
SLOT_NO_END_AVAILABLE = "بعد از این زمان شروع، گزینه‌ای برای پایان وجود ندارد."
SLOT_DRAFT_INCOMPLETE = "اطلاعات بازه ناقص است. لطفاً دوباره تلاش کنید."
SLOT_TOGGLED = "وضعیت بازه به {status} تغییر کرد."
SLOT_DELETE_SUCCESS = "بازه حذف شد."
SLOT_DELETE_BLOCKED = "برای این بازه نوبت ثبت شده است؛ به جای حذف، آن را غیرفعال کنید."
ONLINE_ADMIN_EMPTY = "درخواستی برای مشاورهٔ آنلاین پیدا نشد."
ONLINE_ADMIN_PROMPT = "آخرین درخواست‌های مشاورهٔ آنلاین (حداکثر ۲۰ مورد):"
ONLINE_ADMIN_ACTION_DONE = "وضعیت درخواست به‌روزرسانی شد."
ONLINE_ADMIN_NEED_RECEIPT = "برای این درخواست هنوز رسیدی بارگذاری نشده است."
ONLINE_ADMIN_APPROVED_NOTE = "پرداخت تأیید شد. به زودی مشاور پاسخ می‌دهد."
ONLINE_ADMIN_REJECTED_NOTE = "پرداخت تأیید نشد. در صورت نیاز دوباره تلاش کنید."
STATE_MONTH_MAP = "schedule_months"
STATE_SELECTED_MONTH = "schedule_selected_month"
STATE_SELECTED_DAY_ID = "schedule_selected_day_id"
STATE_SELECTED_DAY_JDATE = "schedule_selected_day_jdate"
STATE_SLOT_DRAFT = "schedule_slot_draft"
STATE_DAY_PICK_FILTER = "schedule_day_picker_filter"
STATE_DAY_PICK_PAGE = "schedule_day_picker_page"
PDF_STATE_MONTH_MAP = "pdf_month_map"
PDF_STATE_SELECTED_MONTH = "pdf_selected_month"
DAY_PICKER_PAGE_SIZE = 6
SLOT_CAPACITY_OPTIONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 8, 10)
_TIME_CHOICES: tuple[str, ...] = tuple(
    [f"{hour:02d}:{minute:02d}" for hour in range(8, 21) for minute in (0, 30)]
    + ["21:00"]
)
SCHEDULE_DAY_PICKER_EMPTY = "تمام روزهای بازه انتخابی از قبل در برنامه ثبت شده‌اند."

BOOKING_RANGE_DAYS = 180
PENDING_PAGE_SIZE = 5
STATE_PENDING_ENTRIES = "pending_entries"
STATE_PENDING_CONTEXT = "pending_context"
STATE_PENDING_PAGE = "pending_page"

PAYMENT_STATUS_LABELS = {
    PaymentStatus.unpaid: "در انتظار پرداخت",
    PaymentStatus.awaiting_confirmation: "در انتظار بررسی",
    PaymentStatus.settled: "پرداخت شده",
    PaymentStatus.rejected: "پرداخت رد شده",
}

REFERENCE_CODE_PREFIX = "CB"


def _normalize_reference_jdate(jdate: str | None) -> str:
    if jdate:
        return jdate
    today = JalaliDate.today()
    return f"{today.year:04}-{today.month:02}-{today.day:02}"


async def _build_reference_code(session, appt: Appointment) -> str:
    target_jdate = _normalize_reference_jdate(appt.jdate)
    stmt = (
        select(func.count(Appointment.id))
        .where(
            Appointment.jdate == target_jdate,
            Appointment.reference_code.is_not(None),
        )
    )
    existing = await session.execute(stmt)
    serial = int(existing.scalar_one() or 0)
    date_token = target_jdate.replace("-", "")
    return f"{REFERENCE_CODE_PREFIX}-{date_token}-{serial:03d}"


async def _ensure_reference_code(session, appt: Appointment) -> None:
    if appt.reference_code:
        return
    appt.reference_code = await _build_reference_code(session, appt)


def _reference_notice(appt: Appointment | None) -> str:
    if appt and appt.reference_code:
        return f"\nکد مرجع: {appt.reference_code}"
    return ""

PDF_MONTH_PROMPT = "ماه مورد نظر برای گزارش PDF را انتخاب کنید."
PDF_DAY_PROMPT = "روز مورد نظر برای تهیه گزارش را انتخاب کنید."
PDF_EMPTY_TEXT = "گزارشی برای این بازه در دسترس نیست."


logger = logging.getLogger(__name__)


def _broadcast_debug(message: str) -> None:
    try:
        with open("broadcast_debug.log", "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat()} {message}\n")
    except Exception as exc:
        logging.getLogger(__name__).warning("[broadcast] failed to write debug log: %s", exc)


router = Router(name="admin")


async def _fetch_pending_entries() -> tuple[str, list[dict[str, object]]]:
    async with SessionLocal() as session:
        today_jdate = JalaliDate.today().strftime("%Y-%m-%d")
        base_query = (
            select(Appointment)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.slot),
            )
            .where(Appointment.receipt_file_id.is_not(None))
            .order_by(Appointment.created_at.desc())
        )
        today_result = await session.execute(
            base_query.where(Appointment.jdate == today_jdate).limit(40)
        )
        appointments = today_result.scalars().all()
        context_label = "امروز"
        if not appointments:
            fallback_result = await session.execute(base_query.limit(40))
            appointments = fallback_result.scalars().all()
            context_label = "اخیر"
    entries: list[dict[str, object]] = []
    for appt in appointments:
        user_name = appt.user.full_name if appt.user and appt.user.full_name else "-"
        entries.append(
            {
                "id": appt.id,
                "jdate": appt.jdate,
                "time_label": _format_appointment_time(appt),
                "patient": user_name,
                "payment": _payment_status_label(appt.payment_status),
            }
        )
    return context_label, entries


async def _show_pending_list(
    target: MessageLike,
    state: FSMContext,
    *,
    edit: bool,
    page: int | None = None,
    force_refresh: bool = False,
) -> None:
    message, default_edit = _resolve_message(target)
    data = await state.get_data()
    entries: list[dict[str, object]] = data.get(STATE_PENDING_ENTRIES) or []
    context_label: str = data.get(STATE_PENDING_CONTEXT) or ""
    if force_refresh or not entries:
        context_label, entries = await _fetch_pending_entries()
        await state.update_data(
            {
                STATE_PENDING_ENTRIES: entries,
                STATE_PENDING_CONTEXT: context_label,
            }
        )
    total = len(entries)
    total_pages = max(1, (total + PENDING_PAGE_SIZE - 1) // PENDING_PAGE_SIZE)
    if page is None:
        page = int(data.get(STATE_PENDING_PAGE, 0) or 0)
    page = max(0, min(page, total_pages - 1))
    await state.update_data({STATE_PENDING_PAGE: page})
    start = page * PENDING_PAGE_SIZE
    chunk = entries[start : start + PENDING_PAGE_SIZE]

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    lines: list[str] = []
    if not chunk:
        content = ADMIN_PENDING_EMPTY
    else:
        lines.append(f"رسیدهای {context_label} (صفحه {page + 1} از {total_pages})")
        lines.append("")
        for entry in chunk:
            lines.append(
                f"#{entry['id']} | {entry['jdate']} | {entry['time_label']} | {entry['patient']} | پرداخت: {entry['payment']}"
            )
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        text=f"مشاهده نوبت #{entry['id']}",
                        callback_data=f"admin:pending:view:{entry['id']}",
                    )
                ]
            )
        content = "\n".join(lines)

    if total_pages > 1:
        nav_buttons: list[InlineKeyboardButton] = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"admin:pending:page:{page - 1}")
            )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(text="بعدی ➡️", callback_data=f"admin:pending:page:{page + 1}")
            )
        if nav_buttons:
            keyboard_rows.append(nav_buttons)
    keyboard_rows.append([InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="admin:pending:refresh")])
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)

    do_edit = default_edit if edit is None else edit
    if do_edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _show_pending_detail(target: MessageLike, state: FSMContext, appt_id: int, edit: bool) -> None:
    message, default_edit = _resolve_message(target)
    async with SessionLocal() as session:
        appt = await session.get(
            Appointment,
            appt_id,
            options=(
                selectinload(Appointment.user),
                selectinload(Appointment.slot),
            ),
        )
    if not appt:
        await message.answer("نوبت مورد نظر یافت نشد.")
        await _show_pending_list(message, state, edit=False, force_refresh=True)
        return
    user = appt.user
    patient_name = user.full_name if user and user.full_name else "-"
    patient_phone = user.phone if user and user.phone else "-"
    time_label = _format_appointment_time(appt)
    status_label = {
        AppointmentStatus.pending: "در انتظار",
        AppointmentStatus.confirmed: "تأیید شده",
        AppointmentStatus.canceled: "لغو شده",
    }.get(appt.status, getattr(appt.status, "value", str(appt.status)))
    payment_label = _payment_status_label(appt.payment_status)
    lines = [
        f"جزئیات نوبت #{appt.id}",
        f"بیمار: {patient_name}",
        f"شماره تماس: {patient_phone}",
        f"تاریخ: {appt.jdate}",
        f"بازه زمانی: {time_label}",
        f"وضعیت نوبت: {status_label}",
        f"وضعیت پرداخت: {payment_label}",
    ]
    if appt.reference_code:
        lines.append(f"کد پیگیری: {appt.reference_code}")
    if appt.notes:
        lines.append(f"یادداشت: {appt.notes}")
    if appt.created_at:
        lines.append(f"زمان ثبت: {appt.created_at:%Y-%m-%d %H:%M}")
    detail_text = "\n".join(line for line in lines if line)

    buttons: list[list[InlineKeyboardButton]] = []
    if appt.payment_status != PaymentStatus.settled:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✅ تأیید پرداخت",
                    callback_data=f"admin:pending:confirm:{appt.id}",
                )
            ]
        )
    if appt.payment_status != PaymentStatus.rejected:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="⛔ رد پرداخت",
                    callback_data=f"admin:pending:cancel:{appt.id}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text="📄 دریافت PDF", callback_data=f"admin:pending:pdf:{appt.id}"),
            InlineKeyboardButton(text="⬅️ بازگشت به لیست", callback_data="admin:pending:refresh"),
        ]
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    if edit and default_edit:
        try:
            await message.edit_text(detail_text, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(detail_text, reply_markup=keyboard)
    else:
        await message.answer(detail_text, reply_markup=keyboard)

    if appt.receipt_file_id:
        try:
            await message.answer_photo(
                appt.receipt_file_id,
                caption=f"رسید پرداخت نوبت #{appt.id}",
            )
        except TelegramBadRequest:
            await message.answer("نمایش تصویر رسید امکان‌پذیر نبود.")


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


def _payment_status_label(value: PaymentStatus | str) -> str:
    if isinstance(value, PaymentStatus):
        return PAYMENT_STATUS_LABELS.get(value, value.value)
    if isinstance(value, str):
        for item in PaymentStatus:
            if item.value == value or item.name == value:
                return PAYMENT_STATUS_LABELS.get(item, item.value)
        return value
    return str(value)


def _normalize_phone_input(value: str) -> str | None:
    if not value:
        return None
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+98"):
        cleaned = "0" + cleaned[3:]
    elif cleaned.startswith("0098"):
        cleaned = "0" + cleaned[4:]
    elif cleaned.startswith("98") and len(cleaned) == 12:
        cleaned = "0" + cleaned[2:]
    if len(cleaned) == 11 and cleaned.isdigit() and cleaned.startswith("0"):
        return cleaned
    return None


def _extract_id_from_callback(data: str) -> int | None:
    try:
        return int(data.rsplit(":", 1)[-1])
    except (ValueError, AttributeError):
        return None


async def _find_user_by_identifier(session, identifier: str) -> User | None:
    token = (identifier or "").strip()
    if not token:
        return None
    if token.isdigit():
        user = await session.get(User, int(token))
        if user:
            return user
        result = await session.execute(select(User).where(User.tg_id == int(token)))
        user = result.scalar_one_or_none()
        if user:
            return user
    normalized_phone = _normalize_phone_input(token)
    if normalized_phone:
        result = await session.execute(select(User).where(User.phone == normalized_phone))
        user = result.scalar_one_or_none()
        if user:
            return user
    return None


async def _get_latest_user_appointment(session, user_id: int) -> Appointment | None:
    stmt = (
        select(Appointment)
        .where(Appointment.user_id == user_id)
        .order_by(Appointment.jdate.desc(), Appointment.created_at.desc())
        .options(selectinload(Appointment.slot))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


def _display_user_name(user: User) -> str:
    if user.full_name:
        return user.full_name
    if user.phone:
        return user.phone
    if user.tg_id:
        return f"tg:{user.tg_id}"
    return f"کاربر #{user.id}"

def _format_appointment_time(appointment: Appointment) -> str:
    if appointment.slot and appointment.slot.start_time and appointment.slot.end_time:
        return f"{appointment.slot.start_time.strftime('%H:%M')} - {appointment.slot.end_time.strftime('%H:%M')}"
    return appointment.time_slot or "-"



async def _store_prompt_reference(state: FSMContext, message: Message) -> None:
    await state.update_data(
        {
            "message_prompt_chat_id": message.chat.id,
            "message_prompt_message_id": message.message_id,
        }
    )


async def _clear_prompt_reference(state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("message_prompt_chat_id") or data.get("message_prompt_message_id"):
        await state.update_data(
            {
                "message_prompt_chat_id": None,
                "message_prompt_message_id": None,
            }
        )


async def _update_prompt_message(
    bot,
    state: FSMContext,
    text: str,
    keyboard: InlineKeyboardMarkup,
    fallback_message: Message,
) -> bool:
    data = await state.get_data()
    chat_id = data.get("message_prompt_chat_id")
    message_id = data.get("message_prompt_message_id")
    if chat_id and message_id:
        try:
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=keyboard,
            )
            return True
        except TelegramBadRequest:
            pass
        except TelegramNetworkError as exc:
            print(f"[ERROR] Failed to edit prompt message: {exc}")
            return False
    try:
        sent = await fallback_message.answer(text, reply_markup=keyboard)
    except TelegramNetworkError as exc:
        print(f"[ERROR] Failed to send prompt message: {exc}")
        return False
    await state.update_data(
        {
            "message_prompt_chat_id": sent.chat.id,
            "message_prompt_message_id": sent.message_id,
        }
    )
    return True


async def _refresh_schedule_month_map(state: FSMContext) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    async with SessionLocal() as session:
        today = date.today()
        lookback = today - timedelta(days=BOOKING_RANGE_DAYS)
        end = today + timedelta(days=BOOKING_RANGE_DAYS)
        days = await list_schedule_days(session, lookback, end)
        if not days:
            result = await session.execute(
                select(ScheduleDay).order_by(ScheduleDay.date.asc())
            )
            days = result.scalars().all()
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


async def _refresh_pdf_month_map(state: FSMContext) -> Dict[str, Dict[str, List[Dict[str, object]]]]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Appointment.jdate, func.count(Appointment.id))
            .group_by(Appointment.jdate)
            .order_by(Appointment.jdate)
        )
        month_map: Dict[str, Dict[str, object]] = {}
        for jdate, total in result.all():
            try:
                jalali = JalaliDate.fromisoformat(jdate)
            except ValueError:
                try:
                    gregorian = datetime.strptime(jdate, "%Y-%m-%d").date()
                    jalali = JalaliDate.to_jalali(gregorian)
                except Exception:
                    jalali = None
            if jalali:
                month_key = f"{jalali.year}-{jalali.month:02d}"
                month_label = f"{jalali_month_name(jalali.month)} {jalali.year}"
                day_label = f"{format_jalali_day(jalali)} | مجموع نوبت‌ها: {total}"
            else:
                month_key = jdate[:7]
                month_label = month_key
                day_label = f"{jdate} | مجموع نوبت‌ها: {total}"
            month_entry = month_map.setdefault(
                month_key,
                {
                    "label": month_label,
                    "days": [],
                },
            )
            month_entry["days"].append(
                {
                    "jdate": jdate,
                    "label": day_label,
                    "count": total,
                }
            )
        for entry in month_map.values():
            entry["days"].sort(key=lambda item: item["jdate"])  # type: ignore[index]
            total_days = len(entry["days"])  # type: ignore[index]
            total_appointments = sum(day["count"] for day in entry["days"])  # type: ignore[index]
            entry["label"] = f"{entry['label']} (روزها: {total_days} | نوبت‌ها: {total_appointments})"  # type: ignore[index]
        ordered = dict(sorted(month_map.items(), key=lambda item: item[0]))
    await state.update_data({PDF_STATE_MONTH_MAP: ordered})
    return ordered  # type: ignore[return-value]


async def _show_pdf_months(message: Message, state: FSMContext, *, edit: bool) -> None:
    month_map = await _refresh_pdf_month_map(state)
    month_rows = [(info["label"], key) for key, info in month_map.items()]
    keyboard = admin_report_months_keyboard(month_rows)
    await state.set_state(AdminPdfStates.selecting_month)
    content = PDF_MONTH_PROMPT if month_rows else PDF_EMPTY_TEXT
    if edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _show_pdf_days(message: Message, state: FSMContext, month_key: str, *, edit: bool) -> None:
    month_map = await _refresh_pdf_month_map(state)
    if not month_map or month_key not in month_map:
        await _show_pdf_months(message, state, edit=edit)
        return
    entry = month_map[month_key]
    rows = [(day["label"], day["jdate"]) for day in entry["days"]]  # type: ignore[index]
    keyboard = admin_report_days_keyboard(rows, month_key)
    await state.update_data({PDF_STATE_SELECTED_MONTH: month_key})
    await state.set_state(AdminPdfStates.selecting_day)
    content_lines = [entry["label"]]  # type: ignore[index]
    if rows:
        content_lines.append(PDF_DAY_PROMPT)
    else:
        content_lines.append(PDF_EMPTY_TEXT)
    content = "\n".join(content_lines)
    if edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)



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




def _format_online_status(status: OnlineConsultRequestStatus) -> str:
    labels = {
        OnlineConsultRequestStatus.pending: "در انتظار ارسال رسید",
        OnlineConsultRequestStatus.awaiting_confirmation: "در انتظار تایید",
        OnlineConsultRequestStatus.approved: "تایید شده",
        OnlineConsultRequestStatus.rejected: "رد شده",
        OnlineConsultRequestStatus.completed: "پاسخ داده شد",
    }
    return labels.get(status, status.value)


def _online_action_keyboard(request_id: int, status: OnlineConsultRequestStatus) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status == OnlineConsultRequestStatus.awaiting_confirmation:
        rows.append([
            InlineKeyboardButton(text="تأیید", callback_data=f"admin:online:approve:{request_id}"),
            InlineKeyboardButton(text="رد کردن", callback_data=f"admin:online:reject:{request_id}"),
        ])
    elif status == OnlineConsultRequestStatus.approved:
        rows.append([
            InlineKeyboardButton(text="علامت‌گذاری به عنوان انجام شد", callback_data=f"admin:online:complete:{request_id}"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="admin:online")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_request_summary(request, user) -> str:
    lines = [
        f"شناسه: #{request.id}",
        f"وضعیت: {_format_online_status(request.status)}",
        f"کاربر: {user.full_name or '-'}",
        f"زمان ثبت: {request.created_at:%Y-%m-%d %H:%M}",
        "پرسش:",
        request.question,
    ]
    if request.admin_notes:
        lines.append("")
        lines.append("یادداشت مدیر:")
        lines.append(request.admin_notes)
    if request.answer:
        lines.append("")
        lines.append("پاسخ:")
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
            InlineKeyboardButton(text=f"مشاهدهٔ درخواست #{req.id}", callback_data=f"admin:online:view:{req.id}"),
        ])
    keyboard_rows.append([InlineKeyboardButton(text="⬅️ بازگشت", callback_data="menu:home")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    content = "\n".join(lines)
    if edit:
        await message.edit_text(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _show_online_request_detail(message: Message, request_id: int, *, edit: bool) -> None:
    async with SessionLocal() as session:
        request = await get_request(session, request_id)
        if not request:
            await message.answer("درخواست پیدا نشد.")
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
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    await _show_online_requests(c.message, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:online:view:"))
async def admin_online_view(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    try:
        request_id = int(c.data.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        await c.answer("شناسه درخواست نامعتبر است.", show_alert=True)
        return
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
            await c.answer("درخواست پیدا نشد.", show_alert=True)
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
    month_key = c.data.rsplit(":", 1)[-1]
    await _show_schedule_days(c, state, month_key)


@router.callback_query(F.data == "admin:schedule:back:months")
async def admin_schedule_back_months(c: CallbackQuery, state: FSMContext):
    await _show_schedule_months(c.message, state, edit=True)
    await c.answer()


@router.callback_query(AdminScheduleStates.selecting_day, F.data.startswith("admin:schedule:day:"))
async def admin_schedule_choose_day(c: CallbackQuery, state: FSMContext):
    jdate = c.data.rsplit(":", 1)[-1]
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
    day_id = int(c.data.rsplit(":", 1)[-1])
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
    day_id = int(c.data.rsplit(":", 1)[-1])
    async with SessionLocal() as session:
        success, affected = await delete_schedule_day(session, day_id)
        if not success and affected > 0:
            success, affected = await delete_schedule_day(session, day_id, force=True)
            if not success:
                await c.answer("حذف انجام نشد.", show_alert=True)
                return
            await c.answer(f"روز حذف شد و {affected} نوبت لغو گردید.", show_alert=True)
        elif not success:
            await c.answer("حذف انجام نشد.", show_alert=True)
            return
        else:
            await c.answer(SCHEDULE_DAY_DELETED)
    await _show_schedule_months(c.message, state, edit=True)


@router.callback_query(F.data.startswith("admin:schedule:add_slot:"))
async def admin_schedule_add_slot_prompt(c: CallbackQuery, state: FSMContext):
    day_id = int(c.data.rsplit(":", 1)[-1])
    await state.update_data({STATE_SLOT_DRAFT: {"day_id": day_id}})
    await state.set_state(AdminScheduleStates.awaiting_slot_start)
    keyboard = admin_schedule_slot_start_keyboard(_start_time_choices())
    try:
        await c.message.edit_text(SLOT_START_PROMPT, reply_markup=keyboard)
    except TelegramBadRequest:
        await c.message.answer(SLOT_START_PROMPT, reply_markup=keyboard)
    await c.answer()


@router.callback_query(F.data.startswith("admin:schedule:slot_edit:"))
async def admin_schedule_slot_edit(c: CallbackQuery, state: FSMContext):
    slot_id = int(c.data.rsplit(":", 1)[-1])
    async with SessionLocal() as session:
        slot = await get_slot_by_id(session, slot_id)
    if not slot:
        await c.answer("بازه یافت نشد.", show_alert=True)
        return
    draft = {
        "day_id": slot.day_id,
        "slot_id": slot.id,
        "mode": "edit",
    }
    await state.update_data({STATE_SLOT_DRAFT: draft})
    await state.set_state(AdminScheduleStates.awaiting_slot_start)
    keyboard = admin_schedule_slot_start_keyboard(_start_time_choices())
    info_text = (
        f"{SLOT_START_PROMPT}\n"
        f"بازه فعلی: {slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')} | ظرفیت: {slot.capacity}"
    )
    try:
        await c.message.edit_text(info_text, reply_markup=keyboard)
    except TelegramBadRequest:
        await c.message.answer(info_text, reply_markup=keyboard)
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
    slot_id = draft.get("slot_id")
    if not all([day_id, start_str, end_str]):
        await c.answer(SLOT_DRAFT_INCOMPLETE, show_alert=True)
        return
    start_time = _parse_time(start_str)
    end_time = _parse_time(end_str)
    if not start_time or not end_time:
        await c.answer(SLOT_TIME_INVALID, show_alert=True)
        return
    async with SessionLocal() as session:
        try:
            if slot_id:
                await update_schedule_slot(session, int(slot_id), start_time, end_time, capacity)
                result_text = SLOT_UPDATED
            else:
                await create_schedule_slot(session, int(day_id), start_time, end_time, capacity)
                result_text = SLOT_CREATED
        except SlotOverlapError as error:
            await c.answer(
                SLOT_OVERLAP_EXISTS.format(
                    start=error.existing_start.strftime("%H:%M"),
                    end=error.existing_end.strftime("%H:%M"),
                ),
                show_alert=True,
            )
            return
        except SlotCreationError as error:
            await c.answer(str(error), show_alert=True)
            return
    await state.update_data({STATE_SLOT_DRAFT: {}})
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    await c.answer(result_text)
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
    slot_id = int(c.data.rsplit(":", 1)[-1])
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
    slot_id = int(c.data.rsplit(":", 1)[-1])
    async with SessionLocal() as session:
        success, affected = await delete_schedule_slot(session, slot_id)
        if not success and affected > 0:
            success, affected = await delete_schedule_slot(session, slot_id, force=True)
            if not success:
                await c.answer("حذف بازه انجام نشد.", show_alert=True)
                return
            await c.answer(f"بازه حذف شد و {affected} نوبت لغو گردید.", show_alert=True)
        elif not success:
            await c.answer("حذف بازه انجام نشد.", show_alert=True)
            return
        else:
            await c.answer(SLOT_DELETE_SUCCESS)
    data = await state.get_data()
    day_id = data.get(STATE_SELECTED_DAY_ID)
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    if day_id and jdate:
        await _show_schedule_day_detail(c.message, state, day_id, jdate, edit=True)


@router.callback_query(F.data.startswith("admin:schedule:slot_info:"))
async def admin_schedule_slot_info(c: CallbackQuery):
    slot_id = c.data.rsplit(":", 1)[-1]
    await c.answer(f"شناسه بازه: {slot_id}")


@router.callback_query(F.data.startswith("admin:schedule:export:"))
async def admin_schedule_export(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    parts = c.data.split(":", 4)
    if len(parts) < 5:
        await c.answer("درخواست نامعتبر است.", show_alert=True)
        return
    jdate = parts[4]
    pdf_path, _ = await _create_day_report_pdf(jdate)
    if not pdf_path:
        await c.answer("برای این تاریخ نوبتی ثبت نشده است.", show_alert=True)
        return
    await c.message.answer_document(FSInputFile(pdf_path), caption=f"گزارش بیماران تاریخ {jdate}")
    await c.answer("گزارش آماده شد.")

@router.callback_query(F.data.startswith("admin:payment:"))
async def admin_payment_review(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    parts = c.data.split(":", 3)
    if len(parts) != 4:
        await c.answer("درخواست نامعتبر است.", show_alert=True)
        return
    action = parts[2]
    try:
        appointment_id = int(parts[3])
    except ValueError:
        await c.answer("شناسه نوبت نامعتبر است.", show_alert=True)
        return
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
            await c.answer("نوبت یافت نشد.", show_alert=True)
            return
        current_status = appointment.payment_status
        if action == "approve":
            if current_status == PaymentStatus.settled:
                await c.answer("این پرداخت قبلاً تایید شده است.", show_alert=True)
                return
            appointment.payment_status = PaymentStatus.settled
            appointment.status = AppointmentStatus.confirmed
            decision_text = "پرداخت تایید شد ✅"
            patient_text = f"پرداخت نوبت #{appointment.id} تایید شد. منتظر حضور شما هستیم."
            await _ensure_reference_code(session, appointment)
        elif action == "reject":
            if current_status == PaymentStatus.rejected:
                await c.answer("این پرداخت قبلاً رد شده است.", show_alert=True)
                return
            appointment.payment_status = PaymentStatus.rejected
            decision_text = "پرداخت رد شد ❌"
            patient_text = f"پرداخت نوبت #{appointment.id} تایید نشد. لطفاً مجدداً اقدام به پرداخت یا ارسال رسید کنید."
        else:
            await c.answer("عملیات ناشناخته است.", show_alert=True)
            return
        await session.commit()
        await session.refresh(appointment)
        user = appointment.user
        slot = appointment.slot
    patient_text += _reference_notice(appointment)
    caption = c.message.caption or ""
    if caption:
        caption += "\n\n"
    time_label = appointment.time_slot or "-"
    if slot:
        time_label = f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}"
    caption += f"نتیجه بررسی: {decision_text}"
    caption += f"\nبازه زمانی: {time_label}"
    if appointment.reference_code:
        caption += f"\nکد مرجع: {appointment.reference_code}"
    try:
        await c.message.edit_caption(caption, reply_markup=None)
    except TelegramBadRequest:
        await c.message.answer(decision_text)
    await c.answer(decision_text)
    if user and user.tg_id:
        try:
            await c.bot.send_message(chat_id=user.tg_id, text=patient_text)
            if action == "approve":
                payment_label = _payment_status_label(appointment.payment_status)
                pdf_path = generate_appointment_pdf(
                    "reports",
                    appointment.id,
                    user.full_name or "-",
                    appointment.jdate,
                    time_label,
                    appointment.status.value,
                    payment_label=payment_label,
                    reference_code=appointment.reference_code,
                )
                await c.bot.send_document(
                    chat_id=user.tg_id,
                    document=FSInputFile(pdf_path),
                    caption=f"رسید نوبت #{appointment.id}{_reference_notice(appointment)}",
                )
        except Exception:
            pass
@router.callback_query(F.data == "admin:pending")
async def pending_from_menu(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("اجازه دسترسی ندارید.", show_alert=True)
        return
    await state.clear()
    await _show_pending_list(c, state, edit=True, force_refresh=True)
    await c.answer()


@router.callback_query(F.data == "admin:pending:refresh")
async def pending_refresh(c: CallbackQuery, state: FSMContext):
    await _show_pending_list(c, state, edit=True, force_refresh=True)
    await c.answer()


@router.message(StateFilter(None), F.text == ADMIN_PENDING_TEXT)
async def pending_list(m: Message, state: FSMContext):
    await _show_pending_list(m, state, edit=False, force_refresh=True)


@router.callback_query(F.data.startswith("admin:pending:view:"))
async def pending_view(c: CallbackQuery, state: FSMContext):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("شناسه نوبت نامعتبر است.", show_alert=True)
        return
    await _show_pending_detail(c, state, appt_id, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:pending:page:"))
async def pending_change_page(c: CallbackQuery, state: FSMContext):
    try:
        page = int(c.data.rsplit(":", 1)[-1])
    except (ValueError, AttributeError):
        await c.answer()
        return
    await _show_pending_list(c, state, edit=True, page=page)
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
        await _show_pending_list(c, state, edit=True, force_refresh=True)
        return
    await c.answer("نوبت تایید شد ✅" + _reference_notice(appt), show_alert=True)
    await _show_pending_detail(c, state, appt_id, edit=True)
    await _send_receipt_to_user(c.bot, appt_id)


@router.callback_query(F.data.startswith("admin:pending:cancel:"))
async def pending_cancel(c: CallbackQuery, state: FSMContext):
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
        await _show_pending_list(c, state, edit=True, force_refresh=True)
        return
    await c.answer("نوبت لغو شد.", show_alert=True)
    await _show_pending_detail(c, state, appt_id, edit=True)


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
    payment_label = _payment_status_label(appt.payment_status)
    path = generate_appointment_pdf(
        "./reports",
        appt.id,
        user.full_name or "-",
        appt.jdate,
        appt.time_slot,
        appt.status.value,
        payment_label=payment_label,
        reference_code=appt.reference_code,
        appointments=appointments,
    )
    await c.message.answer_document(
        FSInputFile(path),
        caption=f"گزارش PDF نوبت #{appt_id}{_reference_notice(appt)}",
    )
    await c.answer("فایل PDF ارسال شد.")


@router.callback_query(F.data == "admin:pdf")
async def admin_pdf_from_menu(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("اجازه دسترسی ندارید.", show_alert=True)
        return
    await state.update_data({PDF_STATE_MONTH_MAP: None, PDF_STATE_SELECTED_MONTH: None})
    await _show_pdf_months(c.message, state, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:pdf:month:"))
async def admin_pdf_select_month(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("اجازه دسترسی ندارید.", show_alert=True)
        return
    parts = c.data.split(":", 3)
    if len(parts) != 4:
        await c.answer("درخواست نامعتبر است.", show_alert=True)
        return
    month_key = parts[3]
    await _show_pdf_days(c.message, state, month_key, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:pdf:day:"))
async def admin_pdf_select_day(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("اجازه دسترسی ندارید.", show_alert=True)
        return
    parts = c.data.split(":", 3)
    if len(parts) != 4:
        await c.answer("درخواست نامعتبر است.", show_alert=True)
        return
    jdate = parts[3]
    pdf_path, _ = await _create_day_report_pdf(jdate)
    if not pdf_path:
        await c.answer("برای این تاریخ نوبتی ثبت نشده است.", show_alert=True)
        await state.update_data({PDF_STATE_MONTH_MAP: None, PDF_STATE_SELECTED_MONTH: None})
        await _show_pdf_months(c.message, state, edit=True)
        return
    await c.message.answer_document(FSInputFile(pdf_path), caption=f"گزارش بیماران تاریخ {jdate}")
    await c.answer("گزارش ارسال شد.")


@router.message(StateFilter(None), F.text == ADMIN_PDF_TEXT)
async def admin_pdf(m: Message, state: FSMContext):
    if m.from_user.id not in settings.admin_ids:
        return
    await state.update_data({PDF_STATE_MONTH_MAP: None, PDF_STATE_SELECTED_MONTH: None})
    await _show_pdf_months(m, state, edit=False)


@router.message(StateFilter(None), F.text.regexp(r"^/confirm_(\d+)$"))
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
    await m.answer(f"نوبت #{appt_id} تأیید شد ✅{_reference_notice(appt)}")
    await _send_receipt_to_user(m.bot, appt_id)


@router.message(StateFilter(None), F.text.regexp(r"^/cancel_(\d+)$"))
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


@router.message(StateFilter(None), F.text.regexp(r"^/pdf_(\d+)$"))
async def pdf_report(m: Message, regexp):
    appt_id = int(regexp.group(1))
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            await m.answer("شناسه نوبت نامعتبر است.")
            return
        user = await session.get(User, appt.user_id)
        appointments = await _fetch_user_appointments_summary(session, user.id)
    payment_label = _payment_status_label(appt.payment_status)
    path = generate_appointment_pdf(
        "./reports",
        appt.id,
        user.full_name or "-",
        appt.jdate,
        appt.time_slot,
        appt.status.value,
        payment_label=payment_label,
        reference_code=appt.reference_code,
        appointments=appointments,
    )
    await m.answer_document(
        FSInputFile(path),
        caption=f"گزارش نوبت #{appt_id}{_reference_notice(appt)}",
    )


async def _send_receipt_to_user(bot, appt_id: int) -> None:
    try:
        async with SessionLocal() as session:
            appt = await session.get(
                Appointment,
                appt_id,
                options=(
                    selectinload(Appointment.user),
                    selectinload(Appointment.slot),
                ),
            )
            if not appt or not appt.user or not appt.user.tg_id:
                return
            time_label = appt.time_slot or "-"
            if appt.slot:
                time_label = f"{appt.slot.start_time.strftime('%H:%M')} - {appt.slot.end_time.strftime('%H:%M')}"
            payment_label = _payment_status_label(appt.payment_status)
            path = generate_appointment_pdf(
                "./reports",
                appt.id,
                appt.user.full_name or "-",
                appt.jdate,
                time_label,
                appt.status.value,
                payment_label=payment_label,
                reference_code=appt.reference_code,
            )
    except Exception as exc:
        print(f"[WARN] Unable to build receipt PDF: {exc}")
        return
    caption = f"رسید نوبت #{appt_id}{_reference_notice(appt)}"
    try:
        await bot.send_document(
            chat_id=appt.user.tg_id,
            document=FSInputFile(path),
            caption=caption,
        )
    except Exception as exc:
        print(f"[WARN] Failed to send receipt to user: {exc}")


def _calculate_age(birth: date | None) -> str:
    if not birth:
        return "-"
    today_j = JalaliDate.today()
    birth_j = JalaliDate.to_jalali(birth)
    years = today_j.year - birth_j.year - (
        (today_j.month, today_j.day) < (birth_j.month, birth_j.day)
    )
    return str(years)


async def _create_day_report_pdf(jdate: str) -> Tuple[str | None, int]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Appointment)
            .options(selectinload(Appointment.user))
            .where(Appointment.jdate == jdate)
            .order_by(Appointment.time_slot.asc(), Appointment.created_at.asc())
        )
        appointments = result.scalars().all()
    if not appointments:
        return None, 0
    rows: List[Dict[str, str]] = []
    for appt in appointments:
        user = appt.user
        full_name = (user.full_name if user and user.full_name else "-")
        phone = (user.phone if user and user.phone else "-")
        age = _calculate_age(user.birth_date if user else None)
        payment_label = _payment_status_label(appt.payment_status)
        rows.append(
            {
                "full_name": full_name,
                "phone": phone,
                "age": age,
                "payment": payment_label,
            }
        )
    path = generate_day_summary_pdf("./reports", jdate, rows)
    return path, len(rows)


async def _fetch_user_appointments_summary(session, user_id: int) -> List[Dict[str, str]]:
    result = await session.execute(
        select(Appointment.jdate, Appointment.time_slot, Appointment.status, Appointment.created_at)
        .where(Appointment.user_id == user_id)
        .order_by(Appointment.jdate.desc(), Appointment.created_at.desc())
    )
    summary: List[Dict[str, str]] = []
    for jdate, time_slot, status, _created_at in result.all():
        status_value = (
            status.value if isinstance(status, AppointmentStatus) else str(status)
        )
        summary.append(
            {
                "jdate": jdate,
                "time_slot": time_slot or "-",
                "status": status_value,
            }
        )
    return summary


async def _update_appointment_status(
    appt_id: int,
    *,
    status: AppointmentStatus,
    payment_status: PaymentStatus,
) -> Appointment | None:
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            return None
        appt.status = status
        appt.payment_status = payment_status
        if payment_status == PaymentStatus.settled:
            await _ensure_reference_code(session, appt)
        await session.commit()
        await session.refresh(appt)
        return appt


MessageLike = Union[Message, CallbackQuery]


def _resolve_message(target: MessageLike) -> tuple[Message, bool]:
    if isinstance(target, CallbackQuery):
        return target.message, True
    return target, False













