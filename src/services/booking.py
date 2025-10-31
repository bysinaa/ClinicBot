# -*- coding: utf-8 -*-
from dataclasses import dataclass

from datetime import date, time, datetime, timedelta
from typing import Sequence

from persiantools.jdatetime import JalaliDate
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import (
    Appointment,
    AppointmentStatus,
    ScheduleDay,
    ScheduleSlot,
)

DEFAULT_TIME_SLOTS = [f"{hour:02d}:00" for hour in range(8, 17)]


async def get_available_slots(session: AsyncSession, jdate: str) -> list[str]:
    """Legacy helper kept for backward compatibility."""
    result = await session.execute(
        select(Appointment).where(
            Appointment.jdate == jdate,
            Appointment.status != AppointmentStatus.canceled,
        )
    )
    taken = {a.time_slot for a in result.scalars().all()}
    return [t for t in DEFAULT_TIME_SLOTS if t not in taken]


@dataclass(frozen=True)
class SlotAvailability:
    slot_id: int
    start_time: str
    end_time: str
    capacity: int
    booked: int

    @property
    def remaining(self) -> int:
        return max(self.capacity - self.booked, 0)


@dataclass(frozen=True)
class SlotSummary:
    slot_id: int
    start_time: str
    end_time: str
    capacity: int
    booked: int
    is_active: bool

    @property
    def remaining(self) -> int:
        return max(self.capacity - self.booked, 0)


class SlotCreationError(Exception):
    """Raised when a schedule slot cannot be created."""


class SlotOverlapError(SlotCreationError):
    """Raised when a new slot intersects with an existing one."""

    def __init__(self, existing_start: time, existing_end: time) -> None:
        self.existing_start = existing_start
        self.existing_end = existing_end
        super().__init__(
            f"این بازه با بازهٔ {existing_start.strftime('%H:%M')} تا {existing_end.strftime('%H:%M')} تداخل دارد."
        )


async def list_schedule_days(
    session: AsyncSession,
    start: date,
    end: date,
) -> Sequence[ScheduleDay]:
    rows = (
        await session.execute(
            select(ScheduleDay)
            .where(
                ScheduleDay.date >= start,
                ScheduleDay.date <= end,
            )
            .order_by(ScheduleDay.date)
        )
    ).scalars().all()
    return rows


async def create_schedule_day(session: AsyncSession, day_date: date) -> ScheduleDay:
    existing = (
        await session.execute(select(ScheduleDay).where(ScheduleDay.date == day_date))
    ).scalar_one_or_none()
    if existing:
        await _ensure_default_slots(session, existing)
        return existing
    day = ScheduleDay(date=day_date, is_active=True)
    session.add(day)
    await session.commit()
    await session.refresh(day)
    await _ensure_default_slots(session, day)
    return day


async def _ensure_default_slots(session: AsyncSession, day: ScheduleDay) -> None:
    existing_slots = (
        await session.execute(
            select(ScheduleSlot)
            .where(ScheduleSlot.day_id == day.id)
            .order_by(ScheduleSlot.start_time, ScheduleSlot.id)
        )
    ).scalars().all()
    target_starts = [datetime.strptime(item, "%H:%M").time() for item in DEFAULT_TIME_SLOTS]
    slot_duration = timedelta(hours=1)

    if existing_slots:
        updated = False
        used_ids: set[int] = set()

        slots_by_start: dict[time, list[ScheduleSlot]] = {}
        for slot in existing_slots:
            slots_by_start.setdefault(slot.start_time, []).append(slot)

        for slot_list in slots_by_start.values():
            slot_list.sort(key=lambda s: s.id)

        for start_time in target_starts:
            desired_end = (datetime.combine(date.today(), start_time) + slot_duration).time()
            slot = None
            slot_candidates = slots_by_start.get(start_time)
            if slot_candidates:
                slot = next((s for s in slot_candidates if s.id not in used_ids), None)
            if slot is None:
                slot = next((s for s in existing_slots if s.id not in used_ids), None)
            if slot is None:
                session.add(
                    ScheduleSlot(
                        day_id=day.id,
                        start_time=start_time,
                        end_time=desired_end,
                        capacity=10,
                        is_active=True,
                    )
                )
                updated = True
            else:
                used_ids.add(slot.id)
                if slot.start_time != start_time:
                    slot.start_time = start_time
                    updated = True
                if slot.end_time != desired_end:
                    slot.end_time = desired_end
                    updated = True
                if slot.capacity != 10:
                    slot.capacity = 10
                    updated = True
                if not slot.is_active:
                    slot.is_active = True
                    updated = True

        for slot in existing_slots:
            if slot.id not in used_ids and slot.is_active:
                slot.is_active = False
                updated = True

        if updated:
            await session.commit()
        return

    for start_time in target_starts:
        end_time = (datetime.combine(date.today(), start_time) + slot_duration).time()
        session.add(
            ScheduleSlot(
                day_id=day.id,
                start_time=start_time,
                end_time=end_time,
                capacity=10,
                is_active=True,
            )
        )
    await session.commit()


async def delete_schedule_day(session: AsyncSession, day_id: int) -> bool:
    day = await session.get(ScheduleDay, day_id)
    if not day:
        return False
    await session.delete(day)
    await session.commit()
    return True


async def set_schedule_day_active(session: AsyncSession, day_id: int, active: bool) -> bool:
    day = await session.get(ScheduleDay, day_id)
    if not day:
        return False
    day.is_active = active
    await session.commit()
    return True


