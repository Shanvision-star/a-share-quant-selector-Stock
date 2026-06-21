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
                    {"date": pd.Timestamp("2026-04-27"), "open": 7.60, "high": 7.90, "low": 7.50, "close": 7.80, "volume": 1000},
                    {"date": pd.Timestamp("2026-04-28"), "open": 7.82, "high": 8.10, "low": 7.70, "close": 8.00, "volume": 1000},
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


def test_daily_engine_does_not_buy_when_calendar_target_bar_is_missing():
    """买入目标交易日缺行情时跳过，不能顺延到后续行情行假装成交。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2026-04-30",
        signal_date="2026-04-30",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-30"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-05-07"), "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1000},
            {"date": pd.Timestamp("2026-05-08"), "open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(start_date="2026-04-30", end_date="2026-04-30"))

    assert result["summary"]["trade_count"] == 0
    assert result["summary"]["skipped_count"] == 1


def test_daily_engine_buys_on_next_real_trading_day_after_holiday_gap():
    """买入延后一天应跳过五一假期，落到 2026-05-06。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2026-04-30",
        signal_date="2026-04-30",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-30"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-05-06"), "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1000},
            {"date": pd.Timestamp("2026-05-07"), "open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(start_date="2026-04-30", end_date="2026-04-30"))

    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["buy_date"] == "2026-05-06"
    assert result["trades"][0]["sell_date"] == "2026-05-07"


def test_daily_engine_does_not_buy_before_closed_signal_date():
    """闭市信号日不能被归一化到前一交易日买入，避免信号前成交。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2026-05-01",
        signal_date="2026-05-01",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-30"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-05-06"), "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1000},
            {"date": pd.Timestamp("2026-05-07"), "open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(
        _default_params(start_date="2026-05-01", end_date="2026-05-01", buy_offset_days=0)
    )

    assert result["summary"]["trade_count"] == 0
    assert result["summary"]["skipped_count"] == 1


def test_daily_engine_buys_after_2025_national_day_holiday_gap():
    """2025 历史回测也要按真实 A 股节假日推进买入日。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2025-09-30",
        signal_date="2025-09-30",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2025-09-30"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2025-10-09"), "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1000},
            {"date": pd.Timestamp("2025-10-10"), "open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(start_date="2025-09-30", end_date="2025-09-30"))

    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["buy_date"] == "2025-10-09"
    assert result["trades"][0]["sell_date"] == "2025-10-10"


def test_daily_engine_buys_after_2023_mid_autumn_national_day_holiday_gap():
    """2023 及更早历史窗口不能把节假日工作日误判为买入目标日。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2023-09-28",
        signal_date="2023-09-28",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2023-09-28"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2023-10-09"), "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1000},
            {"date": pd.Timestamp("2023-10-10"), "open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(start_date="2023-09-28", end_date="2023-09-28"))

    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["buy_date"] == "2023-10-09"
    assert result["trades"][0]["sell_date"] == "2023-10-10"


def test_daily_engine_skips_signal_outside_offline_calendar_window():
    """超出离线日历窗口的候选应跳过，不能让单个旧信号打断整次回测。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2015-12-31",
        signal_date="2015-12-31",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2015-12-31"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2016-01-04"), "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(start_date="2015-12-31", end_date="2015-12-31"))

    assert result["summary"]["trade_count"] == 0
    assert result["summary"]["skipped_count"] == 1


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


def test_daily_engine_requires_positive_volume_on_buy_day():
    """买入日没有明确正成交量时视为不可交易，避免停牌或坏数据被成交。"""
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
            name="无成交量示例",
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
                {"date": pd.Timestamp("2026-04-27"), "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 10.2, "high": 10.5, "low": 10.1, "close": 10.4, "volume": 1000},
            ]
        ),
        "000002": pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 8.0, "high": 8.2, "low": 7.9, "close": 8.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 8.1, "high": 8.3, "low": 8.0, "close": 8.2},
                {"date": pd.Timestamp("2026-04-28"), "open": 8.2, "high": 8.5, "low": 8.1, "close": 8.4, "volume": 1000},
            ]
        ),
    }
    engine = BacktestEngine(
        signal_source=StaticSignalSource(candidates),
        daily_portal=InMemoryDailyDataPortal(frames),
    )

    result = engine.run_daily(_default_params())

    assert result["summary"]["trade_count"] == 1
    assert result["summary"]["skipped_count"] == 1
    assert result["trades"][0]["code"] == "000001"


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


