from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from persiantools.jdatetime import JalaliDate
from sqlalchemy import select

from src.config import settings
from src.database import SessionLocal
from src.keyboards import (
    admin_menu_inline,
    birth_day_keyboard,
    birth_month_keyboard,
    birth_year_keyboard,
    main_menu_inline,
)
from src.models import Role, User
from src.states import RegistrationStates
from src.utils.national_id import is_valid_iran_national_id
from src.services.clinic import get_profile_cached

router = Router(name="common")

BACK_BUTTON_TEXT = "⬅️ بازگشت"
REG_CANCEL = "لغو"

PATIENT_WELCOME = "سلام! برای استفاده از خدمات ابتدا ثبت‌نام را کامل کنید."
PATIENT_MENU_TEXT = "یکی از گزینه‌های زیر را انتخاب کنید:"
ADMIN_MENU_TEXT = "منوی مدیریت فعال است. یکی از گزینه‌ها را انتخاب کنید:"
REG_NAME_PROMPT = "نام و نام‌خانوادگی خود را ارسال کنید."
REG_NID_PROMPT = "کد ملی ۱۰ رقمی خود را وارد کنید."
REG_PHONE_PROMPT = "شماره موبایل خود را وارد کنید (مثلاً 09123456789)."
REG_BIRTH_PROMPT = "سال تولد خود را انتخاب کنید:"  # Jalali
REG_BIRTH_MONTH_PROMPT = "ماه تولد را انتخاب کنید:"
REG_BIRTH_DAY_PROMPT = "روز تولد را انتخاب کنید:"
REG_ALREADY_TEXT = "اطلاعات شما قبلاً ثبت شده است و می‌توانید از منو استفاده کنید."
REG_CANCELLED = "فرآیند ثبت‌نام لغو شد."
REG_SUCCESS = "ثبت‌نام با موفقیت انجام شد ✅"
INVALID_NID = "کد ملی نامعتبر است."
INVALID_PHONE = "شماره موبایل نامعتبر است."

PATIENT_CONTACT_PLACEHOLDER = "اطلاعات تماس بزودی توسط ادمین در دسترس قرار می‌گیرد."
PATIENT_ADDRESS_PLACEHOLDER = "آدرس و موقعیت مطب بزودی از این بخش اعلام می‌شود."
PATIENT_ONLINE_PLACEHOLDER = "ویزیت آنلاین پس از تکمیل پرداخت فعال خواهد شد."
PATIENT_RECEIPT_TEXT = "برای پیگیری پرداخت، رسید واریز را ارسال کنید تا ادمین بررسی کند."
PATIENT_CONSULT_TEXT = (
    "سؤال پزشکی خود را به‌صورت کوتاه و عمومی ارسال کنید. (توجه: این مشاوره جایگزین پزشک نیست.)"
)


def _is_admin_user(current_user: User | None, telegram_id: int) -> bool:
    if current_user and current_user.role == Role.admin:
        return True
    return telegram_id in settings.admin_ids


def _menu_keyboard(is_admin: bool, current_user: User | None = None):
    if is_admin:
        return admin_menu_inline()
    is_registered = bool(current_user and current_user.phone)
    return main_menu_inline(is_registered=is_registered)


def _registration_markup(previous: str | None = None) -> InlineKeyboardMarkup:
    buttons = []
    if previous:
        buttons.append(InlineKeyboardButton(text=BACK_BUTTON_TEXT, callback_data=f"reg:back:{previous}"))
    buttons.append(InlineKeyboardButton(text=REG_CANCEL, callback_data="reg:cancel"))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def _birth_year_prompt(page: int) -> InlineKeyboardMarkup:
    return birth_year_keyboard(page)


def _birth_month_prompt() -> InlineKeyboardMarkup:
    return birth_month_keyboard()


def _birth_day_prompt(year: int, month: int) -> InlineKeyboardMarkup:
    return birth_day_keyboard(year, month)


