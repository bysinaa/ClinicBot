from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def main_menu():
    kb = [
        [KeyboardButton(text="رزرو نوبت")],
        [KeyboardButton(text="ارسال رسید پرداخت")],
        [KeyboardButton(text="مشاوره هوشمند")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def dates_keyboard(dates: list[str]):
    rows = [[InlineKeyboardButton(text=d, callback_data=f"date:{d}")] for d in dates]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def times_keyboard(times: list[str], jdate: str):
    rows = []
    for t in times:
        rows.append([InlineKeyboardButton(text=t, callback_data=f"time:{jdate}:{t}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_menu():
    kb = [
        [KeyboardButton(text="نوبت‌های در انتظار")],
        [KeyboardButton(text="گزارش PDF")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
