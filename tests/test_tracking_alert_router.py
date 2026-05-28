"""P4 跟踪告警 REST 接口测试。"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.routers import tracking_alert as router_module
from web.backend.services.tracking_alert_service import TrackingAlertService


class _RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict]]] = []

    def send(self, slot: str, alerts) -> None:
        self.calls.append((slot, list(alerts)))


@pytest.fixture
def env(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    notifier = _RecordingNotifier()
    svc = TrackingAlertService(connection_factory=lambda: conn, notifier=notifier)
    monkeypatch.setattr(router_module, "tracking_alert_service", svc)

    app = FastAPI()
    app.include_router(router_module.router)
    client = TestClient(app)
    return client, svc, notifier


def _seed(svc: TrackingAlertService) -> None:
    svc.persist_alerts(
        [
            {
                "tracking_id": "t1",
                "rule_id": "rule_break_short_trend",
                "code": "000001",
                "eval_date": "2026-05-01",
                "priority": 10,
                "category": "short_term",
                "action_label": "TREND_BREAK",
                "name": "短线跌破",
                "message": "测试",
                "evidence": {"a": 1},
                "dedup_key": "t1|rule_break_short_trend|2026-05-01",
            },
            {
                "tracking_id": "t2",
                "rule_id": "rule_long_dead_cross",
                "code": "000002",
                "eval_date": "2026-05-01",
                "priority": 70,
                "category": "long_term",
                "action_label": "TREND_BREAK",
                "name": "长线死叉",
                "message": "测试",
                "evidence": {"b": 2},
                "dedup_key": "t2|rule_long_dead_cross|2026-05-01",
            },
        ]
    )


def test_list_alerts_returns_seeded(env) -> None:
    client, svc, _ = env
    _seed(svc)
    resp = client.get("/api/tracking/alerts")
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 2


def test_list_alerts_filters_by_tracking_id(env) -> None:
    client, svc, _ = env
    _seed(svc)
    resp = client.get("/api/tracking/alerts", params={"tracking_id": "t1"})
    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["tracking_id"] == "t1"


def test_dispatch_endpoint_routes_priority_tiers(env) -> None:
    client, svc, notifier = env
    _seed(svc)
    resp = client.post("/api/tracking/alerts/dispatch", params={"slot": "09:00"})
    assert resp.status_code == 200
    summary = resp.json()["data"]
    # P10 必发；P70 聚合
    assert summary["dispatched"] == 1
    assert summary["aggregated"] == 1
    assert len(notifier.calls) == 1
    assert notifier.calls[0][0] == "09:00"


def test_dispatch_endpoint_requires_slot(env) -> None:
    client, _, _ = env
    resp = client.post("/api/tracking/alerts/dispatch")
    # 缺少必填 slot 参数应返回 422
    assert resp.status_code == 422
