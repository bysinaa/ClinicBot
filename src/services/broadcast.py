# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

from src.models import Appointment, User

logger = logging.getLogger(__name__)


class SupportsSendMessage(Protocol):
    async def send_message(self, chat_id: int, text: str) -> Any:
        ...


DEFAULT_THROTTLE_DELAY = 0.05
DEFAULT_RETRY_DELAY = 0.5
DEFAULT_MAX_RETRIES = 3


@dataclass(slots=True)
class BroadcastSummary:
    total: int
    success: int
    failed: int
    errors: list[tuple[int | None, str]] = field(default_factory=list)


def _format_appointment_time(appointment: Appointment) -> str:
    slot = getattr(appointment, "slot", None)
    start_time = getattr(slot, "start_time", None)
    end_time = getattr(slot, "end_time", None)
    if start_time and end_time:
        return f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
    time_slot = getattr(appointment, "time_slot", None)
    return time_slot or "-"


def render_message_template(template: str, user: User, appointment: Appointment | None) -> str:
    replacements = {
        "name": user.full_name or "Unknown",
        "phone": user.phone or "-",
        "appointment_id": "-",
        "date": "-",
        "time": "-",
        "status": "-",
    }
    if appointment:
        replacements["appointment_id"] = str(getattr(appointment, "id", "-") or "-")
        replacements["date"] = getattr(appointment, "jdate", None) or "-"
        replacements["time"] = _format_appointment_time(appointment)
        status = getattr(appointment, "status", None)
        if hasattr(status, "value"):
            replacements["status"] = getattr(status, "value")
        elif status is not None:
            replacements["status"] = str(status)
    result = template
    for key, value in replacements.items():
        result = result.replace(f"{{{key}}}", value)
    return result


async def send_message_with_retry(
    bot: SupportsSendMessage,
    chat_id: int,
    text: str,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_RETRY_DELAY,
) -> tuple[bool, str | None]:
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return True, None
        except TelegramRetryAfter as exc:
            last_error = str(exc)
            if attempt == max_retries:
                break
            delay = exc.retry_after + base_delay
            logger.warning(
                "RetryAfter while sending broadcast to %s (attempt %s/%s). Sleeping %.2fs",
                chat_id,
                attempt + 1,
                max_retries + 1,
                delay,
            )
            await asyncio.sleep(delay)
        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            last_error = str(exc)
            logger.info("Broadcast skipped for %s: %s", chat_id, exc)
            return False, last_error
        except TelegramNetworkError as exc:
            last_error = str(exc)
            if attempt == max_retries:
                break
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Network error while sending broadcast to %s (attempt %s/%s). Retrying in %.2fs",
                chat_id,
                attempt + 1,
                max_retries + 1,
                delay,
            )
            await asyncio.sleep(delay)
        except Exception as exc:  # pragma: no cover - defensive
            last_error = str(exc)
            if attempt == max_retries:
                break
            delay = base_delay * (2 ** attempt)
            logger.exception(
                "Unexpected error while sending broadcast to %s (attempt %s/%s). Retrying in %.2fs",
                chat_id,
                attempt + 1,
                max_retries + 1,
                delay,
            )
            await asyncio.sleep(delay)
    logger.error(
        "Broadcast delivery failed for %s after %s attempts: %s",
        chat_id,
        max_retries + 1,
        last_error,
    )
    return False, last_error


async def broadcast_messages(
    bot: SupportsSendMessage,
    template: str,
    users: Sequence[User],
    appointments: Mapping[int | None, Appointment | None],
    *,
    throttle_delay: float = DEFAULT_THROTTLE_DELAY,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> BroadcastSummary:
    total = len(users)
    success = 0
    failed = 0
    errors: list[tuple[int | None, str]] = []
    for index, user in enumerate(users):
        tg_id = getattr(user, "tg_id", None)
        user_id = getattr(user, "id", None)
        if not tg_id:
            failed += 1
            errors.append((user_id, "missing tg_id"))
            continue
        message_text = render_message_template(
            template,
            user,
            appointments.get(user_id),
        )
        ok, error = await send_message_with_retry(
            bot,
            int(tg_id),
            message_text,
            max_retries=max_retries,
        )
        if ok:
            success += 1
        else:
            failed += 1
            if error:
                errors.append((user_id, error))
        if throttle_delay and index < total - 1:
            await asyncio.sleep(throttle_delay)
    return BroadcastSummary(total=total, success=success, failed=failed, errors=errors)


__all__ = [
    "BroadcastSummary",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_THROTTLE_DELAY",
    "broadcast_messages",
    "render_message_template",
    "send_message_with_retry",
]
