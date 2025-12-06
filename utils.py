import random
import string
from datetime import datetime, timedelta

from config import ORDER_DEADLINE_HOUR


def generate_token(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))


def available_dates(now: datetime) -> list[tuple[str, str]]:
    dates = []
    start_weekday = now.weekday()
    days_left = 6 - start_weekday  # до воскресенья включительно
    for i in range(days_left + 1):
        d = now + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        d_label = d.strftime("%d.%m (%a)")
        if i == 0:
            if now.hour >= ORDER_DEADLINE_HOUR:
                continue
            d_label = f"Сегодня (до {ORDER_DEADLINE_HOUR}:00)"
        dates.append((d_str, d_label))
    return dates


def deadline_passed(target_date: str, now: datetime) -> bool:
    target_dt = datetime.strptime(target_date, "%Y-%m-%d")
    if now.date() > target_dt.date():
        return True
    if now.date() == target_dt.date() and now.hour >= ORDER_DEADLINE_HOUR:
        return True
    return False
