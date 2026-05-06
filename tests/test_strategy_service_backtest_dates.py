from datetime import datetime as real_datetime
import sqlite3

import pandas as pd

from web.backend.services import strategy_result_repository as repo
from web.backend.services import strategy_service


class AnalyzeOnlyStrategy:
    def calculate_indicators(self, df):
        return df

    def select_stocks(self, df, stock_name=''):
        return []

    def analyze_stock(self, stock_code, stock_name, df):
        return {
            'code': stock_code,
            'name': stock_name,
            'signals': [{'date': '2026-04-30', 'close': 10.0, 'category': 'b2_breakout'}],
        }


def _memory_strategy_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE strategy_runs (
            run_id TEXT PRIMARY KEY,
            run_type TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            strategy_filter TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'done',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            stage TEXT,
            message TEXT,
            processed_count INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            matched_count INTEGER DEFAULT 0,
            error_message TEXT,
            host TEXT
        );
        CREATE TABLE strategy_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            strategy_filter TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            category TEXT,
            signal_date TEXT,
            trigger_price REAL,
            close REAL,
            j_value REAL,
            similarity_score REAL,
            reason TEXT,
            signal_json TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_web_strategy_scan_uses_analyze_stock_even_when_select_stocks_is_empty():
    df = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=60)})
    hits = strategy_service._analyze_stock_multi_strategy(
        '000001',
        '测试股票',
        df,
        [('b2', 'B2Strategy', AnalyzeOnlyStrategy())],
    )

    assert hits['b2']['stock_result']['signals'][0]['category'] == 'b2_breakout'


def test_strategy_history_range_filters_by_signal_date(monkeypatch):
    conn = _memory_strategy_db()
    monkeypatch.setattr(repo, 'get_connection', lambda: conn)
    conn.execute(
        """INSERT INTO strategy_runs
           (run_id, run_type, trade_date, strategy_filter, status, started_at, completed_at)
           VALUES ('run-1', 'rebuild_only', '2026-05-06', 'b2', 'done', '2026-05-06 16:00:00', '2026-05-06 16:01:00')"""
    )
    conn.execute(
        """INSERT INTO strategy_results
           (run_id, trade_date, strategy_filter, strategy_name, code, name, category,
            signal_date, trigger_price, close, j_value, similarity_score, reason, signal_json, created_at)
           VALUES ('run-1', '2026-05-06', 'b2', 'B2Strategy', '000001', '测试股票',
                   'b2_breakout', '2026-04-30', 10, 10, 12, NULL, 'signal', NULL, '2026-05-06 16:01:00')"""
    )
    conn.commit()

    result = repo.query_results(
        strategy_filter='b2',
        start_date='2026-04-30',
        end_date='2026-04-30',
    )

    assert result['total'] == 1
    assert result['items'][0]['signal_date'] == '2026-04-30'


def test_latest_trade_date_skips_2026_may_day_holiday(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls):
            return real_datetime(2026, 5, 4, 10, 0, 0)

    monkeypatch.setattr(strategy_service, 'datetime', FakeDateTime)

    assert strategy_service.get_latest_trade_date() == '2026-04-30'


def test_price_frame_is_trimmed_to_as_of_date():
    df = pd.DataFrame({
        'date': ['2026-04-30', '2026-05-06'],
        'close': [10.0, 11.0],
    })

    trimmed = strategy_service._trim_price_frame_as_of(df, '2026-04-30')

    assert list(trimmed['date'].astype(str)) == ['2026-04-30']
