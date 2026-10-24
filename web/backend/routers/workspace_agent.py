"""工作台 Agent 的统一 HTTP 契约，供网页、桌面与 MCP 调用。"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from web.backend.services.workspace_agent import AgentRequest, workspace_agent
from web.backend.services.workspace_actions import AnalysisRequest, ActionRequest, controlled_actions
from web.backend.services.llm_providers.llm_config import load_llm_config

router = APIRouter(prefix="/api/agent", tags=["研究 Agent"])


class SaveReviewRequest(BaseModel):
    review_date: date
    confirmed: bool = False


@router.get("/capabilities")
def capabilities():
    from web.backend.routers.backtest import BacktestRequest
    from web.backend.routers.tracking import TrackingCreateRequest
    from web.backend.services.workspace_actions import UpdateActionParameters, TrackingRefreshParameters
    config = load_llm_config()
    settings = config.get("deepseek") or {}
    ready = config.get("provider") == "deepseek" and bool(settings.get("api_key"))
    from web.backend.services.codex_research import codex_settings
    codex = codex_settings()
    return {"agent_name": "quant_research", "prompt_version": "1.0.0", "model_ready": ready,
            "codex_available": codex['available'], "codex_model": codex['model'],
            "provider": "deepseek" if ready else None, "model": settings.get("model") if ready else None,
            "action_schemas": {"update": UpdateActionParameters.model_json_schema(), "backtest": BacktestRequest.model_json_schema(), "tracking": TrackingCreateRequest.model_json_schema(), "tracking_refresh": TrackingRefreshParameters.model_json_schema()},
            "action_contract": {"confirmed_required": True, "request_id_required": True, "status_query": "/api/agent/actions/{action_id}"},
            "tasks": ["candidates", "tracking", "reviews", "market"], "write_actions": ["save_review", "submit_analysis", "update", "backtest", "tracking", "tracking_refresh"], "trading": False}


@router.get('/daily')
def daily_status():
    from web.backend.services.daily_workflow import read_daily_status
    return read_daily_status()


@router.get("/runs")
def recent_runs(limit: int = Query(30, ge=1, le=100)):
    return {"items": workspace_agent.store.recent(limit)}


@router.post("/runs", status_code=202)
def start_run(payload: AgentRequest):
    try:
        return workspace_agent.submit(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    try:
        return workspace_agent.store.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="运行不存在") from exc


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    get_run(run_id)
    return workspace_agent.store.patch(run_id, active_only=True, status="cancelled")


@router.post("/runs/{run_id}/review")
def save_review(run_id: str, payload: SaveReviewRequest):
    get_run(run_id)
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail="需要明确确认后才会追加复盘")
    try:
        return workspace_agent.save_review(run_id, payload.review_date.isoformat())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/runs/{run_id}/analysis")
def submit_analysis(run_id: str, payload: AnalysisRequest):
    try:
        return workspace_agent.submit_analysis(run_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="父运行不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/actions", status_code=202)
def submit_action(payload: ActionRequest):
    try:
        return controlled_actions.submit(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/actions/{action_id}")
def get_action(action_id: str):
    try:
        return controlled_actions.get(action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="操作不存在") from exc


@router.get("/active")
def active_tasks():
    from web.backend.services.sqlite_service import get_connection
    import json
    from web.backend.services import data_service
    from web.backend.services.backtest_job_service import backtest_job_manager
    # 先恢复受控任务关联的业务记录，保证首次活动查询就排除已死亡拥有者的任务。
    actions = controlled_actions.recent()
    items = []
    rows = get_connection().execute("SELECT payload FROM workspace_agent_runs WHERE status IN ('queued','running')").fetchall()
    for row in rows:
        run = json.loads(row[0])
        items.append({"id": run["run_id"], "kind": "research", "status": run["status"], "owner_pid": run.get("owner_pid")})
    state = data_service._UPDATE_JOB_STATE
    if state.get("is_running"):
        items.append({"id": state["run_id"], "kind": "update", "status": "running"})
    # 读取既有业务任务，覆盖从原 UI 发起的回测。
    for task in backtest_job_manager.list_recent(200):
        if task["status"] not in ("done", "failed", "canceled", "interrupted"):
            items.append({"id": task["task_id"], "kind": "backtest", "status": task["status"]})
    known = {item["id"] for item in items}
    from web.backend.services.strategy_scan import active_scan_status
    for scan in active_scan_status():
        if scan['id'] not in known:
            items.append(scan)
            known.add(scan['id'])
    for action in actions:
        action = controlled_actions.get(action["action_id"])
        if action["status"] in ("running", "queued", "cancel_requested") and action.get("business_id") not in known:
            items.append({"id": action.get("business_id") or action["action_id"], "kind": action["kind"], "status": action["status"], "owner_pid": action.get("owner_pid")})
    return {"total": len(items), "items": items}


class ShutdownRequest(BaseModel):
    confirmed: bool = False


@router.post("/shutdown")
def shutdown_tasks(payload: ShutdownRequest):
    import os
    import json
    from web.backend.services.sqlite_service import get_connection
    from web.backend.services.workspace_agent import now
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail="需要确认退出")
    interrupted = []
    from web.backend.services.strategy_scan import cancel_active_scans
    interrupted.extend(cancel_active_scans())
    rows = get_connection().execute("SELECT payload FROM workspace_agent_runs WHERE status IN ('queued','running')").fetchall()
    for row in rows:
        run = json.loads(row[0])
        if run.get("owner_pid") == os.getpid():
            workspace_agent.store.patch(run["run_id"], active_only=True, status="interrupted", error="桌面确认退出", events=[*run["events"], {"at": now(), "type": "shutdown_confirmed"}])
            interrupted.append(run["run_id"])
    return {"interrupted": interrupted}


@router.get("/requests/{kind}/{request_id}")
def get_request_state(kind: str, request_id: str):
    from web.backend.services.workspace_actions import request_state
    if kind not in ("analysis", "action"):
        raise HTTPException(status_code=404, detail="请求类别不存在")
    try:
        return request_state(kind, request_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="请求不存在") from exc
