from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from src.states import BookingStates
from src.keyboards import dates_keyboard, times_keyboard
from src.utils.jalali import next_jalali_days
from src.database import SessionLocal
from src.models import User, Appointment, AppointmentStatus
from src.services.booking import get_available_slots
from src.services.payment import link_receipt
from src.services.ai_consultation import consult_medical

router = Router(name="patient")

@router.message(F.text == "رزرو نوبت")
async def start_booking(m: Message, state: FSMContext):
    dates = next_jalali_days(7)
    await m.answer("لطفاً یک تاریخ را انتخاب کنید:", reply_markup=dates_keyboard(dates))
    await state.set_state(BookingStates.choosing_date)

@router.callback_query(F.data.startswith("date:"))
async def choose_date(c: CallbackQuery, state: FSMContext):
    jdate = c.data.split(":")[1]
    async with SessionLocal() as session:
        slots = await get_available_slots(session, jdate)
    if not slots:
        await c.message.edit_text(f"برای تاریخ {jdate} اسلات خالی وجود ندارد. تاریخ دیگری را انتخاب کنید.")
        return
    await c.message.edit_text(f"تاریخ انتخابی: {jdate}\nیکی از ساعات زیر را برگزینید:", reply_markup=times_keyboard(slots, jdate))
    await state.set_state(BookingStates.choosing_time)
    await c.answer()

@router.callback_query(F.data.startswith("time:"))
async def choose_time(c: CallbackQuery, state: FSMContext):
    _, jdate, t = c.data.split(":")
    async with SessionLocal() as session:
        # create appointment pending
        from src.models import User, Appointment
        q = await session.execute(select(User).where(User.tg_id == c.from_user.id))
        user = q.scalar_one_or_none()
        appt = Appointment(user_id=user.id, jdate=jdate, time_slot=t)
        session.add(appt)
        await session.commit()
        await state.update_data(appointment_id=appt.id)
    await c.message.edit_text(f"نوبت شما ثبت موقت شد. برای تکمیل، رسید پرداخت را ارسال کنید (به صورت عکس).")
    await state.set_state(BookingStates.waiting_receipt)
    await c.answer()

@router.message(BookingStates.waiting_receipt, F.photo)
async def receive_receipt(m: Message, state: FSMContext):
    data = await state.get_data()
    file_id = m.photo[-1].file_id
    async with SessionLocal() as session:
        await link_receipt(session, data["appointment_id"], file_id)
    await state.clear()
    await m.answer("رسید دریافت شد ✅\nپس از بررسی ادمین نتیجه به شما اعلام می‌شود.")

@router.message(F.text == "ارسال رسید پرداخت")
async def ask_receipt(m: Message, state: FSMContext):
    await m.answer("لطفاً تصویر رسید پرداخت را ارسال کنید و در کپشن، شناسه نوبت را بنویسید.")

@router.message(F.caption.regexp(r"^\s*#?(\d+)\s*$"), F.photo.as_("ph"))
async def receipt_with_caption(m: Message, ph, state: FSMContext, regexp):
    appt_id = int(regexp.group(1))
    file_id = ph[-1].file_id
    async with SessionLocal() as session:
        ok = await link_receipt(session, appt_id, file_id)
    if ok:
        await m.answer("رسید به نوبت پیوند خورد ✅")
    else:
        await m.answer("❌ شناسه نوبت نامعتبر است.")

@router.message()
async def maybe_consult(m: Message):
    # If user sends a message after tapping "مشاوره هوشمند", we treat it as a question (simple heuristic)
    if m.text and len(m.text) > 6:
        answer = await consult_medical(m.text)
        await m.answer(answer)
