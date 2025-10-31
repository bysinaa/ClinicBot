# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Optional, Sequence, Union

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command
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
    admin_message_mode_keyboard,
    admin_message_confirm_keyboard,
    admin_message_cancel_keyboard,
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
)
from src.services.clinic import get_profile_cached
from src.services.online_consult import (
    get_request,
    list_requests,
    update_status as update_online_status,
)
from src.services.broadcast import (
    DEFAULT_THROTTLE_DELAY,
    broadcast_messages,
    render_message_template,
    send_message_with_retry,
)
from src.services.pdf_reports import generate_appointment_pdf, generate_day_summary_pdf
from src.states import AdminMessageStates, AdminPdfStates, AdminScheduleStates, AdminStates
from src.utils.jalali import format_jalali_day, gregorian_to_jalali, jalali_month_name

ADMIN_MENU_TEXT = "منوی مدیریت. لطفاً یک گزینه را انتخاب کنید:"
ADMIN_PENDING_EMPTY = "نوبتی در انتظار بررسی وجود ندارد."
SCHEDULE_EMPTY_TEXT = "هیچ برنامه‌ای ثبت نشده است. برای شروع «افزودن روز» را انتخاب کنید."
SCHEDULE_MONTH_PROMPT = "ماه مورد نظر برای مدیریت را انتخاب کنید:"
SCHEDULE_DAY_PROMPT = "روز مورد نظر را انتخاب کنید:"
SCHEDULE_DATE_PROMPT = "ØªØ§Ø±ÛŒØ® Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± Ø±Ø§ Ø§Ø² Ù…ÛŒØ§Ù† Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯."
SCHEDULE_DATE_INVALID = "تاریخ نامعتبر است یا خارج از بازه شش‌ماههٔ پیشِ‌رو قرار دارد."
SCHEDULE_DAY_ADDED = "روز {label} با موفقیت افزوده شد."
SCHEDULE_DAY_TOGGLED = "وضعیت روز به {status} تغییر کرد."
SCHEDULE_DAY_DELETED = "روز حذف شد."
SCHEDULE_DAY_DELETE_BLOCKED = "تا زمانی که برای این روز نوبت فعال وجود دارد نمی‌توان آن را حذف کرد."
SLOT_START_PROMPT = "Ø²Ù…Ø§Ù† Ø´Ø±ÙˆØ¹ Ø¨Ø§Ø²Ù‡ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯."
SLOT_END_PROMPT = "Ø²Ù…Ø§Ù† Ù¾Ø§ÛŒØ§Ù† Ø¨Ø§Ø²Ù‡ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯."
SLOT_CAPACITY_PROMPT = "Ø¸Ø±ÙÛŒØª Ø¨Ø§Ø²Ù‡ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯."
SLOT_TIME_INVALID = "زمان وارد‌شده معتبر نیست."
SLOT_RANGE_INVALID = "زمان پایان باید بعد از زمان شروع باشد."
SLOT_CAPACITY_INVALID = "ظرفیت باید بزرگ‌تر از صفر باشد."
SLOT_CREATED = "بازهٔ زمانی با موفقیت ایجاد شد."
SLOT_OVERLAP_EXISTS = "این بازه با بازهٔ {start} تا {end} تداخل دارد."
SLOT_NO_END_AVAILABLE = "Ø¨Ø¹Ø¯ Ø§Ø² Ø§ÛŒÙ† Ø²Ù…Ø§Ù† Ø´Ø±ÙˆØ¹ØŒ Ú¯Ø²ÛŒÙ†Ù‡â€ŒØ§ÛŒ Ø¨Ø±Ø§ÛŒ Ù¾Ø§ÛŒØ§Ù† ÙˆØ¬ÙˆØ¯ Ù†Ø¯Ø§Ø±Ø¯."
SLOT_DRAFT_INCOMPLETE = "Ø§Ø·Ù„Ø§Ø¹Ø§Øª Ø¨Ø§Ø²Ù‡ Ù†Ø§Ù‚Øµ Ø§Ø³Øª. Ù„Ø·ÙØ§Ù‹ Ø¯ÙˆØ¨Ø§Ø±Ù‡ ØªÙ„Ø§Ø´ Ú©Ù†ÛŒØ¯."
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
SCHEDULE_DAY_PICKER_EMPTY = "ØªÙ…Ø§Ù… Ø±ÙˆØ²Ù‡Ø§ÛŒ Ø¨Ø§Ø²Ù‡ Ø§Ù†ØªØ®Ø§Ø¨ÛŒ Ø§Ø² Ù‚Ø¨Ù„ Ø¯Ø± Ø¨Ø±Ù†Ø§Ù…Ù‡ Ø«Ø¨Øª Ø´Ø¯Ù‡â€ŒØ§Ù†Ø¯."

BOOKING_RANGE_DAYS = 180

PAYMENT_STATUS_LABELS = {
    PaymentStatus.unpaid: "Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ù¾Ø±Ø¯Ø§Ø®Øª",
    PaymentStatus.awaiting_confirmation: "Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± Ø¨Ø±Ø±Ø³ÛŒ",
    PaymentStatus.settled: "Ù¾Ø±Ø¯Ø§Ø®Øª ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡",
    PaymentStatus.rejected: "Ù¾Ø±Ø¯Ø§Ø®Øª Ø±Ø¯ Ø´Ø¯Ù‡",
}

MESSAGE_CANCEL_TOKENS = {"Ù„ØºÙˆ", "cancel", "/cancel"}
MESSAGE_TEMPLATE_HELP = (
    "متن پیام را وارد کنید.\n"
    "می‌توانید از متغیرهای زیر استفاده کنید: \n"
    "{name} - نام و نام خانوادگی بیمار\n"
    "{phone} - شماره تماس\n"
    "{date} - تاریخ آخرین نوبت ثبت شده\n"
    "{time} - بازه زمانی آخرین نوبت\n"
    "{appointment_id} - شناسه آخرین نوبت\n"
    "{status} - وضعیت آخرین نوبت\n"
    "مثال: سلام {name}! نوبت شما در تاریخ {date} ساعت {time} برگزار می‌شود.\n"
)

REMINDER_DEFAULT_TEMPLATE = (
    "سلام {name}! یادآوری می‌کنیم نوبت شما در تاریخ {date} ساعت {time} برگزار می‌شود. "
    "لطفاً ۱۵ دقیقه زودتر در کلینیک حضور داشته باشید."
)
REMINDER_LOOKAHEAD_DAYS = 14

logger = logging.getLogger(__name__)


def _broadcast_debug(message: str) -> None:
    try:
        with open("broadcast_debug.log", "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat()} {message}\n")
    except Exception as exc:
        logging.getLogger(__name__).warning("[broadcast] failed to write debug log: %s", exc)


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
    return f"Ú©Ø§Ø±Ø¨Ø± #{user.id}"

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


async def _update_broadcast_status_message(bot, chat_id: int, message_id: int, text: str) -> None:
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        try:
            await bot.send_message(chat_id, text)
        except TelegramNetworkError as exc:
            logger.error("Failed to send broadcast status message: %s", exc)




