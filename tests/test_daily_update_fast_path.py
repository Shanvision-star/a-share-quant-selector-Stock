import io
import sys
import time
from datetime import datetime as real_datetime

import pandas as pd

import utils.akshare_fetcher as akshare_fetcher
from utils.akshare_fetcher import AKShareFetcher


def _write_stock_csv(data_dir, code, date_text="2026-04-30"):
    subdir = data_dir / code[:2]
    subdir.mkdir(parents=True, exist_ok=True)
    (subdir / f"{code}.csv").write_text(
        "\n".join([
            "date,open,high,low,close,volume,amount,turnover,market_cap",
            f"{date_text},10,11,9,10.5,1000,1050000,1.2,1000000000",
        ]) + "\n",
        encoding="utf-8",
    )


def test_daily_update_uses_fast_path_across_a_share_holiday_gap(tmp_path, monkeypatch):
    _write_stock_csv(tmp_path, "000001")
    _write_stock_csv(tmp_path, "600000")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 6, 16, 0, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))
    fetcher._market_cap_cache = {"000001": 1000000000, "600000": 1000000000}
    fetcher._market_cap_cache_date = "2026-05-06"

    monkeypatch.setattr(
        fetcher,
        "_fetch_spot_snapshot_map",
        lambda target_date_str, stock_codes=None: {
            code: {
                "date": target_date_str,
                "open": 11.0,
                "high": 12.0,
                "low": 10.8,
                "close": 11.5,
                "volume": 2000,
                "amount": 2300000.0,
                "turnover": 1.5,
                "market_cap": 1100000000,
            }
            for code in stock_codes
        },
    )

    summary = fetcher.daily_update(date="2026-05-06", allow_intraday_fast=False)

    assert summary["status"] == "done"
    assert summary["fast_path_total"] == 2
    assert summary["fast_path_success"] == 2
    assert summary["slow_path_total"] == 0

    for code in ("000001", "600000"):
        first_row = pd.read_csv(fetcher.csv_manager.get_stock_path(code), nrows=1)
        assert first_row.iloc[0]["date"] == "2026-05-06"


def test_daily_update_uses_fast_path_before_next_trading_day_open(tmp_path, monkeypatch):
    _write_stock_csv(tmp_path, "000001")
    _write_stock_csv(tmp_path, "600000")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 7, 5, 30, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))
    fetcher._market_cap_cache = {"000001": 1000000000, "600000": 1000000000}
    fetcher._market_cap_cache_date = "2026-05-07"

    monkeypatch.setattr(
        fetcher,
        "_fetch_spot_snapshot_map",
        lambda target_date_str, stock_codes=None: {
            code: {
                "date": target_date_str,
                "open": 11.0,
                "high": 12.0,
                "low": 10.8,
                "close": 11.5,
                "volume": 2000,
                "amount": 2300000.0,
                "turnover": 1.5,
                "market_cap": 1100000000,
            }
            for code in stock_codes
        },
    )

    summary = fetcher.daily_update(date="2026-05-06", allow_intraday_fast=False)

    assert summary["status"] == "done"
    assert summary["target_date"] == "2026-05-06"
    assert summary["fast_path_total"] == 2
    assert summary["fast_path_success"] == 2
    assert summary["slow_path_total"] == 0


def test_daily_update_uses_fast_path_after_same_day_preopen_fallback(tmp_path, monkeypatch):
    _write_stock_csv(tmp_path, "000001")
    _write_stock_csv(tmp_path, "600000")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 7, 5, 30, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))
    fetcher._market_cap_cache = {"000001": 1000000000, "600000": 1000000000}
    fetcher._market_cap_cache_date = "2026-05-07"

    requested_snapshot_dates = []

    def fake_snapshot(target_date_str, stock_codes=None):
        requested_snapshot_dates.append(target_date_str)
        return {
            code: {
                "date": target_date_str,
                "open": 11.0,
                "high": 12.0,
                "low": 10.8,
                "close": 11.5,
                "volume": 2000,
                "amount": 2300000.0,
                "turnover": 1.5,
                "market_cap": 1100000000,
            }
            for code in stock_codes
        }

    monkeypatch.setattr(fetcher, "_fetch_spot_snapshot_map", fake_snapshot)
    gbk_stdout = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", gbk_stdout)

    summary = fetcher.daily_update(date="2026-05-07", allow_intraday_fast=False)

    assert summary["status"] == "done"
    assert summary["target_date"] == "2026-05-06"
    assert requested_snapshot_dates == ["2026-05-06"]
    assert summary["fast_path_total"] == 2
    assert summary["fast_path_success"] == 2
    assert summary["slow_path_total"] == 0


