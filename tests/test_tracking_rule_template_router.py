"""P3 跟踪规则模板 REST 接口测试。

策略：通过 FastAPI TestClient + 模板服务的内存 SQLite 单例替换，验证 CRUD 行为。
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.routers import tracking_rule_template as router_module
from web.backend.services.tracking_rule_templates import TrackingRuleTemplateService


@pytest.fixture
def client(monkeypatch) -> TestClient:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    svc = TrackingRuleTemplateService(connection_factory=lambda: conn)
    # 替换 router 引用的模块级单例，隔离生产数据库。
    monkeypatch.setattr(router_module, "tracking_rule_template_service", svc)

    app = FastAPI()
    app.include_router(router_module.router)
    return TestClient(app)


def test_get_rule_meta_returns_engine_registry(client: TestClient) -> None:
    resp = client.get("/api/tracking/rule-templates/rules")
    assert resp.status_code == 200
    rules = resp.json()["data"]["rules"]
    assert any(r["rule_id"] == "rule_break_short_trend" for r in rules)
    for rule in rules:
        assert {"rule_id", "name", "category", "priority", "action_label", "default_params"} <= rule.keys()


def test_create_list_get_update_delete_cycle(client: TestClient) -> None:
    # create
    resp = client.post(
        "/api/tracking/rule-templates",
        json={
            "name": "稳健",
            "rule_id": "rule_break_short_trend",
            "params": {"tolerance_pct": 1.5},
            "enabled": True,
        },
    )
    assert resp.status_code == 200, resp.text
    template_id = resp.json()["data"]["template_id"]

    # list
    listed = client.get("/api/tracking/rule-templates").json()["data"]["items"]
    assert len(listed) == 1
    assert listed[0]["template_id"] == template_id

    # get
    got = client.get(f"/api/tracking/rule-templates/{template_id}").json()["data"]
    assert got["params"] == {"tolerance_pct": 1.5}

    # update
    upd = client.put(
        f"/api/tracking/rule-templates/{template_id}",
        json={"enabled": False, "params": {"tolerance_pct": 2.0}},
    )
    assert upd.status_code == 200
    assert upd.json()["data"]["enabled"] is False
    assert upd.json()["data"]["params"] == {"tolerance_pct": 2.0}

    # delete
    delete = client.delete(f"/api/tracking/rule-templates/{template_id}")
    assert delete.status_code == 200
    # second delete → 404
    assert client.delete(f"/api/tracking/rule-templates/{template_id}").status_code == 404


def test_create_unknown_rule_returns_400(client: TestClient) -> None:
    resp = client.post(
        "/api/tracking/rule-templates",
        json={"name": "x", "rule_id": "rule_ghost", "params": {}},
    )
    assert resp.status_code == 400


def test_update_missing_returns_404(client: TestClient) -> None:
    resp = client.put(
        "/api/tracking/rule-templates/not_exists",
        json={"enabled": False},
    )
    assert resp.status_code == 404