async def _run_reminder_job(
    bot,
    template: str,
    recipients: list[dict[str, object]],
    *,
    chat_id: int,
    message_id: int,
) -> None:
    total = len(recipients)
    success = 0
    failures: list[tuple[int | None, str]] = []
    for index, info in enumerate(recipients, start=1):
        user_ns = SimpleNamespace(
            full_name=info.get("full_name") or "",
            phone=info.get("phone") or "",
        )
        status_value = info.get("status") or ""
        status_ns = SimpleNamespace(value=status_value)
        appointment_ns = SimpleNamespace(
            id=info.get("appointment_id"),
            jdate=info.get("date"),
            time_slot=info.get("time"),
            status=status_ns,
        )
        message_text = render_message_template(template, user_ns, appointment_ns)
        tg_id = int(info.get("tg_id"))
        ok, error = await send_message_with_retry(
            bot,
            tg_id,
            message_text,
        )
        if ok:
            success += 1
            _broadcast_debug(f"reminder_sent target={tg_id} index={index}/{total}")
        else:
            failures.append((info.get("user_id"), error or "unknown"))
            _broadcast_debug(f"reminder_failed target={tg_id} error={error}")
        if DEFAULT_THROTTLE_DELAY:
            await asyncio.sleep(DEFAULT_THROTTLE_DELAY)
    summary_text = (
        "ارسال یادآوری‌ها پایان یافت.\n"
        f"موفق: {success}\n"
        f"ناموفق: {total - success}"
    )
    if failures:
        details = "\n".join(
            f"- #{user_id or '?'}: {err}" for user_id, err in failures[:5]
        )
        summary_text += f"\nجزئیات:\n{details}"
        if len(failures) > 5:
            summary_text += f"\n... {len(failures) - 5} مورد دیگر."
    _broadcast_debug(f"reminder_summary success={success} total={total}")
    await _update_broadcast_status_message(bot, chat_id, message_id, summary_text)

