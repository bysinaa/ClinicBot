from datetime import datetime, timedelta
from persiantools.jdatetime import JalaliDate

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