def _registration_storage_defaults() -> dict:
    return {"year_page": 0}


def _current_prompt_data(data: dict) -> tuple[int | None, int | None]:
    return data.get("prompt_chat_id"), data.get("prompt_message_id")


async def _set_prompt_reference(state: FSMContext, message: Message) -> None:
    await state.update_data(prompt_chat_id=message.chat.id, prompt_message_id=message.message_id)


async def _edit_prompt(state: FSMContext, bot, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    data = await state.get_data()
    chat_id, message_id = _current_prompt_data(data)
    fallback_chat = data.get("fallback_chat_id")
    if not chat_id or not message_id:
        if fallback_chat:
            sent = await bot.send_message(chat_id=fallback_chat, text=text, reply_markup=markup)
            await _set_prompt_reference(state, sent)
        return
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=markup)
    except TelegramBadRequest:
        sent = await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        await _set_prompt_reference(state, sent)


async def _show_menu_from_state(
    state: FSMContext,
    bot,
    is_admin: bool,
    current_user: User | None = None,
    text: str | None = None,
) -> None:
    data = await state.get_data()
    chat_id, message_id = _current_prompt_data(data)
    keyboard = _menu_keyboard(is_admin, current_user)
    content = text or (ADMIN_MENU_TEXT if is_admin else PATIENT_MENU_TEXT)
    if chat_id and message_id:
        try:
            await bot.edit_message_text(content, chat_id=chat_id, message_id=message_id, reply_markup=keyboard)
        except TelegramBadRequest:
            await bot.send_message(chat_id=chat_id, text=content, reply_markup=keyboard)
    else:
        fallback_chat = data.get("fallback_chat_id") or chat_id
        if fallback_chat:
            await bot.send_message(chat_id=fallback_chat, text=content, reply_markup=keyboard)
    await state.clear()


async def _send_menu_message(message: Message, text: str, markup: InlineKeyboardMarkup) -> None:
    try:
        await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=markup)

async def _load_clinic_profile():
    async with SessionLocal() as session:
        return await get_profile_cached(session)


def _patient_contact_text(profile) -> str:
    lines: list[str] = []
    phone_number = getattr(profile, "phone_number", None)
    phone_label = getattr(profile, "phone_label", None)
    if phone_number:
        label = phone_label or "شماره تماس"
        lines.append(f"{label}: {phone_number}")
    else:
        lines.append("شماره تماس در سامانه ثبت نشده است.")
    address_text = getattr(profile, "address_text", None)
    if address_text:
        lines.append(f"آدرس ثبت‌شده: {address_text}")
    return "\n".join(lines)


def _patient_address_text(profile) -> str:
    address_text = getattr(profile, "address_text", None)
    if address_text:
        return address_text
    return "آدرس مطب هنوز ثبت نشده است."

async def _load_clinic_profile():
    async with SessionLocal() as session:
        return await get_profile(session)


def _phone_is_valid(value: str) -> bool:
    return value.isdigit() and value.startswith("09") and len(value) == 11


async def _store_fallback_chat(state: FSMContext, chat_id: int) -> None:
    await state.update_data(fallback_chat_id=chat_id)


async def _start_registration(message: Message, state: FSMContext, *, edit: bool) -> None:
    data = await state.get_data()
    fallback_chat = data.get("fallback_chat_id")
    await state.clear()
    if fallback_chat:
        await state.update_data(fallback_chat_id=fallback_chat)
    await state.set_state(RegistrationStates.waiting_name)
    await state.update_data(**_registration_storage_defaults())
    markup = _registration_markup()
    if edit:
        try:
            await message.edit_text(REG_NAME_PROMPT, reply_markup=markup)
            await _set_prompt_reference(state, message)
        except TelegramBadRequest:
            sent = await message.answer(REG_NAME_PROMPT, reply_markup=markup)
            await _set_prompt_reference(state, sent)
    else:
        sent = await message.answer(REG_NAME_PROMPT, reply_markup=markup)
        await _set_prompt_reference(state, sent)
    await state.update_data(full_name="")


