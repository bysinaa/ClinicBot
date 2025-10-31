from datetime import datetime, timedelta, date
from persiantools.jdatetime import JalaliDate

JALALI_MONTH_NAMES = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]

JALALI_WEEKDAY_NAMES = [
    "شنبه",
    "یکشنبه",
    "دوشنبه",
    "سه‌شنبه",
    "چهارشنبه",
    "پنجشنبه",
    "جمعه",
]


def today_jalali() -> str:
    return JalaliDate.today().strftime("%Y-%m-%d")


def next_jalali_days(n: int = 7) -> list[str]:
    # Generate next n days in Jalali calendar
    days = []
    for i in range(n):
        g = datetime.utcnow() + timedelta(days=i)
        j = JalaliDate.to_jalali(g.year, g.month, g.day)
        days.append(j.strftime("%Y-%m-%d"))
    return days


def gregorian_to_jalali(date_value: date) -> JalaliDate:
    return JalaliDate.to_jalali(date_value.year, date_value.month, date_value.day)


def gregorian_to_jalali_str(value: date) -> str:
    j = gregorian_to_jalali(value)
    return j.strftime("%Y-%m-%d")


def jalali_month_name(month: int) -> str:
    return JALALI_MONTH_NAMES[month - 1]


def jalali_weekday_name(j_date: JalaliDate) -> str:
    return JALALI_WEEKDAY_NAMES[j_date.weekday()]


def format_jalali_day(j_date: JalaliDate) -> str:
    return f"{jalali_weekday_name(j_date)} {j_date.day} {jalali_month_name(j_date.month)}"
