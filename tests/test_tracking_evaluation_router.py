"""P5 跟踪规则评估编排路由器测试。"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_frame() -> pd.DataFrame:
    """末段急跌的升序数据，确保至少触发一条短线告警。"""
    days = 200
    closes = [round(10.0 + i * 0.1, 2) for i in range(days)]
    closes[-3:] = [5.0, 4.5, 4.0]
    dates = pd.date_range("2026-01-01", periods=days).strftime("%Y-%m-%d").tolist()
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * days,
        }
    )


@pytest.fixture
def client(monkeypatch):
    import sqlite3

    from web.backend.routers import tracking_evaluation as router_module
    from web.backend.services.tracking_alert_service import TrackingAlertService
    from web.backend.services.tracking_evaluation_service import TrackingEvaluationService

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    alert_svc = TrackingAlertService(connection_factory=lambda: conn)

    class _Tracking:
        def list_items(self, status=None, code=None, limit=100):
            base = [
                {
                    "tracking_id": "trk_a",
                    "code": "000001",
                    "status": "holding",
                    "signal_date": "2026-01-10",
                }
            ]
            if status in (None, "all", "holding"):
                return base
            return []

    class _Template:
        def build_engine_inputs(self):
            return {"params_overrides": {}, "enabled_rules": None}

    svc = TrackingEvaluationService(
        tracking_service=_Tracking(),
        template_service=_Template(),
        alert_service=alert_svc,
        frame_loader=lambda code: _make_frame(),
    )
    monkeypatch.setattr(router_module, "tracking_evaluation_service", svc)

    app = FastAPI()
    app.include_router(router_module.router)
    return TestClient(app)


def test_evaluate_endpoint_returns_summary(client) -> None:
    resp = client.post("/api/tracking/evaluate-rules", json={"eval_date": "2026-07-19"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["evaluated"] == 1
    assert data["alerts_created"] >= 1


def test_evaluate_endpoint_without_body(client) -> None:
    # 空 body 默认 eval_date=None → 引擎兜底为今日
    resp = client.post("/api/tracking/evaluate-rules")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
