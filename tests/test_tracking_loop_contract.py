"""验证 Tracking Agent Loop MVP 的后端闭环合同。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from web.backend.services.tracking_alert_service import TrackingAlertService
from web.backend.services.tracking_evaluation_service import TrackingEvaluationService
from web.backend.services.tracking_llm_service import TrackingLLMService
from web.backend.services.tracking_service import TrackingService


def _memory_connection():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _breakdown_frame() -> pd.DataFrame:
    start = datetime(2026, 1, 1)
    dates = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(200)]
    closes = [round(10.0 + i * 0.1, 2) for i in range(200)]
    closes[-3:] = [5.0, 4.5, 4.0]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * 200,
        }
    )


class _TemplateService:
    def build_engine_inputs(self) -> dict:
        return {"params_overrides": {}, "enabled_rules": None}


def test_tracking_loop_evaluate_alert_advice_confirm_and_ignore(monkeypatch) -> None:
    from web.backend.services import tracking_llm_service as llm_mod

    monkeypatch.setattr(llm_mod, "load_llm_config", lambda: {"provider": "mock"})
    monkeypatch.setattr(
        llm_mod.zettaranc_adapter,
        "prepare_context",
        lambda code, days=60: {"source": "local_csv", "text": "FAKE", "error": None},
    )

    conn = _memory_connection()
    tracking = TrackingService(connection_factory=lambda: conn, daily_loader=lambda code: _breakdown_frame())
    alerts = TrackingAlertService(connection_factory=lambda: conn)
    evaluator = TrackingEvaluationService(
        tracking_service=tracking,
        template_service=_TemplateService(),
        alert_service=alerts,
        frame_loader=lambda code: _breakdown_frame(),
    )
    llm = TrackingLLMService()

    item = tracking.create_item(
        {
            "code": "000559",
            "name": "万向钱潮",
            "strategy_name": "manual",
            "source": "manual",
            "source_date": "2026-05-01",
            "signal_date": "2026-01-10",
        }
    )

    summary = evaluator.evaluate_active_items(eval_date="2026-07-19")
    alert = alerts.list_alerts(tracking_id=item["tracking_id"])[0]
    advice = llm.propose_action(item, [alert], profile="zettaranc_style")
    confirmed = tracking.confirm_intent(item["tracking_id"], advice["suggested_intent"])
    ignored = alerts.update_alert_status(alert["alert_id"], "ignored")
    events = tracking.list_events(item["tracking_id"])

    assert summary["alerts_created"] >= 1
    assert advice["profile"] == "zettaranc_style"
    assert advice["zettaranc_data_source"] == "local_csv"
    assert confirmed["latest_intent"] == advice["suggested_intent"]
    assert ignored["ui_status"] == "ignored"
    assert events[-1]["event_type"] == "intent_confirmed"
