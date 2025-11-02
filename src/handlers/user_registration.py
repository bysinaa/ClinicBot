# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from persiantools.jdatetime import JalaliDate

from src.config import settings
from src.keyboards import (
    CANCEL_TEXT,
    REGISTER_TEXT,
    birth_day_keyboard,
    birth_month_keyboard,
    birth_year_keyboard,
    main_menu_inline,
)
from src.models import Role, User
from src.services.patient_registration import (
    db_find_patient_by_national_id,
    db_upsert_patient,
)
from src.utils.validation import (
    is_valid_national_id,
    normalize_phone,
    to_english_digits,
)

router = Router(name="user_registration")

CANCEL_WORDS = {"لغو", "لغو.", "لغو!", "cancel", "Cancel"}


class PatientRegStates(StatesGroup):
    ask_name = State()
    ask_national_id = State()
    confirm_update = State()
    ask_phone = State()
    optional_menu = State()
    ask_birth_year = State()
    ask_birth_month = State()
    ask_birth_day = State()
    ask_insurance = State()
    ask_address = State()
    confirm = State()


OPTIONAL_MENU_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="📅 تاریخ تولد", callback_data="ureg:opt_birthdate")],
        [InlineKeyboardButton(text="⚧ جنسیت", callback_data="ureg:opt_gender")],
        [InlineKeyboardButton(text="🏥 بیمه", callback_data="ureg:opt_insurance")],
        [InlineKeyboardButton(text="📍 آدرس", callback_data="ureg:opt_address")],
        [InlineKeyboardButton(text="⏭ ادامه و تأیید", callback_data="ureg:opt_skip")],
        [InlineKeyboardButton(text=CANCEL_TEXT, callback_data="ureg:cancel")],
    ]
)

CANCEL_ONLY_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text=CANCEL_TEXT, callback_data="ureg:cancel")]]
)

UPDATE_CHOICE_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✅ بله، بروزرسانی شود", callback_data="ureg:update_yes")],
        [InlineKeyboardButton(text="↩️ ورود کد ملی دیگر", callback_data="ureg:update_no")],
        [InlineKeyboardButton(text=CANCEL_TEXT, callback_data="ureg:cancel")],
    ]
)

GENDER_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="👨 مرد", callback_data="ureg:gender_m"),
            InlineKeyboardButton(text="👩 زن", callback_data="ureg:gender_f"),
        ],
        [InlineKeyboardButton(text="⚪️ ترجیح می‌دهم نگویم", callback_data="ureg:gender_u")],
        [InlineKeyboardButton(text="↩️ بازگشت", callback_data="ureg:opt_back")],
    ]
)

CONFIRM_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأیید نهایی", callback_data="ureg:confirm")],
        [InlineKeyboardButton(text="✏️ ویرایش اطلاعات", callback_data="ureg:edit")],
        [InlineKeyboardButton(text=CANCEL_TEXT, callback_data="ureg:cancel")],
    ]
)

_GENDER_LABELS = {
    "male": "مرد",
    "female": "زن",
    "unknown": "نامشخص",
    None: "نامشخص",
}


def _user_is_admin(user: Optional[User], telegram_id: int) -> bool:
    if user and user.role == Role.admin:
        return True
    return telegram_id in settings.admin_ids


async def _ensure_reg_data(state: FSMContext, *, tg_id: int) -> Dict[str, Any]:
    data = await state.get_data()
    reg = data.get("reg")
    if not reg:
        reg = {
            "tg_id": tg_id,
            "name": None,
            "national_id": None,
            "phone": None,
            "birthdate": None,
            "gender": None,
            "insurance": None,
            "address": None,
            "update_existing": False,
            "existing_id": None,
            "pending_update": None,
            "birth_selection": {},
        }
        await state.update_data(reg=reg)
    return reg


async def _set_reg_values(state: FSMContext, **values: Any) -> None:
    data = await state.get_data()
    reg = data.get("reg") or {}
    reg.update(values)
    await state.update_data(reg=reg)


