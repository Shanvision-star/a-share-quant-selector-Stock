from datetime import date

import pytest

from utils.trading_calendar import (
    advance_a_share_trading_days,
    count_a_share_trading_days,
    is_a_share_trading_day,
    next_a_share_trading_day,
    previous_a_share_trading_day,
)


def test_may_day_gap_counts_only_real_a_share_trading_days():
    assert count_a_share_trading_days(date(2026, 5, 1), date(2026, 5, 6)) == 1


def test_previous_trading_day_skips_2026_may_day_holiday():
    assert previous_a_share_trading_day(date(2026, 5, 4)) == date(2026, 4, 30)


def test_next_trading_day_skips_2026_may_day_holiday():
    assert next_a_share_trading_day(date(2026, 4, 30)) == date(2026, 5, 6)


def test_advance_trading_days_handles_zero_and_holiday_gap():
    assert advance_a_share_trading_days(date(2026, 4, 30), 0) == date(2026, 4, 30)
    assert advance_a_share_trading_days(date(2026, 4, 30), 1) == date(2026, 5, 6)
    assert advance_a_share_trading_days(date(2026, 4, 30), 2) == date(2026, 5, 7)
    assert advance_a_share_trading_days(date(2026, 5, 1), 0) == date(2026, 4, 30)
    assert advance_a_share_trading_days(date(2026, 5, 1), 1) == date(2026, 5, 6)


def test_advance_trading_days_skips_2025_national_day_holiday():
    assert advance_a_share_trading_days(date(2025, 9, 30), 1) == date(2025, 10, 9)


def test_advance_trading_days_skips_2023_mid_autumn_national_day_holiday():
    assert advance_a_share_trading_days(date(2023, 9, 28), 1) == date(2023, 10, 9)


def test_advance_trading_days_handles_closed_start_of_supported_calendar():
    assert advance_a_share_trading_days(date(2016, 1, 1), 0) == date(2016, 1, 4)
    assert advance_a_share_trading_days(date(2016, 1, 1), 1) == date(2016, 1, 4)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2019, 5, 3), False),
        (date(2019, 5, 6), True),
        (date(2020, 1, 31), False),
        (date(2020, 2, 3), True),
    ],
)
def test_historical_special_closure_adjustments(day, expected):
    assert is_a_share_trading_day(day) is expected


def test_advance_trading_days_rejects_negative_days():
    with pytest.raises(ValueError, match="days must be non-negative"):
        advance_a_share_trading_days(date(2026, 4, 30), -1)


def test_advance_trading_days_rejects_unsupported_offline_calendar_year():
    with pytest.raises(ValueError, match="offline calendar supports 2016-01-01 through 2026-12-31"):
        advance_a_share_trading_days(date(2015, 12, 31), 1)
