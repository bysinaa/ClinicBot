from aiogram.fsm.state import StatesGroup, State

class RegistrationStates(StatesGroup):
    waiting_name = State()
    waiting_national_id = State()
    waiting_birth_year = State()
    waiting_birth_month = State()
    waiting_birth_day = State()
    waiting_phone = State()

class BookingStates(StatesGroup):
    choosing_month = State()
    choosing_day = State()
    choosing_slot = State()
    waiting_receipt = State()

class AdminStates(StatesGroup):
    waiting_secret = State()

class AdminPdfStates(StatesGroup):
    selecting_month = State()
    selecting_day = State()

class AdminScheduleStates(StatesGroup):
    selecting_month = State()
    selecting_day = State()
    awaiting_day_input = State()
    awaiting_slot_start = State()
    awaiting_slot_end = State()
    awaiting_slot_capacity = State()

class OnlineConsultStates(StatesGroup):
    waiting_question = State()
    waiting_receipt = State()