def test_daily_update_intraday_fast_before_open_still_targets_completed_day(tmp_path, monkeypatch):
    """开盘前即使勾选盘中快路径，也只能补最近已完成交易日，不能写入当天未开盘快照。"""
    _write_stock_csv(tmp_path, "000001", date_text="2026-05-12")
    _write_stock_csv(tmp_path, "600000", date_text="2026-05-12")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 14, 7, 30, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))
    fetcher._market_cap_cache = {"000001": 1000000000, "600000": 1000000000}
    fetcher._market_cap_cache_date = "2026-05-14"
    requested_snapshot_dates = []

    def fake_snapshot(target_date_str, stock_codes=None):
        requested_snapshot_dates.append(target_date_str)
        return {
            code: {
                "date": target_date_str,
                "open": 11.0,
                "high": 12.0,
                "low": 10.8,
                "close": 11.5,
                "volume": 2000,
                "amount": 2300000.0,
                "turnover": 1.5,
                "market_cap": 1100000000,
            }
            for code in stock_codes
        }

    monkeypatch.setattr(fetcher, "_fetch_spot_snapshot_map", fake_snapshot)

    summary = fetcher.daily_update(date=None, allow_intraday_fast=True)

    assert summary["status"] == "done"
    assert summary["target_date"] == "2026-05-13"
    assert requested_snapshot_dates == ["2026-05-13"]
    assert summary["fast_path_total"] == 2
    assert summary["fast_path_success"] == 2
    assert summary["slow_path_total"] == 0


def test_daily_update_intraday_fast_from_nine_oclock_can_target_today(tmp_path, monkeypatch):
    """9:00 起用户勾选盘中快路径时，可以尝试写入当天快照。"""
    _write_stock_csv(tmp_path, "000001", date_text="2026-05-13")
    _write_stock_csv(tmp_path, "600000", date_text="2026-05-13")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 14, 9, 0, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))
    fetcher._market_cap_cache = {"000001": 1000000000, "600000": 1000000000}
    fetcher._market_cap_cache_date = "2026-05-14"
    requested_snapshot_dates = []

    def fake_snapshot(target_date_str, stock_codes=None):
        requested_snapshot_dates.append(target_date_str)
        return {
            code: {
                "date": target_date_str,
                "open": 11.0,
                "high": 12.0,
                "low": 10.8,
                "close": 11.5,
                "volume": 2000,
                "amount": 2300000.0,
                "turnover": 1.5,
                "market_cap": 1100000000,
            }
            for code in stock_codes
        }

    monkeypatch.setattr(fetcher, "_fetch_spot_snapshot_map", fake_snapshot)

    summary = fetcher.daily_update(date=None, allow_intraday_fast=True)

    assert summary["status"] == "done"
    assert summary["target_date"] == "2026-05-14"
    assert requested_snapshot_dates == ["2026-05-14"]
    assert summary["fast_path_total"] == 2
    assert summary["fast_path_success"] == 2
    assert summary["slow_path_total"] == 0


def test_daily_update_refetches_fast_snapshot_after_same_day_snapshot_fallback(tmp_path, monkeypatch):
    """9:00 后尝试当天快照但尚未就绪时，回退后要重新按已完成交易日走快路径。"""
    _write_stock_csv(tmp_path, "000001", date_text="2026-05-12")
    _write_stock_csv(tmp_path, "600000", date_text="2026-05-12")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 14, 9, 0, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))
    fetcher._market_cap_cache = {"000001": 1000000000, "600000": 1000000000}
    fetcher._market_cap_cache_date = "2026-05-14"
    requested_snapshot_dates = []

    def fake_snapshot(target_date_str, stock_codes=None):
        requested_snapshot_dates.append(target_date_str)
        if target_date_str == "2026-05-14":
            return {}
        return {
            code: {
                "date": target_date_str,
                "open": 11.0,
                "high": 12.0,
                "low": 10.8,
                "close": 11.5,
                "volume": 2000,
                "amount": 2300000.0,
                "turnover": 1.5,
                "market_cap": 1100000000,
            }
            for code in stock_codes
        }

    monkeypatch.setattr(fetcher, "_fetch_spot_snapshot_map", fake_snapshot)

    def fail_slow_path(*args, **kwargs):
        raise AssertionError("回退到最近已完成交易日后应重新走快路径")

    monkeypatch.setattr(fetcher, "_update_single_stock", fail_slow_path)

    summary = fetcher.daily_update(date="2026-05-14", allow_intraday_fast=True)

    assert summary["status"] == "done"
    assert summary["target_date"] == "2026-05-13"
    assert requested_snapshot_dates == ["2026-05-14", "2026-05-13"]
    assert summary["fast_path_total"] == 2
    assert summary["fast_path_success"] == 2
    assert summary["slow_path_total"] == 0


