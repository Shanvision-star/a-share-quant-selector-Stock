from datetime import date

import pytest

from utils.trading_calendar import (
    advance_a_share_trading_days,
    count_a_share_trading_days,
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


def test_advance_trading_days_rejects_negative_days():
    with pytest.raises(ValueError, match="days must be non-negative"):
        advance_a_share_trading_days(date(2026, 4, 30), -1)
