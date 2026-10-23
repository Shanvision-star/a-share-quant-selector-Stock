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
    repository.create_if_absent(replace(ReviewDocument.new("2026-10-23"), body="# 原有复盘\n\n保留这段内容。", tags=("人工标签",)))
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
        assert repository.load("2026-10-23").tags == ("人工标签",)
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


def test_local_checks_stale_missing_and_truncation():
    report = module.local_report([{"source_id": "S1", "tool": "tracking_snapshot", "arguments": {"trade_date": "2026-10-23"}, "data": {"total": 4, "items": [{"code": "000001", "last_eval_date": "2026-10-20"}, {"code": "000002", "last_eval_date": None}], "budget_truncated": True}}])
    text = json.dumps(report, ensure_ascii=False)
    assert "早于参考日期 1 条" in text
    assert "缺少评估/记录日期 1 条" in text
    assert "条数截断 True" in text and "预算截断 True" in text
    assert "不回答开放式" in text


def test_external_analysis_save_stock_search_and_integrity(agent):
    from web.backend.services.workspace_actions import AnalysisRequest
    from web.backend.services.review_service import ReviewService
    parent = finish(agent, agent.submit(module.AgentRequest(question="取证", task="tracking", code="000001")))
    payload = AnalysisRequest(request_id="analysis-one", source_hashes={s["source_id"]: s["sha256"] for s in parent["sources"]},
        report={"summary": "Codex 分析", "findings": [{"text": "取证为空", "source_ids": ["S1"]}], "next_steps": [], "limitations": ["样本有限"]}, model="codex-test", prompt_version="v1")
    child = agent.submit_analysis(parent["run_id"], payload)
    assert child["run_id"] != parent["run_id"] and child["parent_run_id"] == parent["run_id"]
    assert child["input"]["mode"] == "external" and child["author"] == "Codex"
    assert agent.submit_analysis(parent["run_id"], payload)["run_id"] == child["run_id"]
    assert agent.store.get(parent["run_id"]) == parent
    agent.save_review(child["run_id"], "2026-10-23")
    assert agent.save_review(child["run_id"], "2026-10-23")["already_saved"]
    result = ReviewService(ReviewRepository(module.ROOT / "data" / "review_library")).list_reviews(stock="000001")
    assert result["total"] == 1 and "Codex 分析" in result["items"][0].body
    with pytest.raises(ValueError, match="hash"):
        agent.submit_analysis(parent["run_id"], payload.model_copy(update={"source_hashes": {"S1": "bad"}}))
    bad_report = payload.report.model_copy(update={"findings": [module.Finding(text="bad", source_ids=["S404"])]})
    with pytest.raises(ValueError, match="不存在"):
        agent.submit_analysis(parent["run_id"], payload.model_copy(update={"report": bad_report}))
    with pytest.raises(ValueError, match="不同请求"):
        agent.submit_analysis(parent["run_id"], payload.model_copy(update={"model": "other"}))


def test_action_confirmation_idempotency_and_business_contract(agent, monkeypatch):
    from web.backend.services import workspace_actions as actions
    from web.backend.services import tracking_service, backtest_job_service
    service = actions.ControlledActions()
    calls = []
    monkeypatch.setattr(tracking_service.tracking_service, "create_item", lambda params: calls.append(params) or {"tracking_id": "real-tracking", "status": "watching"})
    request = actions.ActionRequest(request_id="track-one", action="tracking", parameters={"code": "000001", "signal_date": "2026-10-23"})
    with pytest.raises(ValueError, match="confirmed"):
        service.submit(request)
    first = service.submit(request.model_copy(update={"confirmed": True}))
    assert first["business_id"] == "real-tracking" and first["status"] == "completed"
    assert service.submit(request.model_copy(update={"confirmed": True}))["action_id"] == first["action_id"]
    assert len(calls) == 1
    monkeypatch.setattr(backtest_job_service.backtest_job_manager, "submit", lambda params: {"task_id": "real-backtest", "status": "queued"})
    monkeypatch.setattr(backtest_job_service.backtest_job_manager, "get", lambda task_id: {"task_id": task_id, "status": "done", "result": {"summary": "ok"}})
    backtest = service.submit(actions.ActionRequest(request_id="bt-one", action="backtest", confirmed=True, parameters={"start_date": "2026-10-01", "end_date": "2026-10-23"}))
    assert backtest["status"] == "queued" and backtest["business_id"] == "real-backtest"
    assert service.get(backtest["action_id"])["status"] == "done"
    assert any(event["type"] == "confirmed" for event in first["events"])
    service.pool.shutdown()


