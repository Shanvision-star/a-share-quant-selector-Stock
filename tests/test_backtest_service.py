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
                {"date": pd.Timestamp("2026-04-24"), "open": 7.50, "high": 7.70, "low": 7.40, "close": 7.55},
                {"date": pd.Timestamp("2026-04-27"), "open": 7.60, "high": 7.90, "low": 7.50, "close": 7.80},
                {"date": pd.Timestamp("2026-04-28"), "open": 7.82, "high": 8.10, "low": 7.70, "close": 8.00},
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
