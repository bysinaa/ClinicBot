from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from src.states import AdminStates
from src.config import settings
from src.database import SessionLocal
from src.models import User, Appointment, AppointmentStatus
from src.keyboards import admin_menu
from src.services.pdf_reports import generate_appointment_pdf

router = Router(name="admin")

@router.message(Command("admin"))
async def admin_entry(m: Message, state: FSMContext):
    await m.answer("رمز ادمین را وارد کنید:")
    await state.set_state(AdminStates.waiting_secret)

@router.message(AdminStates.waiting_secret)
async def admin_check(m: Message, state: FSMContext):
    if m.text.strip() != settings.admin_secret:
        await m.answer("❌ رمز نادرست است.")
        return
    await state.clear()
    await m.answer("خوش آمدید! منوی ادمین:", reply_markup=admin_menu())

@router.message(F.text == "نوبت‌های در انتظار")
async def pending_list(m: Message):
    async with SessionLocal() as session:
        result = await session.execute(select(Appointment, User).join(User, User.id == Appointment.user_id).where(Appointment.status == AppointmentStatus.pending))
        rows = result.all()
    if not rows:
        await m.answer("نوبت در انتظار یافت نشد.")
        return
    text = "نوبت‌های در انتظار:\n"
    for appt, user in rows[:20]:
        text += f"- #{appt.id} | {user.full_name} | {appt.jdate} {appt.time_slot}\n"
    text += "\nبرای تأیید: /confirm_<id>  —  برای رد: /cancel_<id>"
    await m.answer(text)

@router.message(F.text.regexp(r"^/confirm_(\d+)$"))
async def admin_confirm(m: Message, regexp):
    appt_id = int(regexp.group(1))
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            await m.answer("شناسه نامعتبر است.")
            return
        appt.status = AppointmentStatus.confirmed
        await session.commit()
    await m.answer(f"نوبت #{appt_id} تأیید شد ✅")

@router.message(F.text.regexp(r"^/cancel_(\d+)$"))
async def admin_cancel(m: Message, regexp):
    appt_id = int(regexp.group(1))
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            await m.answer("شناسه نامعتبر است.")
            return
        appt.status = AppointmentStatus.canceled
        await session.commit()
    await m.answer(f"نوبت #{appt_id} لغو شد ❌")

@router.message(F.text == "گزارش PDF")
async def admin_pdf(m: Message):
    await m.answer("برای ساخت PDF، دستور `/pdf_<id>` را بزنید.")

@router.message(F.text.regexp(r"^/pdf_(\d+)$"))
async def pdf_report(m: Message, regexp):
    appt_id = int(regexp.group(1))
    async with SessionLocal() as session:
        appt = await session.get(Appointment, appt_id)
        if not appt:
            await m.answer("شناسه نامعتبر است.")
            return
        user = await session.get(User, appt.user_id)
    path = generate_appointment_pdf("./reports", appt.id, user.full_name or "-", appt.jdate, appt.time_slot, appt.status.value)
    await m.answer_document(FSInputFile(path), caption=f"گزارش نوبت #{appt_id}")
