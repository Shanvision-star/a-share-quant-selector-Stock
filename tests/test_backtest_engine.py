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
    """分钟级回测不能当天买当天卖，且只生成 OrderIntent，不触达券商实盘接口。"""
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
                MinuteBar("002100", pd.Timestamp("2026-04-28 14:55:00"), 8.00, 8.05, 7.98, 8.02, 1800, 1443600),
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
    assert result["trades"][0]["sell_datetime"] == "2026-04-28 14:55:00"
    assert result["trades"][0]["sell_date"] > result["trades"][0]["buy_date"]
    assert [item["side"] for item in result["order_intents"]] == ["BUY", "SELL"]
    assert all(item["status"] == "generated" for item in result["order_intents"])
    assert all(item["broker_order_id"] is None for item in result["order_intents"])


def test_daily_engine_blocks_st_and_limit_up_buy_and_rounds_lot_quantity():
    """A 股撮合先处理 ST/涨停禁买和 100 股整数手。"""
    candidates = [
        SignalCandidate(
            code="000001",
            name="平安银行",
            strategy_name="manual",
            trade_date="2026-04-24",
            signal_date="2026-04-24",
            source="manual",
        ),
        SignalCandidate(
            code="000002",
            name="*ST示例",
            strategy_name="manual",
            trade_date="2026-04-24",
            signal_date="2026-04-24",
            source="manual",
        ),
        SignalCandidate(
            code="000003",
            name="涨停示例",
            strategy_name="manual",
            trade_date="2026-04-24",
            signal_date="2026-04-24",
            source="manual",
        ),
    ]
    frames = {
        "000001": pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 10.2, "high": 10.6, "low": 10.1, "close": 10.5, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 10.6, "high": 10.8, "low": 10.4, "close": 10.7, "volume": 1000},
            ]
        ),
        "000002": pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 5.0, "high": 5.1, "low": 4.9, "close": 5.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 5.1, "high": 5.2, "low": 5.0, "close": 5.1, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 5.2, "high": 5.3, "low": 5.1, "close": 5.2, "volume": 1000},
            ]
        ),
        "000003": pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 11.1, "high": 11.2, "low": 10.9, "close": 11.0, "volume": 1000},
            ]
        ),
    }
    engine = BacktestEngine(
        signal_source=StaticSignalSource(candidates),
        daily_portal=InMemoryDailyDataPortal(frames),
    )

    result = engine.run_daily(_default_params(intent_quantity=185))

    assert result["summary"]["candidate_count"] == 3
    assert result["summary"]["trade_count"] == 1
    assert result["summary"]["skipped_count"] == 2
    assert result["trades"][0]["code"] == "000001"
    assert result["order_intents"][0]["quantity"] == 100


def test_daily_engine_skips_when_no_t_plus_one_sell_day():
    """日线窗口只有买入当天时应跳过，不能生成当天买当天卖的交易。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2026-04-24",
        signal_date="2026-04-24",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-27"), "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(simulation_end_date="2026-04-27"))

    assert result["summary"]["trade_count"] == 0
    assert result["summary"]["skipped_count"] == 1


def test_profit_runner_keeps_core_position_and_records_hold_action():
    """放飞后按阶梯卖出，但达到保留底仓比例后记录继续持有。"""
    candidate = SignalCandidate(
        code="002100",
        name="天康生物",
        strategy_name="manual",
        trade_date="2026-04-24",
        signal_date="2026-04-24",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.0, "low": 9.8, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 1000, "short_term_trend": 9.5},
            {"date": pd.Timestamp("2026-04-28"), "open": 10.2, "high": 14.0, "low": 10.1, "close": 13.8, "volume": 1000, "short_term_trend": 10.0},
            {"date": pd.Timestamp("2026-04-29"), "open": 13.8, "high": 14.2, "low": 13.5, "close": 14.0, "volume": 1000, "short_term_trend": 10.5},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"002100": frame}),
    )

    result = engine.run_daily(
        _default_params(
            holding_days=2,
            profit_run_enabled=True,
            profit_trigger_pct=5,
            profit_step_pct=10,
            profit_sell_pct=25,
            profit_keep_pct=50,
            hold_above_short_trend_after_trigger=True,
        )
    )

    trade = result["trades"][0]
    ladder_exits = [item for item in trade["exits"] if item["reason"].startswith("profit_ladder")]
    assert [item["portion_pct"] for item in ladder_exits] == [25.0, 25.0]
    assert any(action["action"] == "hold_core" for action in trade["profit_actions"])
