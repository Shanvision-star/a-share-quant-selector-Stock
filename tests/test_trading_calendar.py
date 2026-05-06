from datetime import date

from utils.trading_calendar import count_a_share_trading_days, previous_a_share_trading_day


def test_may_day_gap_counts_only_real_a_share_trading_days():
    assert count_a_share_trading_days(date(2026, 5, 1), date(2026, 5, 6)) == 1


def test_previous_trading_day_skips_2026_may_day_holiday():
    assert previous_a_share_trading_day(date(2026, 5, 4)) == date(2026, 4, 30)
