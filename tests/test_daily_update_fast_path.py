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