def _format_summary(reg: Dict[str, Any]) -> str:
    birthdate = reg.get("birthdate")
    gender = reg.get("gender")
    insurance = reg.get("insurance")
    address = reg.get("address")
    jalali_birth = "-"
    if isinstance(birthdate, date):
        jalali = JalaliDate.to_jalali(birthdate)
        jalali_birth = f"{jalali.year:04}-{jalali.month:02}-{jalali.day:02}"
    return (
        "لطفاً اطلاعات زیر را تأیید کنید:\n"
        f"• نام و نام خانوادگی: {reg.get('name') or '-'}\n"
        f"• کد ملی: {reg.get('national_id') or '-'}\n"
        f"• شماره تماس: {reg.get('phone') or '-'}\n"
        f"• تاریخ تولد: {jalali_birth}\n"
        f"• جنسیت: {_GENDER_LABELS.get(gender, 'نامشخص')}\n"
        f"• بیمه: {insurance or '-'}\n"
        f"• آدرس: {address or '-'}"
    )


async def _show_main_menu(message: Message, *, is_registered: bool) -> None:
    await message.answer(
        "به منوی اصلی بازگشتید.",
        reply_markup=main_menu_inline(is_registered=is_registered),
    )


async def _cancel_flow(
    message: Message,
    state: FSMContext,
    *,
    current_user: Optional[User] = None,
    reason: str | None = None,
) -> None:
    data = await state.get_data()
    reg = data.get("reg") or {}
    is_registered = bool(
        (current_user and current_user.role == Role.patient)
        or reg.get("existing_id")
        or reg.get("update_existing")
    )
    await state.clear()
    text = reason or "فرآیند ثبت‌نام لغو شد."
    await message.answer(text, reply_markup=main_menu_inline(is_registered=is_registered))


@router.callback_query(StateFilter(None), F.data == "patient:register")
async def start_registration_from_callback(callback: CallbackQuery, state: FSMContext, current_user: Optional[User]) -> None:
    if _user_is_admin(current_user, callback.from_user.id):
        await callback.answer("مدیر نیاز به ثبت‌نام ندارد.", show_alert=True)
        return
    await callback.answer()
    await _ensure_reg_data(state, tg_id=callback.from_user.id)
    await state.set_state(PatientRegStates.ask_name)
    await callback.message.edit_text(
        "برای ثبت‌نام چند سؤال ساده می‌پرسیم.\n"
        "در هر مرحله می‌توانید با دکمه «لغو» فرآیند را متوقف کنید.\n"
        "لطفاً نام و نام خانوادگی را وارد کنید.",
        reply_markup=CANCEL_ONLY_KEYBOARD,
    )


@router.message(StateFilter(None), F.text == REGISTER_TEXT)
async def start_registration_from_message(message: Message, state: FSMContext, current_user: Optional[User]) -> None:
    if _user_is_admin(current_user, message.from_user.id):
        await message.answer("مدیر نیاز به ثبت‌نام ندارد.", reply_markup=main_menu_inline(is_registered=True))
        return
    await _ensure_reg_data(state, tg_id=message.from_user.id)
    await state.set_state(PatientRegStates.ask_name)
    await message.answer(
        "برای ثبت‌نام چند سؤال ساده می‌پرسیم.\n"
        "در هر مرحله می‌توانید با دکمه «لغو» فرآیند را متوقف کنید.\n"
        "لطفاً نام و نام خانوادگی را وارد کنید.",
        reply_markup=CANCEL_ONLY_KEYBOARD,
    )


@router.callback_query(F.data == "ureg:cancel")
async def registration_cancel(callback: CallbackQuery, state: FSMContext, current_user: Optional[User]) -> None:
    await callback.answer()
    await _cancel_flow(callback.message, state, current_user=current_user, reason="فرآیند ثبت‌نام لغو شد.")


@router.message(StateFilter(PatientRegStates.ask_name), F.text)
async def handle_name(message: Message, state: FSMContext, current_user: Optional[User]) -> None:
    text = (message.text or "").strip()
    if text in CANCEL_WORDS:
        await _cancel_flow(message, state, current_user=current_user)
        return
    name = text
    if len(name) < 3 or len(name) > 60:
        await message.answer(
            "⚠️ نام واردشده معتبر نیست. لطفاً نام و نام خانوادگی واقعی (۳ تا ۶۰ کاراکتر) را وارد کنید.",
            reply_markup=CANCEL_ONLY_KEYBOARD,
        )
        return
    await _set_reg_values(state, name=name)
    await state.set_state(PatientRegStates.ask_national_id)
    await message.answer(
        "کد ملی ۱۰ رقمی را وارد کنید.",
        reply_markup=CANCEL_ONLY_KEYBOARD,
    )


