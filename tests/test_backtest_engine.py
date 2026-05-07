"""验证 backtest_engine 的核心边界：信号、行情、执行和下单意图分离。"""

import pandas as pd

from web.backend.backtest_engine.data_portal import InMemoryDailyDataPortal, InMemoryMinuteDataPortal
from web.backend.backtest_engine.engine import BacktestEngine
from web.backend.backtest_engine.models import BacktestParams, MinuteBar, SignalCandidate
from web.backend.backtest_engine.signal_source import StaticSignalSource


def _default_params(**overrides):
    params = {
        "start_date": "2026-04-24",
        "end_date": "2026-04-24",
        "holding_days": 1,
        "buy_offset_days": 1,
        "buy_price": "open",
        "sell_price": "close",
        "fee_rate": 0,
        "slippage_rate": 0,
        "take_profit_pct": 0,
        "stop_loss_pct": 0,
        "max_positions_per_day": 20,
        "profit_run_enabled": False,
        "enable_no_gain_exit": False,
        "exit_on_bull_bear_break": False,
        "exit_on_short_trend_break": False,
        "exit_on_short_trend_drawdown": False,
    }
    params.update(overrides)
    return BacktestParams.from_mapping(params)


def test_daily_engine_uses_future_price_window_after_same_day_signal():
    """start/end 只筛信号，交易模拟默认继续使用信号日之后的行情。"""
    candidate = SignalCandidate(
        code="002100",
        name="天康生物",
        strategy_name="B1CaseAnalyzer",
        trade_date="2026-04-24",
        signal_date="2026-04-24",
        source="manual",
    )
    daily_portal = InMemoryDailyDataPortal(
        {
            "002100": pd.DataFrame(
                [
                    {"date": pd.Timestamp("2026-04-24"), "open": 7.50, "high": 7.70, "low": 7.40, "close": 7.55},
                    {"date": pd.Timestamp("2026-04-27"), "open": 7.60, "high": 7.90, "low": 7.50, "close": 7.80},
                    {"date": pd.Timestamp("2026-04-28"), "open": 7.82, "high": 8.10, "low": 7.70, "close": 8.00},
                ]
            )
        }
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=daily_portal,
    )

    result = engine.run_daily(_default_params())

    assert result["summary"]["candidate_count"] == 1
    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["buy_date"] == "2026-04-27"
    assert result["trades"][0]["sell_date"] == "2026-04-28"
    assert result["order_intents"][0]["side"] == "BUY"
    assert result["order_intents"][0]["broker_order_id"] is None
    assert result["order_intents"][0]["status"] == "generated"


def test_minute_engine_generates_order_intents_without_live_order():
    """分钟级回测只生成 OrderIntent，再用分钟线做本地模拟，不触达券商实盘接口。"""
    candidate = SignalCandidate(
        code="002100",
        name="天康生物",
        strategy_name="B1CaseAnalyzer",
        trade_date="2026-04-24",
        signal_date="2026-04-24",
        source="manual",
    )
    minute_portal = InMemoryMinuteDataPortal(
        {
            "002100": [
                MinuteBar("002100", pd.Timestamp("2026-04-27 09:31:00"), 7.55, 7.60, 7.52, 7.58, 1000, 758000),
                MinuteBar("002100", pd.Timestamp("2026-04-27 09:35:00"), 7.60, 7.68, 7.58, 7.66, 2100, 1608600),
                MinuteBar("002100", pd.Timestamp("2026-04-27 14:55:00"), 7.90, 7.95, 7.88, 7.92, 1800, 1425600),
            ]
        }
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        minute_portal=minute_portal,
    )

    result = engine.run_minute(
        _default_params(
            timeframe="minute",
            minute_buy_time="09:35",
            minute_sell_time="14:55",
            intent_quantity=100,
        )
    )

    assert result["summary"]["candidate_count"] == 1
    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["buy_datetime"] == "2026-04-27 09:35:00"
    assert result["trades"][0]["sell_datetime"] == "2026-04-27 14:55:00"
    assert [item["side"] for item in result["order_intents"]] == ["BUY", "SELL"]
    assert all(item["status"] == "generated" for item in result["order_intents"])
    assert all(item["broker_order_id"] is None for item in result["order_intents"])
