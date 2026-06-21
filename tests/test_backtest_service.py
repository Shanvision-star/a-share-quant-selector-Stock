import pandas as pd

from web.backend.services import backtest_service


def test_manual_same_day_signal_backtest_uses_future_bars(monkeypatch):
    """人工池按单日筛候选时，回测交易应继续使用信号日之后的行情。"""
    monkeypatch.setattr(
        backtest_service.manual_selection_service,
        "list_selections",
        lambda start_date, end_date: [
            {
                "selection_date": "2026-04-24",
                "code": "002100",
                "name": "天康生物",
                "strategy_name": "B1CaseAnalyzer",
                "source_signal_date": "2026-04-24",
                "source_trade_date": "2026-04-24",
            }
        ],
    )
    monkeypatch.setattr(
        backtest_service,
        "_load_price_frame",
        lambda code: pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 7.50, "high": 7.70, "low": 7.40, "close": 7.55, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 7.60, "high": 7.90, "low": 7.50, "close": 7.80, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 7.82, "high": 8.10, "low": 7.70, "close": 8.00, "volume": 1000},
            ]
        ),
    )

    result = backtest_service.run_backtest(
        {
            "start_date": "2026-04-24",
            "end_date": "2026-04-24",
            "source": "manual",
            "strategy": "all",
            "selected_codes": [],
            "selected_candidates": [],
            "input_codes": [],
            "holding_days": 1,
            "buy_offset_days": 1,
            "buy_price": "open",
            "sell_price": "close",
            "fee_rate": 0,
            "slippage_rate": 0,
            "take_profit_pct": 0,
            "stop_loss_pct": 0,
            "max_positions_per_day": 20,
            "codes_fallback_to_start_date": False,
            "profit_run_enabled": False,
            "enable_no_gain_exit": False,
            "exit_on_bull_bear_break": False,
            "exit_on_short_trend_break": False,
            "exit_on_short_trend_drawdown": False,
        }
    )

    assert result["summary"]["candidate_count"] == 1
    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["buy_date"] == "2026-04-27"
    assert result["trades"][0]["sell_date"] == "2026-04-28"


def test_backtest_service_returns_capital_summary_with_default_cash(monkeypatch):
    """旧请求不传 initial_cash 时，Phase B 账本字段也应存在。"""
    monkeypatch.setattr(
        backtest_service.manual_selection_service,
        "list_selections",
        lambda start_date, end_date: [
            {
                "selection_date": "2026-04-24",
                "code": "000001",
                "name": "平安银行",
                "strategy_name": "manual",
                "source_signal_date": "2026-04-24",
                "source_trade_date": "2026-04-24",
            }
        ],
    )
    monkeypatch.setattr(
        backtest_service,
        "_load_price_frame",
        lambda code: pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 10.5, "high": 10.8, "low": 10.4, "close": 10.5, "volume": 1000},
            ]
        ),
    )

    result = backtest_service.run_backtest(
        {
            "start_date": "2026-04-24",
            "end_date": "2026-04-24",
            "source": "manual",
            "strategy": "all",
            "selected_codes": [],
            "selected_candidates": [],
            "input_codes": [],
            "holding_days": 1,
            "buy_offset_days": 1,
            "buy_price": "open",
            "sell_price": "close",
            "fee_rate": 0,
            "slippage_rate": 0,
            "take_profit_pct": 0,
            "stop_loss_pct": 0,
            "max_positions_per_day": 20,
            "codes_fallback_to_start_date": False,
            "profit_run_enabled": False,
            "enable_no_gain_exit": False,
            "exit_on_bull_bear_break": False,
            "exit_on_short_trend_break": False,
            "exit_on_short_trend_drawdown": False,
        }
    )

    assert result["capital_summary"]["initial_cash"] == 100000.0
    assert result["capital_summary"]["invested_count"] == 1
    assert result["capital_summary"]["trade_count"] == 1
    assert result["equity_curve"][-1]["total_equity"] > 100000.0


