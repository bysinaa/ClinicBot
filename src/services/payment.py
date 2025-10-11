from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.models import Appointment

async def link_receipt(session: AsyncSession, appointment_id: int, file_id: str):
    appt = await session.get(Appointment, appointment_id)
    if not appt:
        return False
    appt.receipt_file_id = file_id
    await session.commit()
    await session.refresh(appt)
    return True
