"""验证单股跟踪服务：建仓跟踪、事件流和买入意图生成。"""

import sqlite3

import pandas as pd

from web.backend.services.tracking_service import TrackingService


def _memory_connection():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _daily_loader(code: str) -> pd.DataFrame:
    assert code == "000559"
    return pd.DataFrame(
        [
            {"date": "2026-04-30", "open": 15.80, "high": 16.10, "low": 15.60, "close": 15.90, "volume": 1000},
            {"date": "2026-05-06", "open": 16.09, "high": 16.80, "low": 16.00, "close": 16.50, "volume": 1000},
            {"date": "2026-05-07", "open": 16.70, "high": 17.30, "low": 16.60, "close": 17.20, "volume": 1000},
        ]
    )


def _runner_daily_loader(code: str) -> pd.DataFrame:
    assert code == "000559"
    return pd.DataFrame(
        [
            {"date": "2026-04-30", "open": 10.00, "high": 10.10, "low": 9.90, "close": 10.00, "volume": 1000},
            {"date": "2026-05-06", "open": 10.00, "high": 10.20, "low": 9.90, "close": 10.10, "volume": 1000},
            {"date": "2026-05-07", "open": 10.40, "high": 10.70, "low": 10.30, "close": 10.60, "volume": 1000},
            {"date": "2026-05-08", "open": 11.40, "high": 11.80, "low": 11.30, "close": 11.60, "volume": 1000},
        ]
    )


def test_tracking_service_creates_watch_item_and_event():
    """从人工选股或回测结果加入跟踪后，应持久化 watch_buy 状态和事件。"""
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_daily_loader)

    item = service.create_item(
        {
            "code": "000559",
            "name": "万向钱潮",
            "strategy_name": "BowlReboundStrategy",
            "source": "manual",
            "source_date": "2026-05-01",
            "signal_date": "2026-04-30",
            "params": {"buy_offset_days": 1, "buy_price": "open", "intent_quantity": 200},
        }
    )
    events = service.list_events(item["tracking_id"])

    assert item["tracking_id"].startswith("trk_")
    assert item["status"] == "watch_buy"
    assert item["code"] == "000559"
    assert item["params"]["buy_offset_days"] == 1
    assert events[0]["event_type"] == "created"
    assert events[0]["payload"]["code"] == "000559"


def test_tracking_service_evaluates_watch_item_into_buy_intent():
    """到达买入交易日后，跟踪服务应生成 BUY 意图并进入 holding。"""
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_daily_loader)
    item = service.create_item(
        {
            "code": "000559",
            "name": "万向钱潮",
            "strategy_name": "BowlReboundStrategy",
            "source": "backtest",
            "source_date": "2026-05-01",
            "signal_date": "2026-04-30",
            "params": {"buy_offset_days": 1, "buy_price": "open", "intent_quantity": 250, "lot_size": 100},
        }
    )

    evaluated = service.evaluate_item(item["tracking_id"], "2026-05-06")
    events = service.list_events(item["tracking_id"])

    assert evaluated["status"] == "holding"
    assert evaluated["entry_date"] == "2026-05-06"
    assert evaluated["entry_price"] == 16.09
    assert evaluated["next_action"] == "BUY"
    assert evaluated["latest_intent"]["side"] == "BUY"
    assert evaluated["latest_intent"]["quantity"] == 200
    assert events[-1]["event_type"] == "buy_signal"
    assert events[-1]["payload"]["intent"]["broker_order_id"] is None


def test_tracking_service_profit_runner_waits_for_ladder_before_partial_sell():
    """放飞触发后先进入跟踪状态，达到阶梯涨幅才生成部分卖出建议。"""
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_runner_daily_loader)
    item = service.create_item(
        {
            "code": "000559",
            "name": "万向钱潮",
            "strategy_name": "BowlReboundStrategy",
            "source": "manual",
            "source_date": "2026-05-01",
            "signal_date": "2026-04-30",
            "params": {
                "buy_offset_days": 1,
                "buy_price": "open",
                "intent_quantity": 400,
                "profit_run_enabled": True,
                "profit_trigger_pct": 5,
                "profit_step_pct": 10,
                "profit_sell_pct": 25,
                "profit_keep_pct": 50,
            },
        }
    )
    service.evaluate_item(item["tracking_id"], "2026-05-06")

    runner = service.evaluate_item(item["tracking_id"], "2026-05-07")
    evaluated = service.evaluate_item(item["tracking_id"], "2026-05-08")

    assert runner["status"] == "holding"
    assert runner["next_action"] == "HOLD_RUNNER"
    assert runner["remaining_pct"] == 100
    assert runner["latest_intent"] is None
    assert runner["params"]["runner_triggered"] is True
    assert runner["params"]["next_profit_ladder_pct"] == 15
    assert evaluated["status"] == "partial_sold"
    assert evaluated["next_action"] == "SELL_PARTIAL"
    assert evaluated["remaining_pct"] == 75
    assert evaluated["latest_return_pct"] > 15
    assert evaluated["latest_intent"]["side"] == "SELL"
    assert evaluated["params"]["next_profit_ladder_pct"] == 25


def test_tracking_service_same_day_evaluation_is_idempotent():
    """同一评估日重复点击评估时，不能重复生成卖出建议或继续扣减剩余仓位。"""
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_runner_daily_loader)
    item = service.create_item(
        {
            "code": "000559",
            "name": "万向钱潮",
            "strategy_name": "BowlReboundStrategy",
            "source": "manual",
            "source_date": "2026-05-01",
            "signal_date": "2026-04-30",
            "params": {
                "buy_offset_days": 1,
                "buy_price": "open",
                "intent_quantity": 400,
                "profit_run_enabled": True,
                "profit_trigger_pct": 5,
                "profit_step_pct": 10,
                "profit_sell_pct": 25,
                "profit_keep_pct": 50,
            },
        }
    )
    service.evaluate_item(item["tracking_id"], "2026-05-06")
    service.evaluate_item(item["tracking_id"], "2026-05-07")
    first = service.evaluate_item(item["tracking_id"], "2026-05-08")

    second = service.evaluate_item(item["tracking_id"], "2026-05-08")

    assert first["remaining_pct"] == 75
    assert second["remaining_pct"] == 75
    assert second["latest_intent"]["intent_id"] == first["latest_intent"]["intent_id"]
