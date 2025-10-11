from aiogram.fsm.state import StatesGroup, State

class RegistrationStates(StatesGroup):
    waiting_name = State()
    waiting_national_id = State()
    waiting_phone = State()

class BookingStates(StatesGroup):
    choosing_date = State()
    choosing_time = State()
    waiting_receipt = State()

class AdminStates(StatesGroup):
    waiting_secret = State()
