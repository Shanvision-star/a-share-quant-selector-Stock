"""Post-close Loop Runner REST 接口。"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from web.backend.services.tracking_loop_runner_service import tracking_loop_runner_service


router = APIRouter(prefix="/api/tracking/loops", tags=["跟踪循环"])


class PostCloseRunRequest(BaseModel):
    eval_date: Optional[str] = None
    slot: str = "post_close"
    per_slot_limit: int = Field(default=8, ge=1, le=100)
    sync_first: bool = True
    trigger: Literal["manual", "cron", "api"] = "api"


@router.post("/post-close/run")
async def run_post_close_loop(payload: Optional[PostCloseRunRequest] = None):
    """触发一次收盘后 Tracking Loop；busy 作为幂等状态返回。"""
    payload = payload or PostCloseRunRequest()
    result = tracking_loop_runner_service.run_post_close(
        eval_date=payload.eval_date,
        slot=payload.slot,
        per_slot_limit=payload.per_slot_limit,
        sync_first=payload.sync_first,
        trigger=payload.trigger,
    )
    return {"success": True, "data": result}


@router.get("/runs/latest")
async def latest_loop_run(loop_type: str = Query(default="post_close")):
    """读取最近一次 Tracking Loop 运行摘要。"""
    return {
        "success": True,
        "data": tracking_loop_runner_service.latest_run(loop_type=loop_type),
    }
