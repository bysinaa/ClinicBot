# -*- coding: utf-8 -*-
"""Broadcast helper plugin for aiogram v3 with robust FSM routing."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable, List, Optional

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

DB_PATH = Path("subscribers.db")
SEND_DELAY_SECONDS: float = 0.05


def _ensure_db_path(path: Path | str) -> Path:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _init_db() -> None:
    path = _ensure_db_path(DB_PATH)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY
            )
            """
        )
        conn.commit()


def add_user(chat_id: int) -> None:
    path = _ensure_db_path(DB_PATH)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
        conn.commit()


def get_all_users() -> List[int]:
    path = _ensure_db_path(DB_PATH)
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute("SELECT chat_id FROM users").fetchall()
    return [row[0] for row in rows]


def users_count() -> int:
    path = _ensure_db_path(DB_PATH)
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    return int(row[0]) if row else 0


def chunk_text(text: str, limit: int = 4096) -> List[str]:
    if not text:
        return [""]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


async def register_user_from_message(message: Message) -> None:
    if message.chat:
        add_user(message.chat.id)


def get_broadcast_admin_button(
    *,
    text: str = "📢 پیام همگانی",
    callback_data: str = "admin:broadcast",
) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_confirmation = State()


def build_broadcast_router(
    *,
    is_admin_func: Callable[[int], bool],
    db_path: Optional[Path | str] = None,
    send_delay_seconds: Optional[float] = None,
    enable_stats_command: bool = True,
    stats_command_name: str = "stats",
    broadcast_command_name: str = "broadcast",
    admin_broadcast_callback_data: str = "admin:broadcast",
) -> Router:
    router = Router(name="broadcast")

    global DB_PATH, SEND_DELAY_SECONDS
    if db_path is not None:
        DB_PATH = Path(db_path)
    if send_delay_seconds is not None:
        SEND_DELAY_SECONDS = float(send_delay_seconds)

    _init_db()

    @router.message(Command(broadcast_command_name))
    async def broadcast_entry_command(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin_func(message.from_user.id):
            await message.answer("⛔️ فقط ادمین می‌تواند پیام همگانی ارسال کند.")
            return
        print(f"[broadcast] entry command from admin: {message.from_user.id}")
        await state.set_state(BroadcastStates.waiting_text)
        print("[broadcast] state set -> waiting_text (command)")
        await message.answer(
            "متن پیام همگانی را ارسال کنید.\n"
            "پس از دریافت متن، پیش‌نمایش به همراه دکمه‌های تأیید یا لغو نمایش داده می‌شود."
        )

    @router.callback_query(F.data == admin_broadcast_callback_data)
    async def broadcast_entry_button(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin_func(callback.from_user.id):
            await callback.answer("⛔️ اجازه دسترسی ندارید.", show_alert=True)
            return
        print(f"[broadcast] entry button from admin: {callback.from_user.id}")
        await state.set_state(BroadcastStates.waiting_text)
        print("[broadcast] state set -> waiting_text (button)")
        if callback.message:
            await callback.message.answer(
                "متن پیام همگانی را ارسال کنید.\n"
                "پس از دریافت متن، پیش‌نمایش به همراه دکمه‌های تأیید یا لغو نمایش داده می‌شود."
            )
        await callback.answer()

    @router.message(StateFilter(BroadcastStates.waiting_text), F.text)
    async def broadcast_preview(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin_func(message.from_user.id):
            await state.clear()
            await message.answer("⛔️ فقط ادمین می‌تواند پیام همگانی ارسال کند.")
            return

        text_raw = (message.text or "").strip()
        if not text_raw or text_raw.startswith("/"):
            await message.answer("❗️ متن خالی است یا با دستور شروع می‌شود. دوباره تلاش کن.")
            return

        current_state = await state.get_state()
        print(f"[broadcast] preview handler state: {current_state}")

        text = text_raw
        await state.update_data(pending_broadcast_text=text)
        await state.set_state(BroadcastStates.waiting_confirmation)
        print("[broadcast] state set -> waiting_confirmation (preview)")
        print(f"[broadcast] preview text len: {len(text)}")

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ تأیید و ارسال", callback_data="broadcast:confirm"),
                    InlineKeyboardButton(text="❌ لغو", callback_data="broadcast:cancel"),
                ]
            ]
        )
        await message.answer("پیش‌نمایش پیام همگانی:\n\n" + text, reply_markup=keyboard)

    @router.message(StateFilter(BroadcastStates.waiting_text))
    async def broadcast_preview_invalid(message: Message) -> None:
        print("[broadcast] non-text update received during waiting_text state")
        await message.answer("برای شروع، فقط متن ساده ارسال کنید.")

    @router.callback_query(StateFilter(BroadcastStates.waiting_confirmation), F.data == "broadcast:cancel")
    async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        print(f"[broadcast] cancel clicked by: {getattr(callback.from_user, 'id', None)}")
        if callback.message:
            await callback.message.edit_text("ارسال پیام همگانی لغو شد.")
        await state.clear()
        await callback.answer()

    @router.callback_query(StateFilter(BroadcastStates.waiting_confirmation), F.data == "broadcast:confirm")
    async def broadcast_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin_func(callback.from_user.id):
            await callback.answer("⛔️ اجازه دسترسی ندارید.", show_alert=True)
            return

        print(f"[broadcast] confirm clicked by: {callback.from_user.id}")

        data = await state.get_data()
        text = (data.get("pending_broadcast_text") or "").strip()

        if not text and callback.message and callback.message.text:
            prefix = "پیش‌نمایش پیام همگانی:\n\n"
            if callback.message.text.startswith(prefix):
                text = callback.message.text[len(prefix):].strip()

        if not text:
            if callback.message:
                await callback.message.edit_text("❗️ متن پیدا نشد. دوباره تلاش کنید.")
            await state.set_state(BroadcastStates.waiting_text)
            print("[broadcast] text missing on confirm; reverting to waiting_text")
            await callback.answer()
            return

        if callback.message:
            await callback.message.edit_text("در حال ارسال پیام همگانی...")

        sent = 0
        failed = 0
        for chat_id in get_all_users():
            try:
                for part in chunk_text(text):
                    await callback.bot.send_message(chat_id=chat_id, text=part)
                    await asyncio.sleep(SEND_DELAY_SECONDS)
                sent += 1
            except Exception:
                failed += 1

        total = sent + failed
        if callback.message:
            await callback.message.edit_text(
                f"ارسال پیام همگانی تمام شد.\n"
                f"✅ ارسال موفق: {sent}\n"
                f"⚠️ ناموفق: {failed}\n"
                f"👥 کل مخاطبان: {total}"
            )

        await state.clear()
        print(f"[broadcast] state cleared after confirm; sent: {sent} failed: {failed}")
        await callback.answer()

    if enable_stats_command:

        @router.message(Command(stats_command_name))
        async def stats_handler(message: Message) -> None:
            if not message.from_user or not is_admin_func(message.from_user.id):
                await message.answer("⛔️ فقط ادمین می‌تواند آمار کاربران را مشاهده کند.")
                return
            await message.answer(f"👥 تعداد کاربران ثبت‌شده: {users_count()}")

    return router


__all__ = [
    "BroadcastStates",
    "add_user",
    "build_broadcast_router",
    "chunk_text",
    "get_all_users",
    "get_broadcast_admin_button",
    "register_user_from_message",
    "users_count",
]

