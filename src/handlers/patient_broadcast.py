# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Sequence

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.config import settings
from src.keyboards import CANCEL_TEXT
from src.services.patient_broadcast import (
    SEND_DELAY_SECONDS,
    chunk_text,
    db_find_patient_candidates,
    db_get_active_patient_ids,
    db_get_last_appointments_for,
    db_get_patients_by_ids,
    render_patient_template,
)

router = Router(name="patient_broadcast")

CANCEL_WORD = "لغو"
SAMPLE_LIMIT = 3


class PatientBcastStates(StatesGroup):
    picking_audience = State()
    searching_patient = State()
    composing_text = State()
    confirming = State()


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


def _cancel_requested(message: Message) -> bool:
    text = (message.text or "").strip()
    return text == CANCEL_WORD or text == CANCEL_TEXT


def _audience_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👥 همهٔ بیماران", callback_data="pbcast:aud:all"),
                InlineKeyboardButton(text="👤 یک بیمار", callback_data="pbcast:aud:one"),
            ],
            [InlineKeyboardButton(text="❌ لغو", callback_data="pbcast:cancel")],
        ]
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تأیید و ارسال", callback_data="pbcast:confirm"),
                InlineKeyboardButton(text="✏️ اصلاح متن", callback_data="pbcast:edit"),
            ],
            [InlineKeyboardButton(text="❌ لغو", callback_data="pbcast:cancel")],
        ]
    )


async def _ensure_admin(cb: CallbackQuery | Message) -> bool:
    user_id = cb.from_user.id if isinstance(cb, CallbackQuery) else cb.from_user.id
    if not _is_admin(user_id):
        text = "⛔️ فقط ادمین اجازهٔ دسترسی دارد."
        if isinstance(cb, CallbackQuery):
            await cb.answer(text, show_alert=True)
        else:
            await cb.answer(text)
        return False
    return True


