from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from sqlalchemy import select
from src.keyboards import main_menu
from src.states import RegistrationStates, BookingStates
from aiogram.fsm.context import FSMContext
from src.database import SessionLocal
from src.models import User, Role
from src.utils.national_id import is_valid_iran_national_id

router = Router(name="common")

@router.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await m.answer("سلام! به ربات کلینیک هوشمند خوش آمدید. لطفاً نام و نام‌خانوادگی خود را وارد کنید:", reply_markup=None)
    await state.set_state(RegistrationStates.waiting_name)

@router.message(RegistrationStates.waiting_name)
async def reg_fullname(m: Message, state: FSMContext):
    await state.update_data(full_name=m.text.strip())
    await m.answer("کدملی ۱۰ رقمی خود را وارد کنید:")
    await state.set_state(RegistrationStates.waiting_national_id)

@router.message(RegistrationStates.waiting_national_id)
async def reg_nid(m: Message, state: FSMContext):
    code = m.text.strip().replace("-", "")
    if not is_valid_iran_national_id(code):
        await m.answer("❌ کدملی نامعتبر است. لطفاً دوباره تلاش کنید.")
        return
    await state.update_data(national_id=code)
    await m.answer("شماره موبایل خود را وارد کنید (مثال: 09xxxxxxxxx):")
    await state.set_state(RegistrationStates.waiting_phone)

@router.message(RegistrationStates.waiting_phone)
async def reg_phone(m: Message, state: FSMContext):
    phone = m.text.strip()
    data = await state.get_data()
    async with SessionLocal() as session:
        user = User(tg_id=m.from_user.id, full_name=data["full_name"], national_id=data["national_id"], phone=phone, role=Role.patient)
        session.add(user)
        await session.commit()
    await state.clear()
    await m.answer("ثبت‌نام با موفقیت انجام شد ✅", reply_markup=main_menu())

@router.message(F.text == "مشاوره هوشمند")
async def smart_consult(m: Message):
    await m.answer("سوال پزشکی خود را به صورت کوتاه و عمومی ارسال کنید. (توجه: این مشاوره جایگزین پزشک نیست.)")

