"""K 线服务性能路径测试。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from web.backend.services import kline_service


class _FakePath:
    def __init__(self, mtime_ns: int = 1):
        self.mtime_ns = mtime_ns

    def exists(self) -> bool:
        return True

    def stat(self):
        # 同时补齐 st_size，避免后台指标快照线程（stock.py:_read_stock_preview）
        # 借道 csv_manager.get_stock_path 拿到本假 Path 时抛 AttributeError 噪声。
        class _Stat:
            pass

        stat = _Stat()
        stat.st_mtime_ns = self.mtime_ns
        stat.st_size = 1
        return stat


def _sample_daily_frame(rows: int = 600) -> pd.DataFrame:
    start = datetime(2024, 1, 1)
    dates = [start + timedelta(days=i) for i in range(rows)]
    return pd.DataFrame({
        "date": list(reversed(dates)),
        "open": [10 + i * 0.01 for i in range(rows)],
        "high": [10.5 + i * 0.01 for i in range(rows)],
        "low": [9.8 + i * 0.01 for i in range(rows)],
        "close": [10.2 + i * 0.01 for i in range(rows)],
        "volume": [100000 + i for i in range(rows)],
        "amount": [1000000 + i for i in range(rows)],
        "turnover": [1.0 for _ in range(rows)],
        "market_cap": [1000000000 for _ in range(rows)],
    })


def _clear_qfq_cache_if_present():
    cache = getattr(kline_service, "_QFQ_KLINE_CACHE", None)
    if cache is not None:
        cache.clear()


def test_daily_qfq_limit_500_reads_only_needed_csv_rows(monkeypatch):
    _clear_qfq_cache_if_present()
    calls = []

    def fake_read_stock(code, **kwargs):
        calls.append(kwargs)
        return _sample_daily_frame(kwargs.get("nrows") or 600)

    monkeypatch.setattr(kline_service.csv_manager, "read_stock", fake_read_stock)
    monkeypatch.setattr(kline_service.csv_manager, "get_stock_path", lambda code: _FakePath())

    result = kline_service.get_kline("000001", period="daily", limit=500, adjust="qfq")

    assert result is not None
    assert len(result["bars"]) == 500
    assert calls[0].get("nrows") == 500


def test_daily_qfq_cache_reuses_response_until_csv_mtime_changes(monkeypatch):
    _clear_qfq_cache_if_present()
    path = _FakePath(mtime_ns=100)
    read_count = 0

    def fake_read_stock(code, **kwargs):
        nonlocal read_count
        read_count += 1
        return _sample_daily_frame(kwargs.get("nrows") or 600)

    monkeypatch.setattr(kline_service.csv_manager, "read_stock", fake_read_stock)
    monkeypatch.setattr(kline_service.csv_manager, "get_stock_path", lambda code: path)

    first = kline_service.get_kline("000001", period="daily", limit=500, adjust="qfq")
    second = kline_service.get_kline("000001", period="daily", limit=500, adjust="qfq")
    path.mtime_ns = 200
    third = kline_service.get_kline("000001", period="daily", limit=500, adjust="qfq")

    assert first is second
    assert third is not second
    assert read_count == 2


def test_weekly_qfq_does_not_use_daily_500_row_short_read(monkeypatch):
    _clear_qfq_cache_if_present()
    calls = []

    def fake_read_stock(code, **kwargs):
        calls.append(kwargs)
        return _sample_daily_frame(900)

    monkeypatch.setattr(kline_service.csv_manager, "read_stock", fake_read_stock)
    monkeypatch.setattr(kline_service.csv_manager, "get_stock_path", lambda code: _FakePath())

    result = kline_service.get_kline("000001", period="weekly", limit=500, adjust="qfq")

    assert result is not None
    assert calls[0].get("nrows") is None