@router.message(StateFilter(PatientRegStates.ask_national_id), F.text)
async def handle_national_id(message: Message, state: FSMContext, current_user: Optional[User]) -> None:
    text = (message.text or "").strip()
    if text in CANCEL_WORDS:
        await _cancel_flow(message, state, current_user=current_user)
        return
    raw_code = text
    digits = to_english_digits(raw_code)
    if not is_valid_national_id(digits):
        await message.answer(
            "⚠️ کد ملی واردشده معتبر نیست. لطفاً دوباره تلاش کنید.",
            reply_markup=CANCEL_ONLY_KEYBOARD,
        )
        return
    await _set_reg_values(state, national_id=digits)
    existing = await db_find_patient_by_national_id(digits)
    if existing:
        await _set_reg_values(state, pending_update=existing)
        await state.set_state(PatientRegStates.confirm_update)
        await message.answer(
            "برای این کد ملی مشخصات دیگری ثبت شده است. آیا می‌خواهید اطلاعات قبلی بروزرسانی شود؟",
            reply_markup=UPDATE_CHOICE_KEYBOARD,
        )
        return

    await _set_reg_values(state, update_existing=False, existing_id=None, pending_update=None)
    await state.set_state(PatientRegStates.ask_phone)
    await message.answer(
        "شماره تماس را وارد کنید (مثال: 09123456789 یا +989123456789).",
        reply_markup=CANCEL_ONLY_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.confirm_update), F.data == "ureg:update_yes")
async def handle_update_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    reg = await _ensure_reg_data(state, tg_id=callback.from_user.id)
    existing = reg.get("pending_update") or {}
    await _set_reg_values(
        state,
        update_existing=True,
        existing_id=existing.get("id"),
        phone=existing.get("phone") or reg.get("phone"),
        birthdate=existing.get("birthdate") or reg.get("birthdate"),
        gender=existing.get("gender") or reg.get("gender"),
        insurance=existing.get("insurance") or reg.get("insurance"),
        address=existing.get("address") or reg.get("address"),
    )
    await state.set_state(PatientRegStates.ask_phone)
    await callback.message.edit_text(
        "شماره تماس را وارد کنید (مثال: 09123456789 یا +989123456789).",
        reply_markup=CANCEL_ONLY_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.confirm_update), F.data == "ureg:update_no")
async def handle_update_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PatientRegStates.ask_national_id)
    await callback.message.edit_text(
        "کد ملی ۱۰ رقمی دیگری وارد کنید.",
        reply_markup=CANCEL_ONLY_KEYBOARD,
    )


@router.message(StateFilter(PatientRegStates.ask_phone), F.text)
async def handle_phone(message: Message, state: FSMContext, current_user: Optional[User]) -> None:
    text = (message.text or "").strip()
    if text in CANCEL_WORDS:
        await _cancel_flow(message, state, current_user=current_user)
        return
    phone = normalize_phone(text)
    if not phone:
        await message.answer(
            "⚠️ شماره تماس معتبر نیست. مثال: 09123456789 یا +989123456789",
            reply_markup=CANCEL_ONLY_KEYBOARD,
        )
        return
    await _set_reg_values(state, phone=phone)
    await state.set_state(PatientRegStates.optional_menu)
    await message.answer(
        "عالی! می‌توانید اطلاعات تکمیلی را نیز ثبت کنید یا مستقیماً ادامه دهید.",
        reply_markup=OPTIONAL_MENU_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.optional_menu), F.data == "ureg:opt_birthdate")