async def _run_broadcast_job(bot, template: str, chat_id: int, message_id: int) -> None:
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(User).where(User.tg_id.is_not(None)).order_by(User.id)
            )
            users = result.scalars().all()
            appointments: dict[int, Appointment | None] = {}
            for user in users:
                appointments[user.id] = await _get_latest_user_appointment(session, user.id)
    except Exception as exc:
        logger.exception("Failed to prepare broadcast recipients")
        await _update_broadcast_status_message(
            bot,
            chat_id,
            message_id,
            f"خطا Ø¯Ø± Ø¢Ù…Ø§Ø¯Ù‡â€ŒØ³Ø§Ø²ÛŒ Ø§Ø±Ø³Ø§Ù„ Ù¾ÛŒØ§Ù… Ù‡Ù…Ú¯Ø§Ù†ÛŒ.\nError: {exc}",
        )
        return
    if not users:
        await _update_broadcast_status_message(
            bot,
            chat_id,
            message_id,
            "Ù‡ÛŒÚ† Ú©Ø§Ø±Ø¨Ø±ÛŒ Ø¨Ø±Ø§ÛŒ Ø§Ø±Ø³Ø§Ù„ Ù¾ÛŒØ§Ù… Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.",
        )
        return
    await _update_broadcast_status_message(
        bot,
        chat_id,
        message_id,
        "ارسال پیام همگانی آغاز شد...",
    )
    try:
        summary = await broadcast_messages(
            bot,
            template,
            users,
            appointments,
        )
    except Exception as exc:
        logger.exception("Broadcast job failed during delivery")
        await _update_broadcast_status_message(
            bot,
            chat_id,
            message_id,
            f"خطا Ø¯Ø± Ø²Ù…Ø§Ù† Ø§Ø±Ø³Ø§Ù„ Ù¾ÛŒØ§Ù… Ù‡Ù…Ú¯Ø§Ù†ÛŒ.\nError: {exc}",
        )
        return
    summary_text = (
        "Ø§Ø±Ø³Ø§Ù„ Ù¾ÛŒØ§Ù… Ù‡Ù…Ú¯Ø§Ù†ÛŒ Ù¾Ø§ÛŒØ§Ù† ÛŒØ§ÙØª.\n"
        f"Ù…ÙˆÙÙ‚: {summary.success}\n"
        f"Ù†Ø§Ù…ÙˆÙÙ‚: {summary.failed}"
    )
    if summary.failed and summary.errors:
        max_examples = 5
        details = "\n".join(
            f"- #{user_id or '?'}: {error}" for user_id, error in summary.errors[:max_examples]
        )
        summary_text += f"\nØ¬Ø²Ø¦ÛŒØ§Øª:\n{details}"
        if len(summary.errors) > max_examples:
            summary_text += f"\n... {len(summary.errors) - max_examples} Ù…ÙˆØ±Ø¯ Ø¯ÛŒÚ¯Ø±."
    await _update_broadcast_status_message(
        bot,
        chat_id,
        message_id,
        summary_text,
    )


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
    buttons.append([InlineKeyboardButton(text="ðŸ”„ Ø¨Ø±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ", callback_data="admin:pending:refresh")])
    buttons.append([InlineKeyboardButton(text="â¬…ï¸ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="menu:home")])
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
            inline_keyboard=[[InlineKeyboardButton(text="â¬…ï¸ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="menu:home")]]
        )
    else:
        content = "Ù†ÙˆØ¨Øªâ€ŒÙ‡Ø§ÛŒ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø± ØªØ§ÛŒÛŒØ¯. Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ù‡Ø± Ù…ÙˆØ±Ø¯ ÛŒÚ©ÛŒ Ø§Ø² Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯."
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
            content = "Ø§ÛŒÙ† Ù†ÙˆØ¨Øª Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯ ÛŒØ§ Ù‚Ø¨Ù„Ø§Ù‹ ØªØºÛŒÛŒØ± Ú©Ø±Ø¯Ù‡ Ø§Ø³Øª."
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="â¬…ï¸ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="admin:pending")]]
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
        AppointmentStatus.pending: "Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø±",
        AppointmentStatus.confirmed: "ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡",
        AppointmentStatus.canceled: "Ù„ØºÙˆ Ø´Ø¯Ù‡",
    }
    payment_value = getattr(appt, "payment_status", None)
    payment_label = getattr(payment_value, "value", "-")
    lines = [
        f"Ù†ÙˆØ¨Øª #{appt.id}",
        f"ÙˆØ¶Ø¹ÛŒØª: {status_map.get(appt.status, appt.status.value)}",
        f"Ù¾Ø±Ø¯Ø§Ø®Øª: {payment_label}",
        f"ØªØ§Ø±ÛŒØ®: {appt.jdate}",
        f"Ø³Ø§Ø¹Øª: {appt.time_slot or '-'}",
    ]
    if user:
        lines.append(f"Ø¨ÛŒÙ…Ø§Ø±: {user.full_name or '-'}")
        lines.append(f"Ø´Ù…Ø§Ø±Ù‡ ØªÙ…Ø§Ø³: {user.phone or '-'}")
    if appt.notes:
        lines.append(f"ÛŒØ§Ø¯Ø¯Ø§Ø´Øª: {appt.notes}")
    content = "\n".join(lines)
    buttons: list[list[InlineKeyboardButton]] = []
    if appt.status == AppointmentStatus.pending:
        buttons.append([
            InlineKeyboardButton(text="âœ… ØªØ§ÛŒÛŒØ¯ Ù†ÙˆØ¨Øª", callback_data=f"admin:pending:confirm:{appt.id}"),
            InlineKeyboardButton(text="âŒ Ù„ØºÙˆ Ù†ÙˆØ¨Øª", callback_data=f"admin:pending:cancel:{appt.id}"),
        ])
    buttons.append([InlineKeyboardButton(text="ðŸ“„ ØµØ¯ÙˆØ± PDF", callback_data=f"admin:pending:pdf:{appt.id}")])
    buttons.append([InlineKeyboardButton(text="â¬…ï¸ Ø¨Ø§Ø²Ú¯Ø´Øª Ø¨Ù‡ ÙÙ‡Ø±Ø³Øª", callback_data="admin:pending")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    if do_edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


def _jalali_from_string(jdate: str) -> JalaliDate:
    year, month, day = map(int, jdate.split("-"))
    return JalaliDate(year, month, day)


async def _create_day_report_pdf(jdate: str) -> tuple[str | None, int]:
    async with SessionLocal() as session:
        stmt = (
            select(Appointment)
            .where(Appointment.jdate == jdate)
            .options(
                selectinload(Appointment.user),
                selectinload(Appointment.slot),
            )
            .order_by(Appointment.time_slot)
        )
        appointments = (await session.execute(stmt)).scalars().all()
    if not appointments:
        return None, 0
    today = date.today()
    rows = []
    for appointment in appointments:
        user = appointment.user
        age = "-"
        if user and user.birth_date:
            age_value = (
                today.year
                - user.birth_date.year
                - ((today.month, today.day) < (user.birth_date.month, user.birth_date.day))
            )
            age = str(age_value)
        rows.append(
            {
                "full_name": user.full_name or "-" if user else "-",
                "age": age,
                "phone": user.phone or "-" if user else "-",
                "payment": _payment_status_label(appointment.payment_status),
            }
        )
    pdf_path = generate_day_summary_pdf("reports", jdate, rows)
    return pdf_path, len(rows)


async def _fetch_pdf_month_map() -> dict[str, dict[str, object]]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Appointment.jdate, func.count(Appointment.id))
            .group_by(Appointment.jdate)
            .order_by(Appointment.jdate)
        )
    month_map: dict[str, dict[str, object]] = {}
    for jdate, count in result:
        jalali = _jalali_from_string(jdate)
        month_key = f"{jalali.year:04d}-{jalali.month:02d}"
        month_label = f"{jalali_month_name(jalali.month)} {jalali.year}"
        day_label = f"{format_jalali_day(jalali)} â€” {count} Ù†ÙˆØ¨Øª"
        entry = month_map.setdefault(
            month_key,
            {"label": month_label, "days": []},
        )
        entry["days"].append({"jdate": jdate, "label": day_label, "count": count})
    for entry in month_map.values():
        entry["days"].sort(key=lambda item: item["jdate"], reverse=True)
    ordered = dict(sorted(month_map.items(), key=lambda item: item[0], reverse=True))
    return ordered


async def _load_pdf_month_map(state: FSMContext) -> dict[str, dict[str, object]]:
    data = await state.get_data()
    cached = data.get(PDF_STATE_MONTH_MAP)
    if cached:
        return cached  # type: ignore[return-value]
    month_map = await _fetch_pdf_month_map()
    await state.update_data({PDF_STATE_MONTH_MAP: month_map})
    return month_map


async def _show_pdf_months(message: Message, state: FSMContext, *, edit: bool) -> None:
    month_map = await _load_pdf_month_map(state)
    if not month_map:
        await state.clear()
        await _show_admin_menu(message, edit=edit, text="Ù‡ÛŒÚ† Ù†ÙˆØ¨ØªÛŒ Ø¨Ø±Ø§ÛŒ Ø®Ø±ÙˆØ¬ÛŒ ÙˆØ¬ÙˆØ¯ Ù†Ø¯Ø§Ø±Ø¯.")
        return
    month_rows = [(info["label"], key) for key, info in month_map.items()]
    keyboard = admin_report_months_keyboard(month_rows)
    content = "Ù…Ø§Ù‡ Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± Ø¨Ø±Ø§ÛŒ Ø¯Ø±ÛŒØ§ÙØª Ú¯Ø²Ø§Ø±Ø´ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯."
    await state.set_state(AdminPdfStates.selecting_month)
    if edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)


async def _show_pdf_days(message: Message, state: FSMContext, month_key: str, *, edit: bool) -> None:
    month_map = await _load_pdf_month_map(state)
    entry = month_map.get(month_key)
    if not entry:
        await _show_pdf_months(message, state, edit=edit)
        return
    rows = [(day["label"], day["jdate"]) for day in entry["days"]]
    keyboard = admin_report_days_keyboard(rows, month_key)
    content = f"{entry['label']}\nØ±ÙˆØ² Ù…ÙˆØ±Ø¯ Ù†Ø¸Ø± Ø¨Ø±Ø§ÛŒ Ø¯Ø±ÛŒØ§ÙØª Ú¯Ø²Ø§Ø±Ø´ Ø±Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯."
    await state.update_data({PDF_STATE_SELECTED_MONTH: month_key})
    await state.set_state(AdminPdfStates.selecting_day)
    if edit:
        try:
            await message.edit_text(content, reply_markup=keyboard)
        except TelegramBadRequest:
            await message.answer(content, reply_markup=keyboard)
    else:
        await message.answer(content, reply_markup=keyboard)




def _reminder_dates_keyboard(options: list[dict[str, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in options:
        callback = f"admin:message:reminder:date:{item['jdate']}"
        label = f"{item['label']} ({item['count']} نوبت)"
        rows.append([InlineKeyboardButton(text=label, callback_data=callback)])
    rows.append([InlineKeyboardButton(text="لغو", callback_data="admin:message:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _list_reminder_dates(limit_days: int = REMINDER_LOOKAHEAD_DAYS) -> list[dict[str, str]]:
    async with SessionLocal() as session:
        stmt = select(Appointment.jdate, func.count(Appointment.id)).group_by(Appointment.jdate)
        result = await session.execute(stmt)
        today_g = date.today()
        end_g = today_g + timedelta(days=limit_days)
        items: list[tuple[datetime, str, int]] = []
        for jdate, count in result.all():
            try:
                jalali = _jalali_from_string(jdate)
                gregorian = jalali.to_gregorian()
            except ValueError:
                continue
            if gregorian < today_g or gregorian > end_g:
                continue
            items.append((datetime.combine(gregorian, time.min), jdate, count))
        items.sort(key=lambda entry: entry[0])
    output: list[dict[str, str]] = []
    for _, jdate, count in items:
        jalali = _jalali_from_string(jdate)
        label = format_jalali_day(jalali)
        output.append({"jdate": jdate, "label": label, "count": count})
    return output


async def _collect_reminder_recipients(jdate: str) -> list[dict[str, object]]:
    async with SessionLocal() as session:
        stmt = (
            select(Appointment)
            .where(Appointment.jdate == jdate)
            .options(selectinload(Appointment.user), selectinload(Appointment.slot))
            .order_by(Appointment.time_slot)
        )
        result = await session.execute(stmt)
        recipients: list[dict[str, object]] = []
        for appointment in result.scalars():
            user = appointment.user
            if not user or not user.tg_id:
                continue
            recipients.append(
                {
                    "user_id": user.id,
                    "tg_id": int(user.tg_id),
                    "full_name": user.full_name or "",
                    "phone": user.phone or "",
                    "appointment_id": appointment.id,
                    "date": appointment.jdate,
                    "time": _format_appointment_time(appointment),
                    "status": appointment.status.value if appointment.status else "",
                }
            )
    return recipients

# ----------------------------- پیام همگانی -----------------------------
@router.callback_query(F.data == "admin:message")
async def admin_message_entry(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminMessageStates.choosing_mode)
    content = "لطفاً نوع ارسال پیام را انتخاب کنید:"
    try:
        prompt = await c.message.edit_text(content, reply_markup=admin_message_mode_keyboard())
    except TelegramBadRequest:
        prompt = await c.message.answer(content, reply_markup=admin_message_mode_keyboard())
    await _store_prompt_reference(state, prompt)
    await c.answer()


@router.callback_query(F.data == "admin:message:single")
async def admin_message_single(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    await state.update_data({"message_mode": "single"})
    await state.set_state(AdminMessageStates.awaiting_target)
    instructions = (
        "شناسه تلگرام، شماره تماس یا شناسه داخلی بیمار را وارد کنید.\n"
        "برای لغو، «لغو» را ارسال کنید."
    )
    try:
        prompt = await c.message.edit_text(instructions, reply_markup=admin_message_cancel_keyboard())
    except TelegramBadRequest:
        prompt = await c.message.answer(instructions, reply_markup=admin_message_cancel_keyboard())
    await _store_prompt_reference(state, prompt)
    await c.answer()


@router.callback_query(F.data == "admin:message:reminder")
async def admin_message_reminder(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    await state.update_data({"message_mode": "reminder", "reminder_recipients": None})
    options = await _list_reminder_dates()
    if not options:
        await state.clear()
        await c.message.answer("برای روزهای آینده نوبتی جهت یادآوری ثبت نشده است.")
        await _show_admin_menu(c.message, edit=True)
        await c.answer("موردی یافت نشد.")
        return
    keyboard = _reminder_dates_keyboard(options)
    text = "تاریخ نوبت موردنظر برای ارسال یادآوری را انتخاب کنید:"
    try:
        prompt = await c.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        prompt = await c.message.answer(text, reply_markup=keyboard)
    await _store_prompt_reference(state, prompt)
    await state.set_state(AdminMessageStates.reminder_selecting_date)
    await c.answer()


@router.callback_query(AdminMessageStates.reminder_selecting_date, F.data.startswith("admin:message:reminder:date:"))
async def admin_message_reminder_select_date(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    try:
        _, _, _, jdate = c.data.split(":", 3)
    except ValueError:
        await c.answer("درخواست نامعتبر است.", show_alert=True)
        return
    recipients = await _collect_reminder_recipients(jdate)
    if not recipients:
        options = await _list_reminder_dates()
        message = "برای این تاریخ کاربری با شناسه تلگرام یافت نشد. تاریخ دیگری را انتخاب کنید."
        keyboard = _reminder_dates_keyboard(options) if options else admin_message_mode_keyboard()
        await _update_prompt_message(c.bot, state, message, keyboard, c.message)
        await c.answer("موردی یافت نشد.", show_alert=True)
        return
    jalali = _jalali_from_string(jdate)
    date_label = format_jalali_day(jalali)
    default_template = REMINDER_DEFAULT_TEMPLATE
    sample = recipients[0]
    sample_user = SimpleNamespace(full_name=sample.get("full_name") or "", phone=sample.get("phone") or "")
    sample_status = SimpleNamespace(value=sample.get("status") or "")
    sample_appointment = SimpleNamespace(
        id=sample.get("appointment_id"),
        jdate=sample.get("date"),
        time_slot=sample.get("time"),
        status=sample_status,
    )
    preview = render_message_template(default_template, sample_user, sample_appointment)
    message_text = (
        f"یادآوری برای تاریخ {date_label} ({jdate}) آماده شد.\n"
        f"تعداد دریافت‌کنندگان: {len(recipients)} نفر.\n\n"
        "نمونه پیام پیش‌فرض:\n"
        f"{preview}\n\n"
        "متن یادآوری دلخواه خود را ارسال کنید یا برای استفاده از همین متن عبارت «تایید» را بفرستید. برای لغو «لغو» را ارسال کنید."
    )
    await state.update_data(
        {
            "message_mode": "reminder",
            "reminder_date": jdate,
            "reminder_recipients": recipients,
            "reminder_default_template": default_template,
            "recipient_count": len(recipients),
        }
    )
    _broadcast_debug(f"reminder_date_selected jdate={jdate} recipients={len(recipients)}")
    updated = await _update_prompt_message(c.bot, state, message_text, admin_message_cancel_keyboard(), c.message)
    if not updated:
        await c.message.answer(message_text, reply_markup=admin_message_cancel_keyboard())
    await state.set_state(AdminMessageStates.reminder_entering_template)
    await c.answer()


@router.message(AdminMessageStates.reminder_entering_template)
async def admin_message_reminder_template(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    if text.lower() in MESSAGE_CANCEL_TOKENS:
        await _clear_prompt_reference(state)
        await state.clear()
        await m.answer("عملیات لغو شد.")
        await _show_admin_menu(m, edit=False)
        return
    data = await state.get_data()
    recipients = data.get("reminder_recipients") or []
    if not recipients:
        await state.clear()
        await m.answer("هیچ بیماری برای یادآوری وجود ندارد.")
        await _show_admin_menu(m, edit=False)
        return
    default_template = data.get("reminder_default_template") or REMINDER_DEFAULT_TEMPLATE
    normalized = text.lower()
    if normalized in {"تایید", "تاييد", "default", "/default"}:
        template = default_template
    else:
        template = text
    sample = recipients[0]
    sample_user = SimpleNamespace(full_name=sample.get("full_name") or "", phone=sample.get("phone") or "")
    sample_status = SimpleNamespace(value=sample.get("status") or "")
    sample_appointment = SimpleNamespace(
        id=sample.get("appointment_id"),
        jdate=sample.get("date"),
        time_slot=sample.get("time"),
        status=sample_status,
    )
    preview = render_message_template(template, sample_user, sample_appointment)
    confirmation = (
        f"پیش‌نمایش پیام:\n\n"
        f"{preview}\n\n"
        f"تعداد دریافت‌کنندگان: {len(recipients)} نفر.\n"
        "برای ارسال، دکمه «ارسال» را فشار دهید یا متن جدیدی ارسال کنید."
    )
    await state.update_data({"message_template": template, "recipient_count": len(recipients)})
    _broadcast_debug("reminder_template_ready")
    updated = await _update_prompt_message(m.bot, state, confirmation, admin_message_confirm_keyboard(), m)
    if not updated:
        await m.answer(confirmation, reply_markup=admin_message_confirm_keyboard())
    await state.set_state(AdminMessageStates.confirming)
@router.callback_query(F.data == "admin:message:all")
async def admin_message_all(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    async with SessionLocal() as session:
        total = await session.scalar(select(func.count(User.id)).where(User.tg_id.is_not(None)))
    if not total:
        await state.clear()
        await c.answer("هیچ بیماری در ربات ثبت نشده است.", show_alert=True)
        await _show_admin_menu(c.message, edit=True)
        return
    await state.update_data({"message_mode": "all", "recipient_count": int(total)})
    await state.set_state(AdminMessageStates.awaiting_message)
    text_block = (
        f"ارسال پیام همگانی فعال شد. تعداد دریافت‌کنندگان: {int(total)} نفر.\n"
        f"{MESSAGE_TEMPLATE_HELP}\n"
        "متن پیام را بفرستید یا برای لغو «لغو» را ارسال کنید."
    )
    try:
        prompt = await c.message.edit_text(text_block, reply_markup=admin_message_cancel_keyboard())
    except TelegramBadRequest:
        prompt = await c.message.answer(text_block, reply_markup=admin_message_cancel_keyboard())
    await _store_prompt_reference(state, prompt)
    await c.answer()


@router.message(AdminMessageStates.awaiting_target)
async def admin_message_receive_target(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    if text.lower() in MESSAGE_CANCEL_TOKENS:
        await _clear_prompt_reference(state)
        await state.clear()
        await m.answer("عملیات لغو شد.")
        await _show_admin_menu(m, edit=False)
        return
    async with SessionLocal() as session:
        user = await _find_user_by_identifier(session, text)
    if not user:
        await m.answer("کاربری با این اطلاعات پیدا نشد. دوباره تلاش کنید یا «لغو» را بفرستید.")
        return
    if not user.tg_id:
        await m.answer("این کاربر هنوز حساب تلگرام خود را به ربات متصل نکرده است.")
        return
    await state.update_data({
        "message_mode": "single",
        "target_user_id": user.id,
        "target_display": _display_user_name(user),
    })
    await state.set_state(AdminMessageStates.awaiting_message)
    prompt_text = (
        f"بیمار انتخاب شده: {_display_user_name(user)} (ID: {user.id}).\n"
        f"{MESSAGE_TEMPLATE_HELP}\n"
        "متن پیام را بنویسید یا برای لغو «لغو» را ارسال کنید."
    )
    prompt = await m.answer(prompt_text, reply_markup=admin_message_cancel_keyboard())
    await _store_prompt_reference(state, prompt)


@router.message(AdminMessageStates.awaiting_message)
async def admin_message_receive_template(m: Message, state: FSMContext):
    text = (m.text or "").strip()
    logger.info("[broadcast] received template text=%r", text)
    _broadcast_debug(f"receive_template text={text!r}")
    if text.lower() in MESSAGE_CANCEL_TOKENS:
        await _clear_prompt_reference(state)
        await state.clear()
        await m.answer("عملیات لغو شد.")
        await _show_admin_menu(m, edit=False)
        return
    if not text:
        await m.answer("لطفاً متن پیام را وارد کنید.")
        return
    data = await state.get_data()
    mode = data.get("message_mode")
    if mode not in {"single", "all"}:
        logger.warning("[broadcast] unexpected message_mode=%r", mode)
        _broadcast_debug(f"unexpected_mode {mode!r}")
        await m.answer("حالت ارسال نامشخص است. لطفاً دوباره تلاش کنید.")
        return
    await state.update_data({"message_template": text})
    if mode == "single":
        target_id = data.get("target_user_id")
        logger.info("[broadcast] confirming single send to target_id=%s", target_id)
        logger.info("[broadcast] preparing single preview for target_id=%s", target_id)
        _broadcast_debug(f"single_preview target_id={target_id}")
        async with SessionLocal() as session:
            user = await session.get(User, int(target_id)) if target_id is not None else None
            if not user:
                logger.warning("[broadcast] target user %s not found", target_id)
                _broadcast_debug(f"single_preview user_missing id={target_id}")
                await state.clear()
                await m.answer("بیمار انتخاب شده پیدا نشد. عملیات لغو شد.")
                await _show_admin_menu(m, edit=False)
                return
            appointment = await _get_latest_user_appointment(session, user.id)
        preview = render_message_template(text, user, appointment)
        preview_text = (
            f"پیش‌نمایش برای {_display_user_name(user)}:\n\n{preview}\n\n"
            "برای تایید روی دکمه «ارسال» بزنید یا برای لغو «لغو» را بفرستید."
        )
        try:
            preview_message = await m.answer(preview_text, reply_markup=admin_message_confirm_keyboard())
        except TelegramNetworkError as exc:
            await m.answer(f"امکان ارسال پیش‌نمایش وجود ندارد.\nError: {exc}")
            return
        await _store_prompt_reference(state, preview_message)
        _broadcast_debug("broadcast_preview_sent")
        await state.set_state(AdminMessageStates.confirming)
        return
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.tg_id.is_not(None)).order_by(User.id)
        )
        users = result.scalars().all()
        if not users:
            logger.warning("[broadcast] no users found for broadcast")
            _broadcast_debug("broadcast_no_users")
            await state.clear()
            await m.answer("هیچ کاربری برای ارسال پیام یافت نشد.")
            await _show_admin_menu(m, edit=False)
            return
        sample_user = users[0]
        sample_appointment = await _get_latest_user_appointment(session, sample_user.id)
    preview = render_message_template(text, sample_user, sample_appointment)
    await state.update_data({"recipient_count": len(users)})
    await state.set_state(AdminMessageStates.confirming)
    preview_text = (
        f"پیش‌نمایش برای نمونه ({_display_user_name(sample_user)}):\n\n{preview}\n\n"
        f"تعداد دریافت‌کنندگان: {len(users)} نفر.\n"
        "برای تایید روی دکمه «ارسال» بزنید یا برای لغو «لغو» را بفرستید."
    )
    try:
        preview_message = await m.answer(preview_text, reply_markup=admin_message_confirm_keyboard())
    except TelegramNetworkError as exc:
        await m.answer(f"امکان ارسال پیش‌نمایش وجود ندارد.\nError: {exc}")
        return
    await _store_prompt_reference(state, preview_message)

@router.callback_query(AdminMessageStates.confirming, F.data == "admin:message:confirm")
async def admin_message_confirm(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    data = await state.get_data()
    template = data.get("message_template")
    mode = data.get("message_mode")
    if not template or not mode:
        logger.warning("[broadcast] confirmation missing template or mode: %r %r", template, mode)
        _broadcast_debug("confirm_missing_template_or_mode")
        await c.answer("اطلاعات پیام ناقص است.", show_alert=True)
        return
    try:
        await c.message.edit_reply_markup()
    except TelegramBadRequest:
        pass
    await _clear_prompt_reference(state)
    if mode == "single":
        target_id = data.get("target_user_id")
        async with SessionLocal() as session:
            user = await session.get(User, int(target_id))
            if not user or not user.tg_id:
                logger.warning("[broadcast] invalid single recipient during confirm: %s", target_id)
                _broadcast_debug(f"confirm_invalid_single target_id={target_id}")
                await state.clear()
                await c.message.answer("بیمار انتخاب‌شده موجود نیست یا شناسه تلگرام ندارد.")
                await _show_admin_menu(c.message, edit=False)
                await c.answer("خطا", show_alert=True)
                return
            appointment = await _get_latest_user_appointment(session, user.id)
        message_text = render_message_template(template, user, appointment)
        ok, error = await send_message_with_retry(
            c.bot,
            int(user.tg_id),
            message_text,
        )
        if ok:
            logger.info("[broadcast] single send succeeded for %s", target_id)
            _broadcast_debug(f"confirm_single_success target_id={target_id}")
            await c.message.answer("پیام برای بیمار ارسال شد.")
            await _show_admin_menu(c.message, edit=False)
            await c.answer("ارسال شد.")
        else:
            logger.warning("[broadcast] single send failed for %s error=%r", target_id, error)
            failure_text = "ارسال پیام انجام نشد. لطفاً دوباره تلاش کنید."
            if error:
                failure_text += f"\nError: {error}"
            await c.message.answer(failure_text)
            await _show_admin_menu(c.message, edit=False)
            await c.answer("خطا", show_alert=True)
        await state.clear()
        return

    if mode == "reminder":
        recipients = data.get("reminder_recipients") or []
        if not recipients:
            await c.message.answer("هیچ مخاطبی برای یادآوری انتخاب نشده است.")
            await _show_admin_menu(c.message, edit=False)
            await c.answer("خطا", show_alert=True)
            await state.clear()
            return
        status_message = await c.message.answer("ارسال یادآوری‌ها در حال آماده‌سازی است...")
        _broadcast_debug(f"reminder_send_start count={len(recipients)}")
        asyncio.create_task(
            _run_reminder_job(
                c.bot,
                template,
                recipients,
                chat_id=status_message.chat.id,
                message_id=status_message.message_id,
            )
        )
        await _show_admin_menu(c.message, edit=False)
        await c.answer("ارسال یادآوری آغاز شد.")
        await state.clear()
        return

    # Broadcast
    status_message = await c.message.answer("ارسال پیام همگانی در حال آماده‌سازی است...")
    logger.info("[broadcast] starting background broadcast job (recipients=%s)", data.get("recipient_count"))
    _broadcast_debug("confirm_broadcast_started")
    asyncio.create_task(
        _run_broadcast_job(
            bot=c.bot,
            template=template,
            chat_id=status_message.chat.id,
            message_id=status_message.message_id,
        )
    )
    await _show_admin_menu(c.message, edit=False)
    await c.answer("ارسال پیام همگانی آغاز شد.")
    await state.clear()
    return


@router.callback_query(F.data == "admin:message:cancel")
async def admin_message_cancel(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    await _clear_prompt_reference(state)
    await state.clear()
    try:
        await c.message.edit_reply_markup()
    except TelegramBadRequest:
        pass
    await c.message.answer("عملیات لغو شد.")
    await _show_admin_menu(c.message, edit=False)
    await c.answer("لغو شد.")


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
            day_label = f"{format_jalali_day(jalali)} | {'ÙØ¹Ø§Ù„' if day.is_active else 'ØºÛŒØ±ÙØ¹Ø§Ù„'} | Ø¨Ø§Ø²Ù‡â€ŒÙ‡Ø§: {active_slots}/{slot_total}"
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
            entry["label"] = f"{entry['label']} ({active_days}/{total_days} Ø±ÙˆØ² ÙØ¹Ø§Ù„)"  # type: ignore[index]
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
    status_text = "ÙØ¹Ø§Ù„" if day.is_active else "ØºÛŒØ±ÙØ¹Ø§Ù„"
    active_slots = sum(1 for s in summaries if s.is_active)
    total_slots = len(summaries)
    lines = [
        f"{format_jalali_day(jalali)} ({jdate})",
        f"ÙˆØ¶Ø¹ÛŒØª Ø±ÙˆØ²: {status_text}",
        f"ØªØ¹Ø¯Ø§Ø¯ Ø¨Ø§Ø²Ù‡â€ŒÙ‡Ø§ÛŒ ÙØ¹Ø§Ù„: {active_slots}/{total_slots}",
    ]
    if day.notes:
        lines.append(f"ÛŒØ§Ø¯Ø¯Ø§Ø´Øª: {day.notes}")
    if not summaries:
        lines.append("Ù‡ÛŒÚ† Ø¨Ø§Ø²Ù‡â€ŒØ§ÛŒ Ø¨Ø±Ø§ÛŒ Ø§ÛŒÙ† Ø±ÙˆØ² Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª.")
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
    rows.append([InlineKeyboardButton(text="â¬…ï¸ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="admin:online")])
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
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="â¬…ï¸ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="menu:home")]])
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
    keyboard_rows.append([InlineKeyboardButton(text="â¬…ï¸ Ø¨Ø§Ø²Ú¯Ø´Øª", callback_data="menu:home")])
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
        await c.answer("Ø§Ø¬Ø§Ø²Ù‡ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ø¯Ø§Ø±ÛŒØ¯.", show_alert=True)
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
        await c.answer("ØªØ§Ø±ÛŒØ® Ø§Ù†ØªØ®Ø§Ø¨ÛŒ Ù…Ø¹ØªØ¨Ø± Ù†ÛŒØ³Øª.", show_alert=True)
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
    await m.answer("Ù„Ø·ÙØ§Ù‹ ØªØ§Ø±ÛŒØ® Ø±Ø§ Ø¨Ø§ Ø§Ø³ØªÙØ§Ø¯Ù‡ Ø§Ø² Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ Ø§Ù†ØªØ®Ø§Ø¨ Ú©Ù†ÛŒØ¯.")


@router.callback_query(F.data.startswith("admin:schedule:toggle_day:"))
async def admin_schedule_toggle_day(c: CallbackQuery, state: FSMContext):
    day_id = int(c.data.split(":", 2)[2])
    async with SessionLocal() as session:
        day = await session.get(ScheduleDay, day_id)
        if not day:
            await c.answer("Ø±ÙˆØ² ÛŒØ§ÙØª Ù†Ø´Ø¯.", show_alert=True)
            return
        new_status = not day.is_active
        await set_schedule_day_active(session, day_id, new_status)
    data = await state.get_data()
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    await c.answer(SCHEDULE_DAY_TOGGLED.format(status="ÙØ¹Ø§Ù„" if new_status else "ØºÛŒØ±ÙØ¹Ø§Ù„"))
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
        await c.answer("Ø­Ø°Ù Ø§Ù†Ø¬Ø§Ù… Ù†Ø´Ø¯.", show_alert=True)
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
        try:
            await create_schedule_slot(session, int(day_id), start_time, end_time, capacity)
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
    await m.answer("Ù„Ø·ÙØ§Ù‹ Ø§Ø² Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ Ø¨Ø±Ø§ÛŒ Ø§Ù†ØªØ®Ø§Ø¨ Ú¯Ø²ÛŒÙ†Ù‡ Ø§Ø³ØªÙØ§Ø¯Ù‡ Ú©Ù†ÛŒØ¯.")




@router.callback_query(F.data.startswith("admin:schedule:slot_toggle:"))
async def admin_schedule_slot_toggle(c: CallbackQuery, state: FSMContext):
    slot_id = int(c.data.split(":", 2)[2])
    async with SessionLocal() as session:
        slot = await get_slot_by_id(session, slot_id)
        if not slot:
            await c.answer("Ø¨Ø§Ø²Ù‡ ÛŒØ§ÙØª Ù†Ø´Ø¯.", show_alert=True)
            return
        new_status = not slot.is_active
        await set_schedule_slot_active(session, slot_id, new_status)
    data = await state.get_data()
    day_id = data.get(STATE_SELECTED_DAY_ID)
    jdate = data.get(STATE_SELECTED_DAY_JDATE)
    await c.answer(SLOT_TOGGLED.format(status="ÙØ¹Ø§Ù„" if new_status else "ØºÛŒØ±ÙØ¹Ø§Ù„"))
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
        await c.answer("Ø­Ø°Ù Ø¨Ø§Ø²Ù‡ Ø§Ù†Ø¬Ø§Ù… Ù†Ø´Ø¯.", show_alert=True)
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
    await c.answer(f"Ø´Ù†Ø§Ø³Ù‡ Ø¨Ø§Ø²Ù‡: {slot_id}")


@router.callback_query(F.data.startswith("admin:schedule:export:"))
async def admin_schedule_export(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    parts = c.data.split(":", 4)
    if len(parts) < 5:
        await c.answer("Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
        return
    jdate = parts[4]
    pdf_path, _ = await _create_day_report_pdf(jdate)
    if not pdf_path:
        await c.answer("Ø¨Ø±Ø§ÛŒ Ø§ÛŒÙ† ØªØ§Ø±ÛŒØ® Ù†ÙˆØ¨ØªÛŒ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª.", show_alert=True)
        return
    await c.message.answer_document(FSInputFile(pdf_path), caption=f"Ú¯Ø²Ø§Ø±Ø´ Ø¨ÛŒÙ…Ø§Ø±Ø§Ù† ØªØ§Ø±ÛŒØ® {jdate}")
    await c.answer("Ú¯Ø²Ø§Ø±Ø´ Ø¢Ù…Ø§Ø¯Ù‡ Ø´Ø¯.")

@router.callback_query(F.data.startswith("admin:payment:"))
async def admin_payment_review(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("دسترسی لازم را ندارید.", show_alert=True)
        return
    parts = c.data.split(":", 3)
    if len(parts) != 4:
        await c.answer("Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
        return
    action = parts[2]
    try:
        appointment_id = int(parts[3])
    except ValueError:
        await c.answer("Ø´Ù†Ø§Ø³Ù‡ Ù†ÙˆØ¨Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
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
            await c.answer("Ù†ÙˆØ¨Øª ÛŒØ§ÙØª Ù†Ø´Ø¯.", show_alert=True)
            return
        current_status = appointment.payment_status
        if action == "approve":
            if current_status == PaymentStatus.settled:
                await c.answer("Ø§ÛŒÙ† Ù¾Ø±Ø¯Ø§Ø®Øª Ù‚Ø¨Ù„Ø§Ù‹ ØªØ§ÛŒÛŒØ¯ Ø´Ø¯Ù‡ Ø§Ø³Øª.", show_alert=True)
                return
            appointment.payment_status = PaymentStatus.settled
            appointment.status = AppointmentStatus.confirmed
            decision_text = "Ù¾Ø±Ø¯Ø§Ø®Øª ØªØ§ÛŒÛŒØ¯ Ø´Ø¯ âœ…"
            patient_text = f"Ù¾Ø±Ø¯Ø§Ø®Øª Ù†ÙˆØ¨Øª #{appointment.id} ØªØ§ÛŒÛŒØ¯ Ø´Ø¯. Ù…Ù†ØªØ¸Ø± Ø­Ø¶ÙˆØ± Ø´Ù…Ø§ Ù‡Ø³ØªÛŒÙ…."
        elif action == "reject":
            if current_status == PaymentStatus.rejected:
                await c.answer("Ø§ÛŒÙ† Ù¾Ø±Ø¯Ø§Ø®Øª Ù‚Ø¨Ù„Ø§Ù‹ Ø±Ø¯ Ø´Ø¯Ù‡ Ø§Ø³Øª.", show_alert=True)
                return
            appointment.payment_status = PaymentStatus.rejected
            decision_text = "Ù¾Ø±Ø¯Ø§Ø®Øª Ø±Ø¯ Ø´Ø¯ âŒ"
            patient_text = f"Ù¾Ø±Ø¯Ø§Ø®Øª Ù†ÙˆØ¨Øª #{appointment.id} ØªØ§ÛŒÛŒØ¯ Ù†Ø´Ø¯. Ù„Ø·ÙØ§Ù‹ Ù…Ø¬Ø¯Ø¯Ø§Ù‹ Ø§Ù‚Ø¯Ø§Ù… Ø¨Ù‡ Ù¾Ø±Ø¯Ø§Ø®Øª ÛŒØ§ Ø§Ø±Ø³Ø§Ù„ Ø±Ø³ÛŒØ¯ Ú©Ù†ÛŒØ¯."
        else:
            await c.answer("Ø¹Ù…Ù„ÛŒØ§Øª Ù†Ø§Ø´Ù†Ø§Ø®ØªÙ‡ Ø§Ø³Øª.", show_alert=True)
            return
        await session.commit()
        await session.refresh(appointment)
        user = appointment.user
        slot = appointment.slot
    caption = c.message.caption or ""
    if caption:
        caption += "\n\n"
    time_label = appointment.time_slot or "-"
    if slot:
        time_label = f"{slot.start_time.strftime('%H:%M')} - {slot.end_time.strftime('%H:%M')}"
    caption += f"Ù†ØªÛŒØ¬Ù‡ Ø¨Ø±Ø±Ø³ÛŒ: {decision_text}"
    caption += f"\nØ¨Ø§Ø²Ù‡ Ø²Ù…Ø§Ù†ÛŒ: {time_label}"
    try:
        await c.message.edit_caption(caption, reply_markup=None)
    except TelegramBadRequest:
        await c.message.answer(decision_text)
    await c.answer(decision_text)
    if user and user.tg_id:
        try:
            await c.bot.send_message(chat_id=user.tg_id, text=patient_text)
            if action == "approve":
                pdf_path = generate_appointment_pdf(
                    "reports",
                    appointment.id,
                    user.full_name or "-",
                    appointment.jdate,
                    time_label,
                    appointment.status.value,
                )
                await c.bot.send_document(
                    chat_id=user.tg_id,
                    document=FSInputFile(pdf_path),
                    caption=f"Ø±Ø³ÛŒØ¯ Ù†ÙˆØ¨Øª #{appointment.id}",
                )
        except Exception:
            pass
@router.callback_query(F.data == "admin:pending")
async def pending_from_menu(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("Ø§Ø¬Ø§Ø²Ù‡ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ø¯Ø§Ø±ÛŒØ¯.", show_alert=True)
        return
    await state.clear()
    await _show_pending_list(c, edit=True)
    await c.answer()


@router.callback_query(F.data == "admin:pending:refresh")
async def pending_refresh(c: CallbackQuery):
    await _show_pending_list(c, edit=True)
    await c.answer()


@router.message(F.text == "Ù†ÙˆØ¨Øªâ€ŒÙ‡Ø§ÛŒ Ø¯Ø± Ø§Ù†ØªØ¸Ø§Ø±")
async def pending_list(m: Message):
    await _show_pending_list(m, edit=False)


@router.callback_query(F.data.startswith("admin:pending:view:"))
async def pending_view(c: CallbackQuery):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("Ø´Ù†Ø§Ø³Ù‡ Ù†ÙˆØ¨Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
        return
    await _show_pending_detail(c, appt_id, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:pending:confirm:"))
async def pending_confirm(c: CallbackQuery):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("Ø´Ù†Ø§Ø³Ù‡ Ù†ÙˆØ¨Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
        return
    appt = await _update_appointment_status(
        appt_id,
        status=AppointmentStatus.confirmed,
        payment_status=PaymentStatus.settled,
    )
    if not appt:
        await c.answer("Ù†ÙˆØ¨Øª Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True)
        await _show_pending_list(c, edit=True)
        return
    await c.answer("Ù†ÙˆØ¨Øª ØªØ§ÛŒÛŒØ¯ Ø´Ø¯ âœ…", show_alert=True)
    await _show_pending_detail(c, appt_id, edit=True)


@router.callback_query(F.data.startswith("admin:pending:cancel:"))
async def pending_cancel(c: CallbackQuery):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("Ø´Ù†Ø§Ø³Ù‡ Ù†ÙˆØ¨Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
        return
    appt = await _update_appointment_status(
        appt_id,
        status=AppointmentStatus.canceled,
        payment_status=PaymentStatus.rejected,
    )
    if not appt:
        await c.answer("Ù†ÙˆØ¨Øª Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True)
        await _show_pending_list(c, edit=True)
        return
    await c.answer("Ù†ÙˆØ¨Øª لغو شد.", show_alert=True)
    await _show_pending_detail(c, appt_id, edit=True)


@router.callback_query(F.data.startswith("admin:pending:pdf:"))
async def pending_pdf(c: CallbackQuery):
    appt_id = _extract_id_from_callback(c.data)
    if appt_id is None:
        await c.answer("Ø´Ù†Ø§Ø³Ù‡ Ù†ÙˆØ¨Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
        return
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            await c.answer("Ù†ÙˆØ¨Øª Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯.", show_alert=True)
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
        caption=f"Ú¯Ø²Ø§Ø±Ø´ PDF Ù†ÙˆØ¨Øª #{appt_id}",
    )
    await c.answer("ÙØ§ÛŒÙ„ PDF ارسال شد.")


@router.callback_query(F.data == "admin:pdf")
async def admin_pdf_from_menu(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("Ø§Ø¬Ø§Ø²Ù‡ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ø¯Ø§Ø±ÛŒØ¯.", show_alert=True)
        return
    await state.update_data({PDF_STATE_MONTH_MAP: None, PDF_STATE_SELECTED_MONTH: None})
    await _show_pdf_months(c.message, state, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:pdf:month:"))
async def admin_pdf_select_month(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("Ø§Ø¬Ø§Ø²Ù‡ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ø¯Ø§Ø±ÛŒØ¯.", show_alert=True)
        return
    parts = c.data.split(":", 3)
    if len(parts) != 4:
        await c.answer("Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
        return
    month_key = parts[3]
    await _show_pdf_days(c.message, state, month_key, edit=True)
    await c.answer()


@router.callback_query(F.data.startswith("admin:pdf:day:"))
async def admin_pdf_select_day(c: CallbackQuery, state: FSMContext, current_user: Optional[User] = None):
    if not _is_admin_user(c.from_user.id, current_user):
        await c.answer("Ø§Ø¬Ø§Ø²Ù‡ Ø¯Ø³ØªØ±Ø³ÛŒ Ù†Ø¯Ø§Ø±ÛŒØ¯.", show_alert=True)
        return
    parts = c.data.split(":", 3)
    if len(parts) != 4:
        await c.answer("Ø¯Ø±Ø®ÙˆØ§Ø³Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.", show_alert=True)
        return
    jdate = parts[3]
    pdf_path, _ = await _create_day_report_pdf(jdate)
    if not pdf_path:
        await c.answer("Ø¨Ø±Ø§ÛŒ Ø§ÛŒÙ† ØªØ§Ø±ÛŒØ® Ù†ÙˆØ¨ØªÛŒ Ø«Ø¨Øª Ù†Ø´Ø¯Ù‡ Ø§Ø³Øª.", show_alert=True)
        await state.update_data({PDF_STATE_MONTH_MAP: None, PDF_STATE_SELECTED_MONTH: None})
        await _show_pdf_months(c.message, state, edit=True)
        return
    await c.message.answer_document(FSInputFile(pdf_path), caption=f"Ú¯Ø²Ø§Ø±Ø´ Ø¨ÛŒÙ…Ø§Ø±Ø§Ù† ØªØ§Ø±ÛŒØ® {jdate}")
    await c.answer("Ú¯Ø²Ø§Ø±Ø´ ارسال شد.")


@router.message(F.text == "Ú¯Ø²Ø§Ø±Ø´ PDF")
async def admin_pdf(m: Message, state: FSMContext):
    if m.from_user.id not in settings.admin_ids:
        return
    await state.update_data({PDF_STATE_MONTH_MAP: None, PDF_STATE_SELECTED_MONTH: None})
    await _show_pdf_months(m, state, edit=False)


@router.message(F.text.regexp(r"^/confirm_(\d+)$"))
async def admin_confirm(m: Message, regexp):
    appt_id = int(regexp.group(1))
    appt = await _update_appointment_status(
        appt_id,
        status=AppointmentStatus.confirmed,
        payment_status=PaymentStatus.settled,
    )
    if not appt:
        await m.answer("Ø´Ù†Ø§Ø³Ù‡ Ù†ÙˆØ¨Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.")
        return
    await m.answer(f"Ù†ÙˆØ¨Øª #{appt_id} ØªØ£ÛŒÛŒØ¯ Ø´Ø¯ âœ…")


@router.message(F.text.regexp(r"^/cancel_(\d+)$"))
async def admin_cancel(m: Message, regexp):
    appt_id = int(regexp.group(1))
    appt = await _update_appointment_status(
        appt_id,
        status=AppointmentStatus.canceled,
        payment_status=PaymentStatus.rejected,
    )
    if not appt:
        await m.answer("Ø´Ù†Ø§Ø³Ù‡ Ù†ÙˆØ¨Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.")
        return
    await m.answer(f"Ù†ÙˆØ¨Øª #{appt_id} Ù„ØºÙˆ Ø´Ø¯ âŒ")


@router.message(F.text.regexp(r"^/pdf_(\d+)$"))
async def pdf_report(m: Message, regexp):
    appt_id = int(regexp.group(1))
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            await m.answer("Ø´Ù†Ø§Ø³Ù‡ Ù†ÙˆØ¨Øª Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª.")
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
    await m.answer_document(FSInputFile(path), caption=f"Ú¯Ø²Ø§Ø±Ø´ Ù†ÙˆØ¨Øª #{appt_id}")
MessageLike = Union[Message, CallbackQuery]


def _resolve_message(target: MessageLike) -> tuple[Message, bool]:
    if isinstance(target, CallbackQuery):
        return target.message, True
    return target, False




