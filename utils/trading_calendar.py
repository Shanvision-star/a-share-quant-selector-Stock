"""A-share trading calendar helpers used by update and strategy flows."""
from datetime import date as date_cls, timedelta


# SSE 2026 market holidays. Weekends are filtered separately.
A_SHARE_CLOSED_DATES = {
    date_cls(2026, 1, 1), date_cls(2026, 1, 2), date_cls(2026, 1, 3),
    *{date_cls(2026, 2, day) for day in range(15, 24)},
    date_cls(2026, 4, 4), date_cls(2026, 4, 5), date_cls(2026, 4, 6),
    *{date_cls(2026, 5, day) for day in range(1, 6)},
    date_cls(2026, 6, 19), date_cls(2026, 6, 20), date_cls(2026, 6, 21),
    date_cls(2026, 9, 25), date_cls(2026, 9, 26), date_cls(2026, 9, 27),
    *{date_cls(2026, 10, day) for day in range(1, 8)},
}


def is_a_share_trading_day(day: date_cls) -> bool:
    return day.weekday() < 5 and day not in A_SHARE_CLOSED_DATES


def previous_a_share_trading_day(day: date_cls) -> date_cls:
    cursor = day
    while not is_a_share_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def next_a_share_trading_day(day: date_cls) -> date_cls:
    """Return the first A-share trading day after day."""
    cursor = day + timedelta(days=1)
    while not is_a_share_trading_day(cursor):
        cursor += timedelta(days=1)
    return cursor


def advance_a_share_trading_days(day: date_cls, days: int) -> date_cls:
    """Advance by real A-share trading days.

    days=0 keeps a valid trading day unchanged. If the input day is closed,
    it is normalized to the previous trading day before advancing.
    """
    cursor = day if is_a_share_trading_day(day) else previous_a_share_trading_day(day)
    if days <= 0:
        return cursor
    for _ in range(days):
        cursor = next_a_share_trading_day(cursor)
    return cursor


def count_a_share_trading_days(start_day: date_cls, end_day: date_cls) -> int:
    """Count trading days inclusively from start_day to end_day."""
    if start_day > end_day:
        return 0

    cursor = start_day
    count = 0
    while cursor <= end_day:
        if is_a_share_trading_day(cursor):
            count += 1
        cursor += timedelta(days=1)
    return count