def test_update_stream_real_state_and_failure(agent, monkeypatch):
    from web.backend.services import workspace_actions as actions, data_service
    service = actions.ControlledActions()
    async def update(**params):
        assert params == {"auto_rebuild": False}
        yield {"event": "progress", "data": {"run_id": "real-update", "status": "running"}}
        yield {"event": "error", "data": {"run_id": "real-update", "status": "partial", "message": "部分失败"}}
    monkeypatch.setattr(data_service, "run_data_update", update)
    item = service.submit(actions.ActionRequest(request_id="update-one", action="update", confirmed=True, parameters={"auto_rebuild": False}))
    service.pool.shutdown(wait=True)
    final = service.get(item["action_id"])
    assert final["business_id"] == "real-update" and final["status"] == "failed"
    assert final["error"] == "部分失败"


def test_active_covers_ui_and_shutdown_owner(agent, monkeypatch):
    from web.backend.services import data_service, backtest_job_service
    monkeypatch.setattr(data_service, "_UPDATE_JOB_STATE", {"is_running": True, "run_id": "ui-update"})
    monkeypatch.setattr(backtest_job_service.backtest_job_manager, "list_recent", lambda limit: [{"task_id": "ui-bt", "status": "running"}])
    owned = agent.store.create(module.AgentRequest(question="owned"))
    other = agent.store.create(module.AgentRequest(question="other"))
    agent.store.patch(other["run_id"], owner_pid=-123)
    active = routes.active_tasks()
    assert active["total"] == 4
    assert {item["id"] for item in active["items"]} >= {"ui-update", "ui-bt"}
    result = routes.shutdown_tasks(routes.ShutdownRequest(confirmed=True))
    assert result["interrupted"] == [owned["run_id"]]
    assert agent.store.get(other["run_id"])["status"] == "queued"


def test_update_success_uses_existing_job_complete(agent, monkeypatch):
    from web.backend.services import workspace_actions as actions, data_service
    service = actions.ControlledActions()
    async def update(**params):
        yield {"event": "update_complete", "data": {"run_id": "real-success", "status": "running"}}
        yield {"event": "job_complete", "data": {"run_id": "real-success", "status": "done"}}
    monkeypatch.setattr(data_service, "run_data_update", update)
    item = service.submit(actions.ActionRequest(request_id="update-success", action="update", confirmed=True))
    service.pool.shutdown(wait=True)
    assert service.get(item["action_id"])["status"] == "completed"


def test_http_external_and_action_validation(agent):
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.post("/api/agent/actions", json={"request_id": "unsafe", "action": "tracking", "parameters": {}}).status_code == 409
        assert client.post("/api/agent/actions", json={"request_id": "unsafe", "action": "shell", "confirmed": True}).status_code == 422
        assert client.post("/api/agent/actions", json={"request_id": "unsafe", "action": "update", "confirmed": True, "parameters": {"shell": "cmd"}}).status_code == 409
        assert client.post("/api/agent/shutdown", json={"confirmed": False}).status_code == 409
        assert client.get("/api/agent/actions/missing").status_code == 404


