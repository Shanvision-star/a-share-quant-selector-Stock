"""A-share trading calendar helpers used by update and strategy flows."""
from datetime import date as date_cls, timedelta


def _date_range(start: date_cls, end: date_cls) -> set[date_cls]:
    return {start + timedelta(days=offset) for offset in range((end - start).days + 1)}


# Official SSE market closures kept offline for deterministic historical backtests.
A_SHARE_CLOSED_DATES = {
    date_cls(2024, 1, 1),
    *_date_range(date_cls(2024, 2, 9), date_cls(2024, 2, 17)), date_cls(2024, 2, 4), date_cls(2024, 2, 18),
    *_date_range(date_cls(2024, 4, 4), date_cls(2024, 4, 6)), date_cls(2024, 4, 7),
    *_date_range(date_cls(2024, 5, 1), date_cls(2024, 5, 5)), date_cls(2024, 4, 28), date_cls(2024, 5, 11),
    date_cls(2024, 6, 10),
    *_date_range(date_cls(2024, 9, 15), date_cls(2024, 9, 17)), date_cls(2024, 9, 14),
    *_date_range(date_cls(2024, 10, 1), date_cls(2024, 10, 7)), date_cls(2024, 9, 29), date_cls(2024, 10, 12),
    date_cls(2025, 1, 1),
    *_date_range(date_cls(2025, 1, 28), date_cls(2025, 2, 4)), date_cls(2025, 1, 26), date_cls(2025, 2, 8),
    *_date_range(date_cls(2025, 4, 4), date_cls(2025, 4, 6)),
    *_date_range(date_cls(2025, 5, 1), date_cls(2025, 5, 5)), date_cls(2025, 4, 27),
    *_date_range(date_cls(2025, 5, 31), date_cls(2025, 6, 2)),
    *_date_range(date_cls(2025, 10, 1), date_cls(2025, 10, 8)), date_cls(2025, 9, 28), date_cls(2025, 10, 11),
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
    if days < 0:
        raise ValueError("days must be non-negative")
    if days == 0:
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
