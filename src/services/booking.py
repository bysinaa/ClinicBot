from dataclasses import dataclass
from datetime import date, time
from typing import Sequence

from persiantools.jdatetime import JalaliDate
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Appointment,
    AppointmentStatus,
    ScheduleDay,
    ScheduleSlot,
)

DEFAULT_TIME_SLOTS = [
    "09:00",
    "09:30",
    "10:00",
    "10:30",
    "11:00",
    "11:30",
    "12:00",
    "14:00",
    "14:30",
    "15:00",
    "15:30",
    "16:00",
]


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
        return existing
    day = ScheduleDay(date=day_date, is_active=True)
    session.add(day)
    await session.commit()
    await session.refresh(day)
    return day


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
    return await session.get(ScheduleSlot, slot_id)


async def create_schedule_slot(
    session: AsyncSession,
    day_id: int,
    start_time: time,
    end_time: time,
    capacity: int,
) -> ScheduleSlot:
    slot = ScheduleSlot(
        day_id=day_id,
        start_time=start_time,
        end_time=end_time,
        capacity=capacity,
        is_active=True,
    )
    session.add(slot)
    await session.commit()
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