def test_dead_update_owner_recovers_business_terminal_and_active(agent, monkeypatch):
    from web.backend.services import workspace_actions as actions, strategy_result_repository as repo, data_service, backtest_job_service
    service = actions.ControlledActions()
    for suffix, business_status, expected in (("done", "done", "completed"), ("failed", "error", "failed"), ("open", "running", "interrupted")):
        run_id = f"business-{suffix}"
        repo.create_run(run_id, "update", "2026-10-23", "all")
        if business_status != "running":
            repo.finish_run(run_id, business_status, "业务终态")
        req = f"dead-{suffix}"
        actions.claim_request("action", req, {"case": suffix})
        service.save({"action_id": req, "request_id": req, "kind": "update", "status": "running", "owner_pid": -1, "business_id": run_id, "events": [], "created_at": module.now()})
        item = service.get(req)
        assert item["status"] == expected
        assert item["events"][-1]["type"] == "owner_interrupted"
    monkeypatch.setattr(routes, "controlled_actions", service)
    monkeypatch.setattr(data_service, "_UPDATE_JOB_STATE", {})
    monkeypatch.setattr(backtest_job_service.backtest_job_manager, "list_recent", lambda _: [])
    assert routes.active_tasks() == {"total": 0, "items": []}
    service.pool.shutdown()


@pytest.mark.parametrize("status", ["queued", "running", "cancel_requested"])
def test_dead_backtest_owner_recovers_business_active_and_idempotency(agent, monkeypatch, status):
    from web.backend.services import workspace_actions as actions, backtest_job_service as jobs, data_service
    repository = jobs.BacktestTaskRepository(connection_factory=db.get_connection)
    manager = jobs.BacktestJobManager(runner=lambda _: {"summary": {"trades": 0}}, repository=repository)
    monkeypatch.setattr(jobs, "backtest_job_manager", manager)
    monkeypatch.setattr(data_service, "_UPDATE_JOB_STATE", {})
    request = actions.ActionRequest(request_id="dead-backtest", action="backtest", confirmed=True,
        parameters={"start_date": "2026-10-01", "end_date": "2026-10-23"})
    actions.claim_request("action", request.request_id, request.model_dump(mode="json"))
    repository.create({"task_id": "orphan-bt", "status": status, "params": request.parameters})
    old_service = actions.ControlledActions()
    old_service.save({"action_id": "orphan-action", "request_id": request.request_id, "kind": "backtest",
        "status": status, "owner_pid": -1, "business_id": "orphan-bt", "events": [], "created_at": module.now()})
    old_service.pool.shutdown()
    service = actions.ControlledActions()
    monkeypatch.setattr(routes, "controlled_actions", service)
    try:
        # 首次只读取活动列表也必须先恢复业务状态，不能多轮轮询才移除残留。
        assert routes.active_tasks() == {"total": 0, "items": []}
        recovered = service.get("orphan-action")
        assert recovered["status"] == "failed" and "退出" in recovered["error"]
        business = manager.get("orphan-bt", include_events=True)
        assert business["status"] == "failed" and business["finished_at"]
        assert [event["event_type"] for event in business["events"]].count("owner_interrupted") == 1
        assert [event["type"] for event in recovered["events"]].count("owner_interrupted") == 1
        assert service.submit(request)["action_id"] == "orphan-action"
        assert len(manager.list_recent()) == 1
        fresh = service.submit(request.model_copy(update={"request_id": "new-backtest"}))
        assert fresh["business_id"] != "orphan-bt"
        assert manager.wait(fresh["business_id"], timeout=3)["status"] == "done"
        rows = db.get_connection().execute("SELECT event FROM workspace_action_audit WHERE request_id=?", (request.request_id,)).fetchall()
        assert [row[0] for row in rows].count("owner_interrupted") == 1
    finally:
        service.pool.shutdown()
        manager.executor.shutdown(wait=True)


@pytest.mark.parametrize("business_status,alive", [("running", True), ("queued", True),
    ("done", False), ("failed", False), ("canceled", False)])
def test_backtest_recovery_preserves_live_owner_and_business_terminal(agent, monkeypatch, business_status, alive):
    from web.backend.services import workspace_actions as actions, backtest_job_service as jobs
    repository = jobs.BacktestTaskRepository(connection_factory=db.get_connection)
    manager = jobs.BacktestJobManager(repository=repository)
    monkeypatch.setattr(jobs, "backtest_job_manager", manager)
    # 另一个后端实例的 owner 也应保留，不能仅检查是否为当前 PID。
    monkeypatch.setattr(actions, "process_alive", lambda pid: pid == 78910 and alive)
    repository.create({"task_id": "protected-bt", "status": business_status,
        "result": {"summary": {"preserved": True}} if business_status == "done" else None})
    before = repository.get("protected-bt", include_events=True)
    actions.claim_request("action", "protected-request", {"case": "protected"})
    service = actions.ControlledActions()
    service.save({"action_id": "protected-action", "request_id": "protected-request", "kind": "backtest",
        "status": "running", "owner_pid": 78910, "business_id": "protected-bt", "events": [], "created_at": module.now()})
    try:
        assert service.get("protected-action")["status"] == business_status
        assert repository.get("protected-bt", include_events=True) == before
    finally:
        service.pool.shutdown()
        manager.executor.shutdown(wait=True)