@router.callback_query(F.data == "pbcast:start")
async def broadcast_entry(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(callback):
        return
    await state.clear()
    await state.set_state(PatientBcastStates.picking_audience)
    if callback.message:
        await callback.message.answer(
            "ارسال پیام بیماران فعال شد.\nگیرنده را انتخاب کنید:",
            reply_markup=_audience_keyboard(),
        )
    await callback.answer()


@router.callback_query(StateFilter(PatientBcastStates.picking_audience), F.data == "pbcast:cancel")
async def broadcast_cancel_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.answer("لغو شد.")
    await callback.answer()


@router.callback_query(StateFilter(PatientBcastStates.picking_audience), F.data == "pbcast:aud:all")
async def broadcast_pick_all(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(callback):
        return
    ids = await db_get_active_patient_ids()
    audience = [pid for pid in ids if isinstance(pid, int)]
    if not audience:
        if callback.message:
            await callback.message.answer("بیمار فعالی یافت نشد. ابتدا بیماران را ثبت‌نام کنید.")
        await callback.answer()
        return
    await state.update_data(audience_type="ALL", audience_ids=audience)
    await state.set_state(PatientBcastStates.composing_text)
    count = len(audience)
    if callback.message:
        await callback.message.answer(
            f"ارسال پیام همگانی فعال شد. تعداد دریافت‌کنندگان: {count} نفر.\n"
            "متن پیام را وارد کنید.\n"
            "می‌توانید از متغیرهای زیر استفاده کنید:\n"
            "{name} {phone} {national_id} {date} {time} {appointment_id} {status}\n"
            "مثال: سلام {name}! نوبت شما در تاریخ {date} ساعت {time} برگزار می‌شود.\n"
            "برای لغو «لغو» را ارسال کنید.",
        )
    await callback.answer()


@router.callback_query(StateFilter(PatientBcastStates.picking_audience), F.data == "pbcast:aud:one")
async def broadcast_pick_one(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(callback):
        return
    await state.update_data(audience_type="ONE", audience_ids=[])
    await state.set_state(PatientBcastStates.searching_patient)
    if callback.message:
        await callback.message.answer(
            "کد ملی، شماره تماس، یا بخشی از نام بیمار را ارسال کنید.\n"
            "برای لغو «لغو» را ارسال کنید."
        )
    await callback.answer()


@router.message(StateFilter(PatientBcastStates.searching_patient), F.text)
async def broadcast_search_patient(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔️ فقط ادمین اجازهٔ دسترسی دارد.")
        return
    if _cancel_requested(message):
        await state.clear()
        await message.answer("لغو شد.")
        return
    candidates = await db_find_patient_candidates(message.text.strip(), limit=5)
    if not candidates:
        await message.answer("بیماری یافت نشد. دوباره تلاش کنید یا «لغو» را ارسال کنید.")
        return
    keyboard_rows = []
    for candidate in candidates:
        label = f"{candidate.get('name', '-')}\nکد ملی: {candidate.get('national_id', '-')}\nتلفن: {candidate.get('phone', '-')}"
        keyboard_rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"pbcast:pick:{candidate['id']}")]
        )
    keyboard_rows.append([InlineKeyboardButton(text="❌ لغو", callback_data="pbcast:cancel")])
    await state.update_data(candidate_ids=[c["id"] for c in candidates])
    await message.answer(
        "نتایج جستجو:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
    )


@router.callback_query(StateFilter(PatientBcastStates.searching_patient), F.data.startswith("pbcast:pick:"))
async def broadcast_pick_patient(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(callback):
        return
    patient_id_str = callback.data.split(":", 2)[-1]
    try:
        patient_id = int(patient_id_str)
    except ValueError:
        await callback.answer("شناسهٔ نامعتبر.", show_alert=True)
        return
    data = await state.get_data()
    candidates = data.get("candidate_ids") or []
    if patient_id not in candidates:
        await callback.answer("ابتدا بیمار را جستجو کنید.", show_alert=True)
        return
    await state.update_data(audience_ids=[patient_id])
    await state.set_state(PatientBcastStates.composing_text)
    if callback.message:
        await callback.message.answer(
            "متن پیام را وارد کنید.\n"
            "متغیرهای موجود: {name} {phone} {national_id} {date} {time} {appointment_id} {status}\n"
            "برای لغو «لغو» را ارسال کنید."
        )
    await callback.answer()


@router.callback_query(
    StateFilter(PatientBcastStates.searching_patient, PatientBcastStates.composing_text, PatientBcastStates.confirming),
    F.data == "pbcast:cancel",
)
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if callback.message:
        await callback.message.answer("لغو شد.")
    await callback.answer()


@router.message(StateFilter(PatientBcastStates.composing_text), F.text)
async def broadcast_compose(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("⛔️ فقط ادمین اجازهٔ دسترسی دارد.")
        return
    if _cancel_requested(message):
        await state.clear()
        await message.answer("لغو شد.")
        return
    template = (message.text or "").strip()
    data = await state.get_data()
    audience_ids: List[int] = data.get("audience_ids") or []
    audience_type = data.get("audience_type", "ONE")
    if not audience_ids:
        await message.answer("هنوز بیماری انتخاب نشده است. ابتدا گیرنده را مشخص کنید.")
        await state.set_state(PatientBcastStates.picking_audience)
        return
    await state.update_data(template=template)
    await state.set_state(PatientBcastStates.confirming)
    preview = await _build_preview(audience_ids, template, audience_type)
    await message.answer(preview, reply_markup=_confirm_keyboard())


@router.callback_query(StateFilter(PatientBcastStates.confirming), F.data == "pbcast:edit")
async def broadcast_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PatientBcastStates.composing_text)
    if callback.message:
        await callback.message.answer("متن جدید را ارسال کنید. برای لغو «لغو» را ارسال کنید.")
    await callback.answer()


@router.message(StateFilter(PatientBcastStates.confirming), F.text)
async def broadcast_confirm_text(message: Message, state: FSMContext) -> None:
    if _cancel_requested(message):
        await state.clear()
        await message.answer("لغو شد.")
        return
    await message.answer("برای تایید از دکمه‌های پایین استفاده کنید یا «لغو» را ارسال کنید.")

@router.callback_query(StateFilter(PatientBcastStates.confirming), F.data == "pbcast:confirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(callback):
        return
    data = await state.get_data()
    template: str = data.get("template", "")
    audience_ids: List[int] = data.get("audience_ids") or []
    audience_type = data.get("audience_type", "ONE")
    if not template or not audience_ids:
        if callback.message:
            await callback.message.answer("داده‌های لازم یافت نشد. لطفاً دوباره تلاش کنید.")
        await state.clear()
        await callback.answer()
        return
    patients = await db_get_patients_by_ids(audience_ids)
    last_appts = await db_get_last_appointments_for(audience_ids)
    sent = 0
    failed = 0
    total = len(audience_ids)
    for pid in audience_ids:
        record = patients.get(pid)
        if not record or not record.get("tg_id"):
            failed += 1
            continue
        text = render_patient_template(template, record, last_appts.get(pid))
        try:
            for chunk in chunk_text(text):
                await callback.bot.send_message(chat_id=record["tg_id"], text=chunk)
                await asyncio.sleep(SEND_DELAY_SECONDS)
            sent += 1
        except Exception:
            failed += 1
            continue
    if callback.message:
        callback_text = (
            "ارسال پیام همگانی تمام شد.\n"
            f"✅ ارسال موفق: {sent}\n"
            f"❌ ناموفق: {failed}\n"
            f"👥 کل مخاطبان: {total}"
        )
        await callback.message.edit_text(callback_text)
    await state.clear()
    await callback.answer()


async def _build_preview(audience_ids: Sequence[int], template: str, audience_type: str) -> str:
    sample_ids = list(audience_ids[:SAMPLE_LIMIT] if audience_type == "ALL" else audience_ids[:1])
    patients = await db_get_patients_by_ids(sample_ids)
    last_appts = await db_get_last_appointments_for(sample_ids)
    previews: List[str] = []
    for idx, pid in enumerate(sample_ids, start=1):
        patient = patients.get(pid)
        if not patient:
            continue
        rendered = render_patient_template(template, patient, last_appts.get(pid))
        previews.append(f"{idx}) {rendered}")
    preview_body = "\n---\n".join(previews) if previews else "پیش‌نمایش در دسترس نیست."
    return f"پیش‌نمایش پیام:\n{preview_body}\n\nتأیید می‌کنید؟"