def test_backtest_service_caches_daily_frame_for_duplicate_code(monkeypatch):
    """同一股票多条信号回测时，服务层应只读取一次日线行情。"""
    monkeypatch.setattr(
        backtest_service.manual_selection_service,
        "list_selections",
        lambda start_date, end_date: [
            {
                "selection_date": "2026-04-24",
                "code": "000001",
                "name": "平安银行",
                "strategy_name": "manual",
                "source_signal_date": "2026-04-24",
                "source_trade_date": "2026-04-24",
            },
            {
                "selection_date": "2026-04-25",
                "code": "000001",
                "name": "平安银行",
                "strategy_name": "manual",
                "source_signal_date": "2026-04-24",
                "source_trade_date": "2026-04-24",
            },
        ],
    )
    calls = {"count": 0}

    def load_price_frame(code):
        calls["count"] += 1
        return pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.3, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 10.3, "high": 10.6, "low": 10.2, "close": 10.5, "volume": 1000},
            ]
        )

    monkeypatch.setattr(backtest_service, "_load_price_frame", load_price_frame)

    result = backtest_service.run_backtest(
        {
            "start_date": "2026-04-24",
            "end_date": "2026-04-25",
            "source": "manual",
            "strategy": "all",
            "selected_codes": ["000001"],
            "selected_candidates": [],
            "input_codes": [],
            "holding_days": 1,
            "buy_offset_days": 1,
            "buy_price": "open",
            "sell_price": "close",
            "fee_rate": 0,
            "slippage_rate": 0,
            "take_profit_pct": 0,
            "stop_loss_pct": 0,
            "max_positions_per_day": 0,
            "codes_fallback_to_start_date": False,
            "profit_run_enabled": False,
            "enable_no_gain_exit": False,
            "exit_on_bull_bear_break": False,
            "exit_on_short_trend_break": False,
            "exit_on_short_trend_drawdown": False,
        }
    )

    assert result["summary"]["candidate_count"] == 2
    assert calls["count"] == 1


def test_backtest_service_reports_progress_per_candidate(monkeypatch):
    """真实回测服务应按候选处理进度回调，供异步任务写入进度表。"""
    monkeypatch.setattr(
        backtest_service.manual_selection_service,
        "list_selections",
        lambda start_date, end_date: [
            {
                "selection_date": "2026-04-24",
                "code": "000001",
                "name": "平安银行",
                "strategy_name": "manual",
                "source_signal_date": "2026-04-24",
                "source_trade_date": "2026-04-24",
            },
            {
                "selection_date": "2026-04-24",
                "code": "000002",
                "name": "万科A",
                "strategy_name": "manual",
                "source_signal_date": "2026-04-24",
                "source_trade_date": "2026-04-24",
            },
        ],
    )
    monkeypatch.setattr(
        backtest_service,
        "_load_price_frame",
        lambda code: pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.3, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 10.3, "high": 10.6, "low": 10.2, "close": 10.5, "volume": 1000},
            ]
        ),
    )
    events = []

    result = backtest_service.run_backtest(
        {
            "start_date": "2026-04-24",
            "end_date": "2026-04-24",
            "source": "manual",
            "strategy": "all",
            "selected_codes": [],
            "selected_candidates": [],
            "input_codes": [],
            "holding_days": 1,
            "buy_offset_days": 1,
            "buy_price": "open",
            "sell_price": "close",
            "fee_rate": 0,
            "slippage_rate": 0,
            "take_profit_pct": 0,
            "stop_loss_pct": 0,
            "max_positions_per_day": 20,
            "codes_fallback_to_start_date": False,
            "profit_run_enabled": False,
            "enable_no_gain_exit": False,
            "exit_on_bull_bear_break": False,
            "exit_on_short_trend_break": False,
            "exit_on_short_trend_drawdown": False,
        },
        progress_callback=events.append,
    )

    assert result["summary"]["candidate_count"] == 2
    assert events[-1]["processed_count"] == 2
    assert events[-1]["total_count"] == 2
    assert events[-1]["current_code"] == "000002"