async def optional_birthdate(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    reg = await _ensure_reg_data(state, tg_id=callback.from_user.id)
    reg["birth_selection"] = {}
    await state.update_data(reg=reg)
    await state.set_state(PatientRegStates.ask_birth_year)
    await callback.message.edit_text(
        "سال تولد را انتخاب کنید.",
        reply_markup=birth_year_keyboard(page=0),
    )


@router.callback_query(StateFilter(PatientRegStates.ask_birth_year), F.data.startswith("bdate:y_page:"))
async def birth_year_page(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    page = int(callback.data.split(":")[-1])
    await callback.message.edit_text(
        "سال تولد را انتخاب کنید.",
        reply_markup=birth_year_keyboard(page=page),
    )


@router.callback_query(StateFilter(PatientRegStates.ask_birth_year), F.data.startswith("bdate:y:"))
async def birth_year_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    year = int(callback.data.split(":")[-1])
    reg = await _ensure_reg_data(state, tg_id=callback.from_user.id)
    reg["birth_selection"] = {"year": year}
    await state.update_data(reg=reg)
    await state.set_state(PatientRegStates.ask_birth_month)
    await callback.message.edit_text(
        "اکنون ماه تولد را انتخاب کنید.",
        reply_markup=birth_month_keyboard(),
    )


@router.callback_query(StateFilter(PatientRegStates.ask_birth_month), F.data == "bdate:back:year")
async def birth_month_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PatientRegStates.ask_birth_year)
    await callback.message.edit_text(
        "سال تولد را انتخاب کنید.",
        reply_markup=birth_year_keyboard(page=0),
    )


@router.callback_query(StateFilter(PatientRegStates.ask_birth_month), F.data.startswith("bdate:m:"))
async def birth_month_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    month = int(callback.data.split(":")[-1])
    reg = await _ensure_reg_data(state, tg_id=callback.from_user.id)
    selection = reg.get("birth_selection") or {}
    selection["month"] = month
    reg["birth_selection"] = selection
    await state.update_data(reg=reg)
    year = selection.get("year")
    await state.set_state(PatientRegStates.ask_birth_day)
    await callback.message.edit_text(
        "روز تولد را انتخاب کنید.",
        reply_markup=birth_day_keyboard(year=year, month=month),
    )


@router.callback_query(StateFilter(PatientRegStates.ask_birth_day), F.data == "bdate:back:month")
async def birth_day_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PatientRegStates.ask_birth_month)
    await callback.message.edit_text(
        "ماه تولد را انتخاب کنید.",
        reply_markup=birth_month_keyboard(),
    )


@router.callback_query(
    StateFilter(PatientRegStates.ask_birth_year, PatientRegStates.ask_birth_month, PatientRegStates.ask_birth_day),
    F.data == "bdate:cancel",
)
async def birthdate_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    reg = await _ensure_reg_data(state, tg_id=callback.from_user.id)
    reg["birth_selection"] = {}
    await state.update_data(reg=reg)
    await state.set_state(PatientRegStates.optional_menu)
    await callback.message.edit_text(
        "انتخاب تاریخ تولد لغو شد. گزینه دیگری را انتخاب کنید یا ادامه دهید.",
        reply_markup=OPTIONAL_MENU_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.ask_birth_day), F.data.startswith("bdate:d:"))
async def birth_day_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    day = int(callback.data.split(":")[-1])
    reg = await _ensure_reg_data(state, tg_id=callback.from_user.id)
    selection = reg.get("birth_selection") or {}
    year = selection.get("year")
    month = selection.get("month")
    if not year or not month:
        await state.set_state(PatientRegStates.ask_birth_year)
        await callback.message.edit_text("سال تولد را انتخاب کنید.", reply_markup=birth_year_keyboard(page=0))
        return
    jalali_date = JalaliDate(year, month, day)
    gregorian = jalali_date.to_gregorian()
    await _set_reg_values(state, birthdate=gregorian, birth_selection={})
    await state.set_state(PatientRegStates.optional_menu)
    await callback.message.edit_text(
        f"تاریخ تولد ذخیره شد: {jalali_date.year:04}-{jalali_date.month:02}-{jalali_date.day:02}\n"
        "گزینه دیگری را انتخاب کنید یا ادامه دهید.",
        reply_markup=OPTIONAL_MENU_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.optional_menu), F.data == "ureg:opt_gender")
async def optional_gender(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.edit_text("جنسیت را انتخاب کنید.", reply_markup=GENDER_KEYBOARD)


@router.callback_query(StateFilter(PatientRegStates.optional_menu), F.data == "ureg:opt_insurance")
async def optional_insurance(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PatientRegStates.ask_insurance)
    await callback.message.edit_text(
        "نام بیمه یا توضیح کوتاهی وارد کنید.",
        reply_markup=CANCEL_ONLY_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.optional_menu), F.data == "ureg:opt_address")
async def optional_address(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PatientRegStates.ask_address)
    await callback.message.edit_text(
        "آدرس کامل خود را وارد کنید.",
        reply_markup=CANCEL_ONLY_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.optional_menu), F.data == "ureg:opt_skip")