def test_analysis_interrupted_claim_is_visible_and_never_replayed(agent):
    from web.backend.services import workspace_actions as actions
    payload = {"parent": "evidence", "report": "pending"}
    actions.claim_request("analysis", "interrupted-analysis", payload)
    state = actions.request_state("analysis", "interrupted-analysis")
    assert state["request_state"] == "processing" and state["request"] == payload
    state["owner_pid"] = -1
    actions.complete_request("analysis", "interrupted-analysis", state)
    result = routes.get_request_state("analysis", "interrupted-analysis")
    assert result["request_state"] == "interrupted" and result["request_id"] == "interrupted-analysis"
    with pytest.raises(ValueError, match="状态=interrupted"):
        actions.claim_request("analysis", "interrupted-analysis", payload)
    assert actions.request_state("analysis", "interrupted-analysis")["request_state"] == "interrupted"


def test_partial_warning_cannot_be_overwritten_by_done(agent, monkeypatch):
    from web.backend.services import workspace_actions as actions, data_service
    service = actions.ControlledActions()
    async def update(**params):
        yield {"event": "update_warning", "data": {"run_id": "partial-real", "status": "running", "update_status": "partial", "failed": 3, "message": "三只失败"}}
        yield {"event": "update_complete", "data": {"run_id": "partial-real", "status": "running"}}
        yield {"event": "job_complete", "data": {"run_id": "partial-real", "status": "done"}}
    monkeypatch.setattr(data_service, "run_data_update", update)
    item = service.submit(actions.ActionRequest(request_id="partial-real", action="update", confirmed=True))
    service.pool.shutdown(wait=True)
    final = service.get(item["action_id"])
    assert final["status"] == "failed" and final["update_status"] == "partial"
    assert final["update_failure"]["failed"] == 3 and final["error"] == "三只失败"
    assert final["events"][2]["update_status"] == "partial"


def test_dead_owner_done_with_warning_recovers_failed(agent):
    from web.backend.services import workspace_actions as actions, strategy_result_repository as repo
    service = actions.ControlledActions()
    repo.create_run("partial-dead", "update", "2026-10-23", "all")
    repo.insert_event("partial-dead", "warning", message="局部失败")
    repo.finish_run("partial-dead", "done")
    actions.claim_request("action", "partial-dead", {})
    service.save({"action_id": "partial-dead", "request_id": "partial-dead", "kind": "update", "status": "running", "owner_pid": -1, "business_id": "partial-dead", "events": [], "created_at": module.now()})
    assert service.get("partial-dead")["status"] == "failed"
    service.pool.shutdown()