async def get_available_days(
    session: AsyncSession,
    start: date,
    end: date,
) -> Sequence[ScheduleDay]:
    rows = (
        await session.execute(
            select(ScheduleDay)
            .join(ScheduleSlot)
            .where(
                ScheduleDay.date >= start,
                ScheduleDay.date <= end,
                ScheduleDay.is_active.is_(True),
                ScheduleSlot.is_active.is_(True),
            )
            .group_by(ScheduleDay.id)
            .having(func.count(ScheduleSlot.id) > 0)
            .order_by(ScheduleDay.date)
        )
    ).scalars().all()
    return rows


async def get_day_availability(session: AsyncSession, jdate: str) -> Sequence[SlotAvailability]:
    try:
        year, month, day = map(int, jdate.split("-"))
        jalali_date = JalaliDate(year, month, day)
    except ValueError:
        return []
    gregorian = jalali_date.to_gregorian()
    slot_rows = (
        await session.execute(
            select(ScheduleSlot)
            .join(ScheduleDay, ScheduleDay.id == ScheduleSlot.day_id)
            .where(
                ScheduleDay.date == gregorian,
                ScheduleDay.is_active.is_(True),
                ScheduleSlot.is_active.is_(True),
            )
            .order_by(ScheduleSlot.start_time)
        )
    ).scalars().all()
    if not slot_rows:
        return []
    slot_ids = [slot.id for slot in slot_rows]
    counts = await session.execute(
        select(Appointment.slot_id, func.count(Appointment.id))
        .where(
            Appointment.slot_id.in_(slot_ids),
            Appointment.status != AppointmentStatus.canceled,
        )
        .group_by(Appointment.slot_id)
    )
    counts_map = dict(counts.all())
    availability: list[SlotAvailability] = []
    for slot in slot_rows:
        booked = counts_map.get(slot.id, 0)
        availability.append(
            SlotAvailability(
                slot_id=slot.id,
                start_time=slot.start_time.strftime("%H:%M"),
                end_time=slot.end_time.strftime("%H:%M"),
                capacity=slot.capacity,
                booked=booked,
            )
        )
    return availability


async def get_day_slot_summaries(session: AsyncSession, day_id: int) -> Sequence[SlotSummary]:
    slot_rows = (
        await session.execute(
            select(ScheduleSlot)
            .where(ScheduleSlot.day_id == day_id)
            .order_by(ScheduleSlot.start_time)
        )
    ).scalars().all()
    if not slot_rows:
        return []  # type: ignore[return-value]
    slot_ids = [slot.id for slot in slot_rows]
    counts = await session.execute(
        select(Appointment.slot_id, func.count(Appointment.id))
        .where(Appointment.slot_id.in_(slot_ids))
        .group_by(Appointment.slot_id)
    )
    counts_map = dict(counts.all())
    summaries: list[SlotSummary] = []
    for slot in slot_rows:
        booked = counts_map.get(slot.id, 0)
        summaries.append(
            SlotSummary(
                slot_id=slot.id,
                start_time=slot.start_time.strftime("%H:%M"),
                end_time=slot.end_time.strftime("%H:%M"),
                capacity=slot.capacity,
                booked=booked,
                is_active=slot.is_active,
            )
        )
    return summaries


async def get_slot_by_id(session: AsyncSession, slot_id: int) -> ScheduleSlot | None:
    return await session.get(
        ScheduleSlot,
        slot_id,
        options=(selectinload(ScheduleSlot.day),),
    )


async def create_schedule_slot(
    session: AsyncSession,
    day_id: int,
    start_time: time,
    end_time: time,
    capacity: int,
) -> ScheduleSlot:
    if capacity <= 0:
        raise SlotCreationError("ظرفیت بازه باید بزرگ‌تر از صفر باشد.")
    if start_time >= end_time:
        raise SlotCreationError("زمان پایان باید بعد از زمان شروع باشد.")
    existing = (
        await session.execute(
            select(ScheduleSlot)
            .where(
                ScheduleSlot.day_id == day_id,
                ScheduleSlot.is_active.is_(True),
                ScheduleSlot.start_time < end_time,
                ScheduleSlot.end_time > start_time,
            )
            .order_by(ScheduleSlot.start_time)
        )
    ).scalars().first()
    if existing:
        raise SlotOverlapError(existing.start_time, existing.end_time)
    slot = ScheduleSlot(
        day_id=day_id,
        start_time=start_time,
        end_time=end_time,
        capacity=capacity,
        is_active=True,
    )
    session.add(slot)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise SlotCreationError("ایجاد بازه به دلیل خطای پایگاه‌داده انجام نشد.") from exc
    await session.refresh(slot)
    return slot


async def set_schedule_slot_active(session: AsyncSession, slot_id: int, active: bool) -> bool:
    slot = await session.get(ScheduleSlot, slot_id)
    if not slot:
        return False
    slot.is_active = active
    await session.commit()
    return True


async def delete_schedule_slot(session: AsyncSession, slot_id: int) -> bool:
    slot = await session.get(ScheduleSlot, slot_id)
    if not slot:
        return False
    booked = await count_slot_bookings(session, slot_id)
    if booked > 0:
        return False
    await session.delete(slot)
    await session.commit()
    return True


async def count_user_bookings_for_day(
    session: AsyncSession,
    user_id: int,
    jdate: str,
) -> int:
    result = await session.execute(
        select(func.count(Appointment.id)).where(
            Appointment.user_id == user_id,
            Appointment.jdate == jdate,
            Appointment.status != AppointmentStatus.canceled,
        )
    )
    return int(result.scalar_one())


async def count_slot_bookings(session: AsyncSession, slot_id: int) -> int:
    result = await session.execute(
        select(func.count(Appointment.id)).where(Appointment.slot_id == slot_id)
    )
    return int(result.scalar_one())

