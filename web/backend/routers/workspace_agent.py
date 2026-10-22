"""工作台 Agent 的统一 HTTP 契约，供网页、桌面与 MCP 调用。"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from web.backend.services.workspace_agent import AgentRequest, workspace_agent
from web.backend.services.llm_providers.llm_config import load_llm_config

router = APIRouter(prefix="/api/agent", tags=["研究 Agent"])


class SaveReviewRequest(BaseModel):
    review_date: date
    confirmed: bool = False


@router.get("/capabilities")
def capabilities():
    config = load_llm_config()
    settings = config.get("deepseek") or {}
    ready = config.get("provider") == "deepseek" and bool(settings.get("api_key"))
    return {"agent_name": "quant_research", "prompt_version": "1.0.0", "model_ready": ready,
            "provider": "deepseek" if ready else None, "model": settings.get("model") if ready else None,
            "tasks": ["candidates", "tracking", "reviews"], "write_actions": ["save_review"], "trading": False}


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