def test_daily_engine_delays_stop_loss_exit_when_limit_down_locked():
    """止损触发日跌停锁死时，应顺延到下一可卖日，不能按止损价虚假成交。"""
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
            {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-28"), "open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-29"), "open": 9.1, "high": 9.4, "low": 9.0, "close": 9.2, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(holding_days=2, stop_loss_pct=5))

    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["sell_date"] == "2026-04-29"
    assert result["trades"][0]["sell_price"] == 9.2
    assert result["trades"][0]["exit_reason"] == "fixed_stop_loss"
    trade = result["trades"][0]
    assert len(trade["exits"]) == 1
    assert trade["exits"][0]["portion_pct"] == 100.0


def test_daily_engine_uses_prior_tradeable_close_for_limit_down_delay():
    """前一行坏数据不能污染跌停价计算，导致锁死跌停日被误判可卖。"""
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
            {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-28"), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            {"date": pd.Timestamp("2026-04-29"), "open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-30"), "open": 9.1, "high": 9.4, "low": 9.0, "close": 9.2, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(holding_days=3, stop_loss_pct=5))

    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["sell_date"] == "2026-04-30"
    assert result["trades"][0]["sell_price"] == 9.2


def test_daily_engine_uses_prior_tradeable_close_for_limit_up_buy_block():
    """买入日涨停判断不能被前一行无量坏收盘价绕过。"""
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
            {"date": pd.Timestamp("2026-04-25"), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            {"date": pd.Timestamp("2026-04-27"), "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-28"), "open": 11.1, "high": 11.2, "low": 10.9, "close": 11.0, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params())

    assert result["summary"]["trade_count"] == 0
    assert result["summary"]["skipped_count"] == 1


def test_daily_engine_ignores_untradeable_exit_trigger_day():
    """无量或停牌日的价格不能触发止损，再顺延成虚假成交。"""
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
            {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-28"), "open": 9.0, "high": 9.1, "low": 9.0, "close": 9.0},
            {"date": pd.Timestamp("2026-04-29"), "open": 10.1, "high": 10.5, "low": 10.0, "close": 10.4, "volume": 1000},
            {"date": pd.Timestamp("2026-04-30"), "open": 10.4, "high": 10.8, "low": 10.2, "close": 10.6, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(holding_days=3, stop_loss_pct=5))

    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["sell_date"] == "2026-04-30"
    assert result["trades"][0]["exit_reason"] == "holding_days"


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


def test_profit_runner_delays_ladder_exit_when_limit_down_locked():
    """Profit Runner 阶梯减仓触发日不可卖时，应使用实际可卖日和价格。"""
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
            {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.0, "low": 9.8, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 13.5, "low": 9.9, "close": 13.33, "volume": 1000, "short_term_trend": 9.5},
            {"date": pd.Timestamp("2026-04-28"), "open": 12.0, "high": 12.0, "low": 12.0, "close": 12.0, "volume": 1000, "short_term_trend": 8.5},
            {"date": pd.Timestamp("2026-04-29"), "open": 11.2, "high": 11.49, "low": 11.1, "close": 11.3, "volume": 1000, "short_term_trend": 8.7},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(
        _default_params(
            holding_days=2,
            profit_run_enabled=True,
            profit_trigger_pct=5,
            profit_step_pct=5,
            profit_sell_pct=25,
            profit_keep_pct=50,
            hold_above_short_trend_after_trigger=False,
        )
    )

    trade = result["trades"][0]
    ladder_exits = [item for item in trade["exits"] if item["reason"].startswith("profit_ladder")]
    assert ladder_exits[0]["date"] == "2026-04-29"
    assert ladder_exits[0]["price"] == 11.3
    assert any(action["action"] == "sell_partial" and action["date"] == "2026-04-29" for action in trade["profit_actions"])
    assert sum(item["portion_pct"] for item in trade["exits"]) <= 100.0
    assert [item["reason"] for item in trade["exits"]] == ["profit_ladder_10.0pct", "holding_days"]
    assert [item["date"] for item in trade["exits"]] == ["2026-04-29", "2026-04-29"]
    assert [item["portion_pct"] for item in trade["exits"]] == [25.0, 75.0]


def test_profit_runner_ignores_untradeable_trigger_day():
    """无量或停牌日的高点不能触发 Profit Runner 动作。"""
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
            {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.0, "low": 9.8, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000, "short_term_trend": 9.5},
            {"date": pd.Timestamp("2026-04-28"), "open": 13.0, "high": 14.0, "low": 12.8, "close": 13.5, "short_term_trend": 9.5},
            {"date": pd.Timestamp("2026-04-29"), "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.3, "volume": 1000, "short_term_trend": 9.5},
            {"date": pd.Timestamp("2026-04-30"), "open": 10.3, "high": 10.49, "low": 10.2, "close": 10.4, "volume": 1000, "short_term_trend": 9.5},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(
        _default_params(
            holding_days=3,
            profit_run_enabled=True,
            profit_trigger_pct=5,
            profit_step_pct=5,
            profit_sell_pct=25,
            hold_above_short_trend_after_trigger=False,
        )
    )

    trade = result["trades"][0]
    assert trade["exit_reason"] == "holding_days"
    assert trade["profit_actions"] == []
    assert all(not item["reason"].startswith("profit_ladder") for item in trade["exits"])


def test_engine_limits_single_code_signals_before_execution():
    """单只股票长区间命中太多时，应先截断信号，避免单股策略回测拖慢接口。"""
    candidates = [
        SignalCandidate(
            code="000001",
            name="平安银行",
            strategy_name="manual",
            trade_date=f"2026-04-{24 + index:02d}",
            signal_date=f"2026-04-{24 + index:02d}",
            source="manual",
        )
        for index in range(5)
    ]
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-27"), "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 1000},
            {"date": pd.Timestamp("2026-04-28"), "open": 10.2, "high": 10.5, "low": 10.1, "close": 10.4, "volume": 1000},
            {"date": pd.Timestamp("2026-04-29"), "open": 10.4, "high": 10.6, "low": 10.2, "close": 10.5, "volume": 1000},
            {"date": pd.Timestamp("2026-04-30"), "open": 10.5, "high": 10.8, "low": 10.4, "close": 10.7, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource(candidates),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(max_positions_per_day=0, max_signals_per_code=2))

    assert result["summary"]["raw_candidate_count"] == 5
    assert result["summary"]["candidate_count"] == 2
    assert result["runtime"]["candidate_limit_applied"] is True
    assert any("单股信号上限" in message for message in result["runtime"]["warnings"])


def test_daily_engine_stops_when_runtime_budget_is_exhausted():
    """运行预算耗尽后停止继续处理候选，避免长任务拖住前端请求。"""
    class SlowPortal:
        def __init__(self):
            self.frame = pd.DataFrame(
                [
                    {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                    {"date": pd.Timestamp("2026-04-27"), "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 1000},
                    {"date": pd.Timestamp("2026-04-28"), "open": 10.2, "high": 10.5, "low": 10.1, "close": 10.4, "volume": 1000},
                ]
            )

        def get_daily_frame(self, code):
            import time

            time.sleep(0.003)
            return self.frame.copy()

    candidates = [
        SignalCandidate(
            code=f"00000{index}",
            name=f"测试{index}",
            strategy_name="manual",
            trade_date="2026-04-24",
            signal_date="2026-04-24",
            source="manual",
        )
        for index in range(1, 6)
    ]
    engine = BacktestEngine(
        signal_source=StaticSignalSource(candidates),
        daily_portal=SlowPortal(),
    )

    result = engine.run_daily(_default_params(max_runtime_seconds=0.001, max_positions_per_day=0))

    assert result["runtime"]["stopped_early"] is True
    assert result["summary"]["runtime_stopped_early"] is True
    assert result["summary"]["runtime_processed_count"] < result["summary"]["candidate_count"]