def test_rejections_and_review_failures_persist_safe_audit(agent, monkeypatch):
    from web.backend.services import workspace_actions as actions
    service = actions.ControlledActions()
    secret = "secret-must-never-be-audited"
    with pytest.raises(ValueError):
        service.submit(actions.ActionRequest(request_id="invalid-params", action="update", confirmed=True, parameters={"unknown": secret}))
    monkeypatch.setattr(service, "recent", lambda: [{"created_at": module.now(), "request_id": str(i)} for i in range(12)])
    with pytest.raises(ValueError):
        service.submit(actions.ActionRequest(request_id="rate-limited", action="update", confirmed=True))
    monkeypatch.setattr(service, "recent", lambda: [])
    actions.claim_request("action", "conflicting-id", {"old": True})
    with pytest.raises(ValueError):
        service.submit(actions.ActionRequest(request_id="conflicting-id", action="update", confirmed=True))
    parent = finish(agent, agent.submit(module.AgentRequest(question="取证", task="tracking")))
    payload = actions.AnalysisRequest(request_id="invalid-hash", source_hashes={"S1": "wrong"}, report={"summary": secret, "findings": [], "next_steps": [], "limitations": []}, model="test", prompt_version="test")
    with pytest.raises(ValueError):
        agent.submit_analysis(parent["run_id"], payload)
    with pytest.raises(ValueError):
        agent.save_review(agent.store.create(module.AgentRequest(question="未完成"))["run_id"], "2026-10-23")
    rows = db.get_connection().execute("SELECT request_id,event,payload FROM workspace_action_audit").fetchall()
    rejected = {row[0]: json.loads(row[2])["stage"] for row in rows if row[1] == "rejected"}
    assert rejected == {"invalid-params": "validation", "rate-limited": "rate_limit", "conflicting-id": "idempotency", "invalid-hash": "source_hash"}
    assert any(row[1] == "failed" and json.loads(row[2])["stage"] == "append_review" for row in rows)
    assert secret not in json.dumps([tuple(row) for row in rows])
    service.pool.shutdown()


def test_capabilities_disclose_reused_action_schemas(agent):
    from web.backend.routers.backtest import BacktestRequest
    from web.backend.routers.tracking import TrackingCreateRequest
    schemas = routes.capabilities()["action_schemas"]
    assert schemas["backtest"] == BacktestRequest.model_json_schema()
    assert schemas["tracking"] == TrackingCreateRequest.model_json_schema()
    assert schemas["update"]["properties"]["auto_rebuild"]["default"] is True
    assert schemas["update"]["properties"]["pipeline"]["default"] is False
    assert schemas["update"]["additionalProperties"] is False


@pytest.mark.parametrize("alive", [True, False])
def test_request_state_concurrent_completion_preserves_mapping(agent, monkeypatch, alive):
    from web.backend.services import workspace_actions as actions
    actions.claim_request("analysis", "race-state", {"parent": "p"})
    observed, release = threading.Event(), threading.Event()
    result, errors = [], []
    def check_owner(pid):
        observed.set()
        assert release.wait(3)
        return alive
    monkeypatch.setattr(actions, "process_alive", check_owner)
    def read_state():
        try:
            result.append(actions.request_state("analysis", "race-state"))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=read_state)
    thread.start()
    assert observed.wait(3)
    completed = {"run_id": "completed-child"}
    actions.complete_request("analysis", "race-state", completed)
    release.set()
    thread.join(3)
    assert not thread.is_alive() and not errors
    assert actions.request_state("analysis", "race-state") == completed
    assert actions.claim_request("analysis", "race-state", {"parent": "p"}) == completed
    if not alive:
        assert result == [completed]


def test_claim_recovery_holds_sqlite_transaction_until_state_write(agent, monkeypatch):
    from web.backend.services import workspace_actions as actions
    actions.claim_request("analysis", "race-claim", {"parent": "p"})
    locked, release, completing, completed = (threading.Event() for _ in range(4))
    errors = []
    def check_owner(pid):
        assert db.get_connection().in_transaction
        locked.set()
        assert release.wait(3)
        return False
    monkeypatch.setattr(actions, "process_alive", check_owner)
    def retry():
        try:
            actions.claim_request("analysis", "race-claim", {"parent": "p"})
        except ValueError as exc:
            assert "interrupted" in str(exc)
        except Exception as exc:
            errors.append(exc)
    def finish_request():
        try:
            completing.set()
            actions.complete_request("analysis", "race-claim", {"run_id": "final-child"})
            completed.set()
        except Exception as exc:
            errors.append(exc)
    retry_thread = threading.Thread(target=retry)
    retry_thread.start()
    assert locked.wait(3)
    finish_thread = threading.Thread(target=finish_request)
    finish_thread.start()
    assert completing.wait(3)
    assert not completed.wait(.05)
    release.set()
    retry_thread.join(3)
    finish_thread.join(3)
    assert not errors and completed.is_set()
    assert actions.request_state("analysis", "race-claim") == {"run_id": "final-child"}
