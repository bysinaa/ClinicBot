from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Appointment, PaymentStatus


async def link_receipt(session: AsyncSession, appointment_id: int, file_id: str):
    appt = await session.get(Appointment, appointment_id)
    if not appt:
        return False
    appt.receipt_file_id = file_id
    appt.payment_status = PaymentStatus.awaiting_confirmation
    await session.commit()
    await session.refresh(appt)
    return True
