# -*- coding: utf-8 -*-
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from feature_broadcast_aiogram_plugin_fixed import register_user_from_message
from src.config import settings
from src.keyboards import (
    REGISTER_TEXT,
    SMART_ASSIST_TEXT,
    admin_menu_inline,
    main_menu_inline,
)
from src.models import Role, User

router = Router(name="common")

PATIENT_WELCOME = (
    "سلام! به ربات کلینیک خوش آمدید. برای استفاده از خدمات، از منوی زیر گزینهٔ موردنظر را انتخاب کنید."
)
PATIENT_MENU_TEXT = "برای شروع می‌توانید «ثبت‌نام» را انتخاب کنید یا سایر گزینه‌ها را مشاهده کنید."
ADMIN_MENU_TEXT = "منوی مدیریت فعال است. لطفاً گزینهٔ موردنظر را انتخاب کنید."
SMART_ASSIST_REPLY = (
    "قابلیت مشاورهٔ هوشمند به‌زودی فعال می‌شود. لطفاً موقتاً از گزینه‌های دیگر استفاده کنید."
)


def _is_admin_user(current_user: User | None, telegram_id: int) -> bool:
    if current_user and current_user.role == Role.admin:
        return True
    return telegram_id in settings.admin_ids


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, current_user: User | None = None) -> None:
    await state.clear()
    await register_user_from_message(message)

    is_admin = _is_admin_user(current_user, message.from_user.id)
    reply_markup = admin_menu_inline() if is_admin else main_menu_inline(
        is_registered=bool(current_user and current_user.phone)
    )

    if is_admin:
        await message.answer(ADMIN_MENU_TEXT, reply_markup=reply_markup)
    else:
        body = f"{PATIENT_WELCOME}\n\n{PATIENT_MENU_TEXT}"
        await message.answer(body, reply_markup=reply_markup)


@router.message(StateFilter(None), F.text == SMART_ASSIST_TEXT)
async def smart_assist_placeholder(message: Message) -> None:
    await message.answer(SMART_ASSIST_REPLY)