def test_daily_update_downgrades_same_day_selection_before_close_without_intraday_fast(tmp_path, monkeypatch):
    _write_stock_csv(tmp_path, "000001", date_text="2026-05-06")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 7, 5, 30, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))

    def _should_not_fetch(*args, **kwargs):
        raise AssertionError("same-day snapshot should not be requested before close when intraday fast is disabled")

    monkeypatch.setattr(fetcher, "_fetch_spot_snapshot_map", _should_not_fetch)

    summary = fetcher.daily_update(date="2026-05-07", allow_intraday_fast=False)

    assert summary["status"] == "done"
    assert summary["target_date"] == "2026-05-06"
    assert summary["to_update"] == 0
    assert summary["fast_path_total"] == 0
    assert summary["slow_path_total"] == 0


def test_daily_update_falls_back_when_same_day_snapshot_is_unavailable(tmp_path, monkeypatch):
    _write_stock_csv(tmp_path, "000001", date_text="2026-05-06")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 7, 15, 30, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))

    monkeypatch.setattr(fetcher, "_fetch_spot_snapshot_map", lambda *args, **kwargs: {})

    summary = fetcher.daily_update(date="2026-05-07", allow_intraday_fast=False)

    assert summary["status"] == "done"
    assert summary["target_date"] == "2026-05-06"
    assert summary["to_update"] == 0
    assert summary["fast_path_total"] == 0
    assert summary["slow_path_total"] == 0


def test_daily_update_does_not_wait_for_expired_market_cap_cache_when_cached_values_exist(tmp_path, monkeypatch):
    _write_stock_csv(tmp_path, "000001")
    _write_stock_csv(tmp_path, "600000")

    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 6, 16, 0, 0)

    monkeypatch.setattr(akshare_fetcher, "datetime", FakeDateTime)

    fetcher = AKShareFetcher(str(tmp_path))
    fetcher._market_cap_cache = {"000001": 1000000000, "600000": 1000000000}
    fetcher._market_cap_cache_date = "2026-03-01"

    def slow_market_cap_snapshot():
        time.sleep(0.6)
        return pd.DataFrame(
            [
                {"代码": "000001", "总市值": 1200000000, "今开": 11.0, "最新价": 11.5, "最高": 12.0, "最低": 10.8, "成交量": 2000, "成交额": 2300000.0, "换手率": 1.5},
                {"代码": "600000", "总市值": 1200000000, "今开": 11.0, "最新价": 11.5, "最高": 12.0, "最低": 10.8, "成交量": 2000, "成交额": 2300000.0, "换手率": 1.5},
            ]
        )

    monkeypatch.setattr(akshare_fetcher.ak, "stock_zh_a_spot_em", slow_market_cap_snapshot)

    monkeypatch.setattr(
        fetcher,
        "_fetch_spot_snapshot_map",
        lambda target_date_str, stock_codes=None: {
            code: {
                "date": target_date_str,
                "open": 11.0,
                "high": 12.0,
                "low": 10.8,
                "close": 11.5,
                "volume": 2000,
                "amount": 2300000.0,
                "turnover": 1.5,
                "market_cap": 1100000000,
            }
            for code in stock_codes
        },
    )

    started_at = time.perf_counter()
    summary = fetcher.daily_update(date="2026-05-06", allow_intraday_fast=False)
    elapsed = time.perf_counter() - started_at

    assert summary["status"] == "done"
    assert summary["fast_path_success"] == 2
    assert elapsed < 0.45