async def _ensure_user_record(session, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


@router.message(CommandStart())
async def start(m: Message, state: FSMContext, current_user: User | None = None):
    await state.clear()
    await _store_fallback_chat(state, m.chat.id)
    is_admin = _is_admin_user(current_user, m.from_user.id)
    if current_user:
        await _show_menu_from_state(state, m.bot, is_admin, current_user=current_user)
        return
    if is_admin:
        await _show_menu_from_state(
            state,
            m.bot,
            True,
            current_user=current_user,
            text=ADMIN_MENU_TEXT,
        )
        return
    await m.answer(PATIENT_WELCOME)
    await _start_registration(m, state, edit=False)


@router.callback_query(F.data == "menu:register")
async def menu_register(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await _store_fallback_chat(state, c.message.chat.id)
    is_admin = _is_admin_user(current_user, c.from_user.id)
    if is_admin:
        await c.answer("شما ادمین هستید و نیازی به ثبت‌نام ندارید.", show_alert=True)
        return
    async with SessionLocal() as session:
        existing = await session.execute(select(User).where(User.tg_id == c.from_user.id))
        existing_user = existing.scalar_one_or_none()
        if existing_user:
            await state.clear()
            await c.message.edit_text(
                REG_ALREADY_TEXT,
                reply_markup=_menu_keyboard(False, existing_user),
            )
            await c.answer()
            return
    await _start_registration(c.message, state, edit=True)
    await c.answer()


@router.callback_query(F.data == "reg:cancel")
async def reg_cancel(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await state.clear()
    await c.answer("لغو شد")
    is_admin = _is_admin_user(current_user, c.from_user.id)
    await c.message.edit_text(REG_CANCELLED, reply_markup=_menu_keyboard(is_admin, current_user))


@router.callback_query(F.data.startswith("reg:back:"))
async def reg_back(c: CallbackQuery, state: FSMContext):
    target = c.data.split(":", maxsplit=2)[2]
    await c.answer()
    if target == "name":
        await state.set_state(RegistrationStates.waiting_name)
        await _edit_prompt(state, c.bot, REG_NAME_PROMPT, _registration_markup())
    elif target == "nid":
        await state.set_state(RegistrationStates.waiting_national_id)
        await _edit_prompt(state, c.bot, REG_NID_PROMPT, _registration_markup("name"))
    elif target == "year":
        await state.set_state(RegistrationStates.waiting_birth_year)
        data = await state.get_data()
        page = int(data.get("year_page", 0))
        await _edit_prompt(state, c.bot, REG_BIRTH_PROMPT, _birth_year_prompt(page))
    elif target == "month":
        await state.set_state(RegistrationStates.waiting_birth_month)
        await _edit_prompt(state, c.bot, REG_BIRTH_MONTH_PROMPT, _birth_month_prompt())
    elif target == "day":
        await state.set_state(RegistrationStates.waiting_birth_day)
        data = await state.get_data()
        year = data.get("birth_year")
        month = data.get("birth_month")
        if year and month:
            await _edit_prompt(state, c.bot, REG_BIRTH_DAY_PROMPT, _birth_day_prompt(year, month))
        else:
            await reg_cancel(c, state)


@router.message(RegistrationStates.waiting_name)
async def reg_fullname(m: Message, state: FSMContext):
    await state.update_data(full_name=m.text.strip())
    await state.set_state(RegistrationStates.waiting_national_id)
    await _edit_prompt(state, m.bot, REG_NID_PROMPT, _registration_markup("name"))


@router.message(RegistrationStates.waiting_national_id)
async def reg_national_id(m: Message, state: FSMContext):
    code = m.text.strip().replace("-", "")
    if not is_valid_iran_national_id(code):
        await m.answer(INVALID_NID)
        return
    async with SessionLocal() as session:
        existing = await session.execute(select(User).where(User.national_id == code))
        user = existing.scalar_one_or_none()
        if user:
            await state.clear()
            await _show_menu_from_state(
                state,
                m.bot,
                False,
                current_user=user,
                text=REG_ALREADY_TEXT,
            )
            return
    await state.update_data(national_id=code)
    await state.set_state(RegistrationStates.waiting_birth_year)
    await _edit_prompt(state, m.bot, REG_BIRTH_PROMPT, _birth_year_prompt(0))


@router.callback_query(RegistrationStates.waiting_birth_year, F.data.startswith("bdate:"))
async def reg_birth_year(c: CallbackQuery, state: FSMContext):
    parts = c.data.split(":")
    action = parts[1]
    await c.answer()
    if action == "y":
        year = int(parts[2])
        await state.update_data(birth_year=year)
        await state.set_state(RegistrationStates.waiting_birth_month)
        await _edit_prompt(state, c.bot, REG_BIRTH_MONTH_PROMPT, _birth_month_prompt())
    elif action == "y_page":
        page = int(parts[2])
        await state.update_data(year_page=page)
        await _edit_prompt(state, c.bot, REG_BIRTH_PROMPT, _birth_year_prompt(page))
    elif action == "cancel":
        await reg_cancel(c, state)


@router.callback_query(RegistrationStates.waiting_birth_month, F.data.startswith("bdate:"))
async def reg_birth_month(c: CallbackQuery, state: FSMContext):
    parts = c.data.split(":")
    action = parts[1]
    await c.answer()
    data = await state.get_data()
    year = data.get("birth_year")
    if action == "m" and year:
        month = int(parts[2])
        await state.update_data(birth_month=month)
        await state.set_state(RegistrationStates.waiting_birth_day)
        await _edit_prompt(state, c.bot, REG_BIRTH_DAY_PROMPT, _birth_day_prompt(year, month))
    elif action == "back" and parts[2] == "year":
        await state.set_state(RegistrationStates.waiting_birth_year)
        page = int(data.get("year_page", 0))
        await _edit_prompt(state, c.bot, REG_BIRTH_PROMPT, _birth_year_prompt(page))
    elif action == "cancel":
        await reg_cancel(c, state)


@router.callback_query(RegistrationStates.waiting_birth_day, F.data.startswith("bdate:"))
async def reg_birth_day(c: CallbackQuery, state: FSMContext):
    parts = c.data.split(":")
    action = parts[1]
    await c.answer()
    data = await state.get_data()
    year = data.get("birth_year")
    month = data.get("birth_month")
    if action == "d" and year and month:
        day = int(parts[2])
        try:
            JalaliDate(year, month, day)
        except ValueError:
            await c.answer("تاریخ نامعتبر است.", show_alert=True)
            return
        await state.update_data(birth_day=day)
        await state.set_state(RegistrationStates.waiting_phone)
        await _edit_prompt(state, c.bot, REG_PHONE_PROMPT, _registration_markup("day"))
    elif action == "back" and parts[2] == "month":
        await state.set_state(RegistrationStates.waiting_birth_month)
        await _edit_prompt(state, c.bot, REG_BIRTH_MONTH_PROMPT, _birth_month_prompt())
    elif action == "cancel":
        await reg_cancel(c, state)


@router.message(RegistrationStates.waiting_phone)
async def reg_phone(m: Message, state: FSMContext):
    phone = m.text.strip()
    if not _phone_is_valid(phone):
        await m.answer(INVALID_PHONE)
        return
    data = await state.get_data()
    jalali_year = data.get("birth_year")
    jalali_month = data.get("birth_month")
    jalali_day = data.get("birth_day")
    is_admin = m.from_user.id in settings.admin_ids
    async with SessionLocal() as session:
        phone_result = await session.execute(select(User).where(User.phone == phone))
        phone_user = phone_result.scalar_one_or_none()
        if phone_user:
            await state.clear()
            await _show_menu_from_state(
                state,
                m.bot,
                is_admin,
                current_user=phone_user,
                text=REG_ALREADY_TEXT,
            )
            return
        user = await _ensure_user_record(session, m.from_user.id)
        if user:
            user.full_name = data.get("full_name")
            user.national_id = data.get("national_id")
            user.phone = phone
            if jalali_year and jalali_month and jalali_day:
                user.birth_date = JalaliDate(jalali_year, jalali_month, jalali_day).to_gregorian()
            if is_admin and user.role != Role.admin:
                user.role = Role.admin
        else:
            gregorian_date = None
            if jalali_year and jalali_month and jalali_day:
                gregorian_date = JalaliDate(jalali_year, jalali_month, jalali_day).to_gregorian()
            user = User(
                tg_id=m.from_user.id,
                full_name=data.get("full_name"),
                national_id=data.get("national_id"),
                birth_date=gregorian_date,
                phone=phone,
                role=Role.admin if is_admin else Role.patient,
            )
            session.add(user)
        await session.commit()
    await state.clear()
    await _show_menu_from_state(
        state,
        m.bot,
        is_admin,
        current_user=user,
        text=REG_SUCCESS,
    )


@router.callback_query(F.data == "menu:home")
async def menu_home(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await state.clear()
    is_admin = _is_admin_user(current_user, c.from_user.id)
    await _send_menu_message(
        c.message,
        ADMIN_MENU_TEXT if is_admin else PATIENT_MENU_TEXT,
        _menu_keyboard(is_admin, current_user),
    )
    await c.answer()


@router.callback_query(F.data == "menu:book")
async def menu_book(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await c.answer()
    await state.clear()
    is_admin = _is_admin_user(current_user, c.from_user.id)
    await _send_menu_message(
        c.message,
        "برای رزرو نوبت از منوی تاریخ استفاده کنید.",
        _menu_keyboard(is_admin, current_user),
    )


@router.callback_query(F.data == "menu:contact")
async def menu_contact(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await c.answer()
    await state.clear()
    is_admin = _is_admin_user(current_user, c.from_user.id)
    profile = await _load_clinic_profile()
    text = _patient_contact_text(profile)
    await _send_menu_message(c.message, text, _menu_keyboard(is_admin, current_user))


@router.callback_query(F.data == "menu:address")
async def menu_address(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await c.answer()
    await state.clear()
    is_admin = _is_admin_user(current_user, c.from_user.id)
    profile = await _load_clinic_profile()
    text = _patient_address_text(profile)
    await _send_menu_message(c.message, text, _menu_keyboard(is_admin, current_user))
    if getattr(profile, "location_lat", None) is not None and getattr(profile, "location_lon", None) is not None:
        await c.message.bot.send_location(
            chat_id=c.message.chat.id,
            latitude=profile.location_lat,
            longitude=profile.location_lon,
        )


@router.callback_query(F.data == "menu:online")
async def menu_online(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await c.answer()
    await state.clear()
    is_admin = _is_admin_user(current_user, c.from_user.id)
    await _send_menu_message(c.message, PATIENT_ONLINE_PLACEHOLDER, _menu_keyboard(is_admin, current_user))


@router.callback_query(F.data == "menu:receipt")
async def menu_receipt(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await c.answer()
    await state.clear()
    is_admin = _is_admin_user(current_user, c.from_user.id)
    await _send_menu_message(c.message, PATIENT_RECEIPT_TEXT, _menu_keyboard(is_admin, current_user))


@router.callback_query(F.data == "menu:consult")
async def menu_consult(c: CallbackQuery, state: FSMContext, current_user: User | None = None):
    await c.answer()
    await state.clear()
    is_admin = _is_admin_user(current_user, c.from_user.id)
    await _send_menu_message(c.message, PATIENT_CONSULT_TEXT, _menu_keyboard(is_admin, current_user))


@router.message(F.text == "مشاوره هوشمند")
async def smart_consult(m: Message):
    await m.answer(PATIENT_CONSULT_TEXT)
