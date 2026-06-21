"""A 股交易日历辅助函数，用于更新、策略和回测执行链路。"""
from datetime import date as date_cls, timedelta


def _date_range(start: date_cls, end: date_cls) -> set[date_cls]:
    return {start + timedelta(days=offset) for offset in range((end - start).days + 1)}


def _closed_weekdays(*ranges: tuple[date_cls, date_cls]) -> set[date_cls]:
    closed: set[date_cls] = set()
    for start, end in ranges:
        closed.update(day for day in _date_range(start, end) if day.weekday() < 5)
    return closed


A_SHARE_OFFLINE_CALENDAR_START = date_cls(2016, 1, 1)
A_SHARE_OFFLINE_CALENDAR_END = date_cls(2026, 12, 31)

# 官方上交所休市表离线化，保证历史回测不依赖实时网络。
A_SHARE_CLOSED_DATES = _closed_weekdays(
    (date_cls(2016, 1, 1), date_cls(2016, 1, 3)),
    (date_cls(2016, 2, 7), date_cls(2016, 2, 13)),
    (date_cls(2016, 4, 2), date_cls(2016, 4, 4)),
    (date_cls(2016, 4, 30), date_cls(2016, 5, 2)),
    (date_cls(2016, 6, 9), date_cls(2016, 6, 11)),
    (date_cls(2016, 9, 15), date_cls(2016, 9, 17)),
    (date_cls(2016, 10, 1), date_cls(2016, 10, 7)),
    (date_cls(2017, 1, 1), date_cls(2017, 1, 2)),
    (date_cls(2017, 1, 27), date_cls(2017, 2, 2)),
    (date_cls(2017, 4, 2), date_cls(2017, 4, 4)),
    (date_cls(2017, 4, 29), date_cls(2017, 5, 1)),
    (date_cls(2017, 5, 28), date_cls(2017, 5, 30)),
    (date_cls(2017, 10, 1), date_cls(2017, 10, 8)),
    (date_cls(2018, 1, 1), date_cls(2018, 1, 1)),
    (date_cls(2018, 2, 15), date_cls(2018, 2, 21)),
    (date_cls(2018, 4, 5), date_cls(2018, 4, 7)),
    (date_cls(2018, 4, 29), date_cls(2018, 5, 1)),
    (date_cls(2018, 6, 16), date_cls(2018, 6, 18)),
    (date_cls(2018, 9, 22), date_cls(2018, 9, 24)),
    (date_cls(2018, 10, 1), date_cls(2018, 10, 7)),
    (date_cls(2019, 1, 1), date_cls(2019, 1, 1)),
    (date_cls(2019, 2, 4), date_cls(2019, 2, 10)),
    (date_cls(2019, 4, 5), date_cls(2019, 4, 7)),
    (date_cls(2019, 5, 1), date_cls(2019, 5, 4)),
    (date_cls(2019, 6, 7), date_cls(2019, 6, 9)),
    (date_cls(2019, 9, 13), date_cls(2019, 9, 15)),
    (date_cls(2019, 10, 1), date_cls(2019, 10, 7)),
    (date_cls(2020, 1, 1), date_cls(2020, 1, 1)),
    (date_cls(2020, 1, 24), date_cls(2020, 2, 2)),
    (date_cls(2020, 4, 4), date_cls(2020, 4, 6)),
    (date_cls(2020, 5, 1), date_cls(2020, 5, 5)),
    (date_cls(2020, 6, 25), date_cls(2020, 6, 27)),
    (date_cls(2020, 10, 1), date_cls(2020, 10, 8)),
    (date_cls(2021, 1, 1), date_cls(2021, 1, 3)),
    (date_cls(2021, 2, 11), date_cls(2021, 2, 17)),
    (date_cls(2021, 4, 3), date_cls(2021, 4, 5)),
    (date_cls(2021, 5, 1), date_cls(2021, 5, 5)),
    (date_cls(2021, 6, 12), date_cls(2021, 6, 14)),
    (date_cls(2021, 9, 19), date_cls(2021, 9, 21)),
    (date_cls(2021, 10, 1), date_cls(2021, 10, 7)),
    (date_cls(2022, 1, 1), date_cls(2022, 1, 3)),
    (date_cls(2022, 1, 31), date_cls(2022, 2, 6)),
    (date_cls(2022, 4, 3), date_cls(2022, 4, 5)),
    (date_cls(2022, 4, 30), date_cls(2022, 5, 4)),
    (date_cls(2022, 6, 3), date_cls(2022, 6, 5)),
    (date_cls(2022, 9, 10), date_cls(2022, 9, 12)),
    (date_cls(2022, 10, 1), date_cls(2022, 10, 7)),
    (date_cls(2023, 1, 1), date_cls(2023, 1, 2)),
    (date_cls(2023, 1, 21), date_cls(2023, 1, 27)),
    (date_cls(2023, 4, 5), date_cls(2023, 4, 5)),
    (date_cls(2023, 4, 29), date_cls(2023, 5, 3)),
    (date_cls(2023, 6, 22), date_cls(2023, 6, 24)),
    (date_cls(2023, 9, 29), date_cls(2023, 10, 6)),
    (date_cls(2024, 1, 1), date_cls(2024, 1, 1)),
    (date_cls(2024, 2, 9), date_cls(2024, 2, 17)),
    (date_cls(2024, 4, 4), date_cls(2024, 4, 6)),
    (date_cls(2024, 5, 1), date_cls(2024, 5, 5)),
    (date_cls(2024, 6, 10), date_cls(2024, 6, 10)),
    (date_cls(2024, 9, 15), date_cls(2024, 9, 17)),
    (date_cls(2024, 10, 1), date_cls(2024, 10, 7)),
    (date_cls(2025, 1, 1), date_cls(2025, 1, 1)),
    (date_cls(2025, 1, 28), date_cls(2025, 2, 4)),
    (date_cls(2025, 4, 4), date_cls(2025, 4, 6)),
    (date_cls(2025, 5, 1), date_cls(2025, 5, 5)),
    (date_cls(2025, 5, 31), date_cls(2025, 6, 2)),
    (date_cls(2025, 10, 1), date_cls(2025, 10, 8)),
    (date_cls(2026, 1, 1), date_cls(2026, 1, 3)),
    (date_cls(2026, 2, 15), date_cls(2026, 2, 23)),
    (date_cls(2026, 4, 4), date_cls(2026, 4, 6)),
    (date_cls(2026, 5, 1), date_cls(2026, 5, 5)),
    (date_cls(2026, 6, 19), date_cls(2026, 6, 21)),
    (date_cls(2026, 9, 25), date_cls(2026, 9, 27)),
    (date_cls(2026, 10, 1), date_cls(2026, 10, 7)),
)


def _ensure_calendar_supported(day: date_cls) -> None:
    if day < A_SHARE_OFFLINE_CALENDAR_START or day > A_SHARE_OFFLINE_CALENDAR_END:
        raise ValueError("offline calendar supports 2016-01-01 through 2026-12-31")


def is_a_share_trading_day(day: date_cls) -> bool:
    _ensure_calendar_supported(day)
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
    if days < 0:
        raise ValueError("days must be non-negative")
    _ensure_calendar_supported(day)
    if is_a_share_trading_day(day):
        cursor = day
    else:
        try:
            cursor = previous_a_share_trading_day(day)
        except ValueError:
            # 支持窗口起点可能正好闭市，此时没有窗口内上一交易日，只能从该闭市日向后推进。
            if days == 0:
                return next_a_share_trading_day(day)
            cursor = day
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
