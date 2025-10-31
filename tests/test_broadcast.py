# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import types
import unittest
from datetime import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

from src.services.broadcast import (
    BroadcastSummary,
    broadcast_messages,
    render_message_template,
    send_message_with_retry,
)

logging.getLogger("src.services.broadcast").setLevel(logging.CRITICAL)


class RenderTemplateTests(unittest.TestCase):
    def test_render_template_with_appointment(self) -> None:
        user = types.SimpleNamespace(full_name="Ali Reza", phone="09121234567", id=1)
        slot = types.SimpleNamespace(start_time=time(9, 0), end_time=time(9, 30))
        appointment = types.SimpleNamespace(
            id=42,
            jdate="1403-01-10",
            time_slot="09:00",
            status=types.SimpleNamespace(value="confirmed"),
            slot=slot,
        )
        template = "Hello {name}, phone {phone}, appt {appointment_id} on {date} at {time} [{status}]"
        result = render_message_template(template, user, appointment)
        expected = "Hello Ali Reza, phone 09121234567, appt 42 on 1403-01-10 at 09:00 - 09:30 [confirmed]"
        self.assertEqual(result, expected)

    def test_render_template_without_appointment(self) -> None:
        user = types.SimpleNamespace(full_name=None, phone=None, id=7)
        template = "Hi {name}! Contact: {phone}. Last status: {status}"
        result = render_message_template(template, user, None)
        self.assertEqual(result, "Hi Unknown! Contact: -. Last status: -")


class SendMessageWithRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_after_then_success(self) -> None:
        class _FakeBot:
            def __init__(self) -> None:
                self.send_message = AsyncMock()

        bot = _FakeBot()
        retry_exc = TelegramRetryAfter(
            method=MagicMock(),
            message="Flood control",
            retry_after=0,
        )
        bot.send_message.side_effect = [retry_exc, None]
        with patch("src.services.broadcast.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            ok, error = await send_message_with_retry(bot, chat_id=123, text="hello", max_retries=2)
        self.assertTrue(ok)
        self.assertIsNone(error)
        self.assertEqual(bot.send_message.await_count, 2)
        sleep_mock.assert_awaited()

    async def test_forbidden_stops_immediately(self) -> None:
        class _FakeBot:
            def __init__(self) -> None:
                self.send_message = AsyncMock()

        bot = _FakeBot()
        bot.send_message.side_effect = TelegramForbiddenError(
            method=MagicMock(),
            message="Blocked",
        )
        with patch("src.services.broadcast.asyncio.sleep", new=AsyncMock()) as sleep_mock:
            ok, error = await send_message_with_retry(bot, chat_id=999, text="ping", max_retries=2)
        self.assertFalse(ok)
        self.assertIsNotNone(error)
        bot.send_message.assert_awaited_once()
        sleep_mock.assert_not_awaited()


class BroadcastMessagesTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_summary_counts(self) -> None:
        bot = types.SimpleNamespace()

        users = [
            types.SimpleNamespace(id=1, tg_id=101, full_name="User1", phone="1"),
            types.SimpleNamespace(id=2, tg_id=202, full_name="User2", phone="2"),
        ]
        appointments: dict[int, Any] = {user.id: None for user in users}

        async def _fake_send_message(*args: Any, **kwargs: Any) -> tuple[bool, str | None]:
            raise AssertionError("Should not be called")

        bot.send_message = AsyncMock(side_effect=_fake_send_message)  # type: ignore[attr-defined]

        with patch(
            "src.services.broadcast.send_message_with_retry",
            new=AsyncMock(side_effect=[(True, None), (False, "failed")]),
        ):
            summary = await broadcast_messages(
                bot,
                template="Ping {name}",
                users=users,
                appointments=appointments,
                throttle_delay=0,
            )
        self.assertIsInstance(summary, BroadcastSummary)
        self.assertEqual(summary.total, 2)
        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.errors, [(2, "failed")])


if __name__ == "__main__":
    unittest.main()