async def optional_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    reg = await _ensure_reg_data(state, tg_id=callback.from_user.id)
    await state.set_state(PatientRegStates.confirm)
    await callback.message.edit_text(_format_summary(reg), reply_markup=CONFIRM_KEYBOARD)


@router.callback_query(
    StateFilter(PatientRegStates.optional_menu, PatientRegStates.ask_insurance, PatientRegStates.ask_address),
    F.data == "ureg:opt_back",
)
async def optional_back(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PatientRegStates.optional_menu)
    await callback.message.edit_text(
        "گزینه دیگری را انتخاب کنید یا ادامه دهید.",
        reply_markup=OPTIONAL_MENU_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.optional_menu), F.data.startswith("ureg:gender_"))
async def gender_selected(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    gender_map = {"ureg:gender_m": "male", "ureg:gender_f": "female", "ureg:gender_u": "unknown"}
    gender = gender_map.get(callback.data)
    if gender is None:
        await callback.answer("گزینه نامعتبر.", show_alert=True)
        return
    await _set_reg_values(state, gender=gender)
    await state.set_state(PatientRegStates.optional_menu)
    await callback.message.edit_text(
        "جنسیت ذخیره شد. گزینه دیگری را انتخاب کنید یا ادامه دهید.",
        reply_markup=OPTIONAL_MENU_KEYBOARD,
    )


@router.message(StateFilter(PatientRegStates.ask_insurance), F.text)
async def handle_insurance(message: Message, state: FSMContext, current_user: Optional[User]) -> None:
    text = (message.text or "").strip()
    if text in CANCEL_WORDS:
        await _cancel_flow(message, state, current_user=current_user)
        return
    insurance = to_english_digits(text).strip()
    await _set_reg_values(state, insurance=insurance or None)
    await state.set_state(PatientRegStates.optional_menu)
    await message.answer(
        "اطلاعات بیمه ثبت شد. گزینه دیگری را انتخاب کنید یا ادامه دهید.",
        reply_markup=OPTIONAL_MENU_KEYBOARD,
    )


@router.message(StateFilter(PatientRegStates.ask_address), F.text)
async def handle_address(message: Message, state: FSMContext, current_user: Optional[User]) -> None:
    text = (message.text or "").strip()
    if text in CANCEL_WORDS:
        await _cancel_flow(message, state, current_user=current_user)
        return
    address = to_english_digits(text).strip()
    await _set_reg_values(state, address=address or None)
    await state.set_state(PatientRegStates.optional_menu)
    await message.answer(
        "آدرس ثبت شد. گزینه دیگری را انتخاب کنید یا ادامه دهید.",
        reply_markup=OPTIONAL_MENU_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.confirm), F.data == "ureg:edit")
async def confirm_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PatientRegStates.optional_menu)
    await callback.message.edit_text(
        "گزینه‌ای را برای ویرایش انتخاب کنید.",
        reply_markup=OPTIONAL_MENU_KEYBOARD,
    )


@router.callback_query(StateFilter(PatientRegStates.confirm), F.data == "ureg:confirm")
async def confirm_submit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    reg = await _ensure_reg_data(state, tg_id=callback.from_user.id)
    payload = {
        "tg_id": callback.from_user.id,
        "name": reg.get("name"),
        "national_id": reg.get("national_id"),
        "phone": reg.get("phone"),
        "birthdate": reg.get("birthdate"),
        "gender": reg.get("gender"),
        "insurance": reg.get("insurance"),
        "address": reg.get("address"),
        "existing_id": reg.get("existing_id"),
        "pending_update": None,
    }
    await db_upsert_patient(payload, update_existing=bool(reg.get("update_existing")))
    await state.clear()
    await callback.message.edit_text(
        "✅ ثبت‌نام با موفقیت انجام شد.",
        reply_markup=main_menu_inline(is_registered=True),
    )


@router.message(StateFilter(PatientRegStates.ask_name, PatientRegStates.ask_national_id, PatientRegStates.ask_phone), F.text == "")
async def ignore_empty(message: Message) -> None:
    await message.answer("متنی دریافت نشد. لطفاً دوباره تلاش کنید.", reply_markup=CANCEL_ONLY_KEYBOARD)
