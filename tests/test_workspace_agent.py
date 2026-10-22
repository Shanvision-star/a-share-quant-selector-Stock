"""研究 Agent 的状态竞争、证据校验、权限与追加幂等回归，不调用真实模型。"""

import json
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from web.backend.services import sqlite_service as db
from web.backend.services import workspace_agent as module
from web.backend.routers import workspace_agent as routes
from web.backend.services.desktop_auth import DesktopAuthMiddleware
from web.backend.services.review_repository import ReviewDocument, ReviewRepository


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "cache.db")
    monkeypatch.setattr(db, "_local", threading.local())
    monkeypatch.setattr(module, "ROOT", tmp_path)
    db.init_database()
    instance = module.WorkspaceAgent()
    instance.store.init()
    monkeypatch.setattr(routes, "workspace_agent", instance)
    yield instance
    instance.pool.shutdown(wait=True)


def finish(agent, run):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = agent.store.get(run["run_id"])
        if current["status"] not in ("queued", "running"):
            return current
        time.sleep(.01)
    pytest.fail("run did not finish")


def test_local_report_real_evidence_and_reload(agent):
    run = finish(agent, agent.submit(module.AgentRequest(question="整理跟踪", task="tracking")))
    assert run["status"] == "completed"
    assert run["provider"] == "local" and run["usage"] is None
    assert run["sources"][0]["data"]["total"] == 0
    assert len(run["sources"][0]["sha256"]) == 64
    assert module.AgentStore().get(run["run_id"]) == run
    assert run["agent_name"] and run["prompt_version"]


def test_model_bad_source_fails_but_keeps_usage(agent, monkeypatch):
    monkeypatch.setattr(module, "load_llm_config", lambda: {"provider": "deepseek"})
    monkeypatch.setattr(module, "call_model", lambda *_: ({"summary": "摘要", "findings": [{"text": "缺少证据", "source_ids": ["S404"]}], "next_steps": [], "limitations": []}, {"provider": "test", "model": "stub", "usage": {"total_tokens": 21}, "cost": None}))
    run = finish(agent, agent.submit(module.AgentRequest(question="检查", task="tracking", mode="model")))
    assert run["status"] == "failed" and run["output"] is None
    assert run["usage"]["total_tokens"] == 21
    assert "不存在" in run["error"]


def test_cancel_wins_over_late_model_completion(agent, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def provider(*_):
        entered.set()
        release.wait(3)
        return {"summary": "稍后返回", "findings": [], "next_steps": [], "limitations": []}, {"provider": "test", "usage": {"total_tokens": 8}}
    monkeypatch.setattr(module, "call_model", provider)
    run = agent.submit(module.AgentRequest(question="检查", task="tracking", mode="model"))
    assert entered.wait(3)
    agent.store.patch(run["run_id"], active_only=True, status="cancelled")
    release.set()
    agent.pool.shutdown(wait=True)
    current = agent.store.get(run["run_id"])
    assert current["status"] == "cancelled" and current["output"] is None
    assert current["usage"]["total_tokens"] == 8


def test_restart_marks_unfinished(agent):
    run = agent.store.create(module.AgentRequest(question="整理"))
    agent.store.patch(run["run_id"], owner_pid=-1)
    agent.store.init(recover=True)
    assert agent.store.get(run["run_id"])["status"] == "interrupted"


def test_second_backend_preserves_live_owner(agent):
    run = agent.store.create(module.AgentRequest(question="整理"))
    agent.store.init(recover=True)
    assert agent.store.get(run["run_id"])["status"] == "queued"


def test_confirm_required_and_review_append_is_idempotent(agent):
    repository = ReviewRepository(module.ROOT / "data" / "review_library")
    from dataclasses import replace
    repository.create_if_absent(replace(ReviewDocument.new("2026-10-23"), body="# 原有复盘\n\n保留这段内容。"))
    run = finish(agent, agent.submit(module.AgentRequest(question="整理", task="tracking")))
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        endpoint = f"/api/agent/runs/{run['run_id']}/review"
        assert client.post(endpoint, json={"review_date": "2026-10-23"}).status_code == 409
        assert "agent-run" not in repository.load("2026-10-23").body
        first = client.post(endpoint, json={"review_date": "2026-10-23", "confirmed": True})
        second = client.post(endpoint, json={"review_date": "2026-10-23", "confirmed": True})
        assert first.status_code == second.status_code == 200
        assert second.json()["already_saved"]
        body = repository.load("2026-10-23").body
        assert "保留这段内容" in body and body.count(f"<!-- agent-run:{run['run_id']} -->") == 1


def test_desktop_auth_and_validation(agent, monkeypatch):
    monkeypatch.setenv("QUANT_DESKTOP_TOKEN", "a" * 64)
    app = FastAPI()
    app.add_middleware(DesktopAuthMiddleware)
    app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.get("/api/agent/runs").status_code == 401
        headers = {"X-Quant-Token": "a" * 64}
        assert client.get("/api/agent/runs", headers=headers).status_code == 200
        for bad in ({"question": "q", "code": "../secrets"}, {"question": "q", "limit": 999}, {"question": "q", "shell": "cmd"}):
            assert client.post("/api/agent/runs", headers=headers, json=bad).status_code == 422
        assert client.get("/api/agent/runs/missing", headers=headers).status_code == 404


def test_failure_does_not_fallback_to_fake_success(agent, monkeypatch):
    def broken(*_):
        raise RuntimeError("sensitive provider text")
    monkeypatch.setattr(module, "call_model", broken)
    run = finish(agent, agent.submit(module.AgentRequest(question="检查", task="tracking", mode="model")))
    assert run["status"] == "failed" and run["output"] is None
    assert "sensitive" not in json.dumps(run)


def test_cli_rejects_path_escape():
    from scripts.quant_tools import run_endpoint
    with pytest.raises(ValueError):
        run_endpoint("../../tracking/anything")
