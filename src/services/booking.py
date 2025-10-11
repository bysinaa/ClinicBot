from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models import Appointment, AppointmentStatus
from typing import Sequence

DEFAULT_TIME_SLOTS = ["09:00","09:30","10:00","10:30","11:00","11:30","12:00",
                      "14:00","14:30","15:00","15:30","16:00"]

async def get_available_slots(session: AsyncSession, jdate: str) -> list[str]:
    # Calculate available slots by removing those already taken (pending/confirmed)
    result = await session.execute(
        select(Appointment).where(Appointment.jdate == jdate, Appointment.status != AppointmentStatus.canceled)
    )
    taken = {a.time_slot for a in result.scalars().all()}
    return [t for t in DEFAULT_TIME_SLOTS if t not in taken]
