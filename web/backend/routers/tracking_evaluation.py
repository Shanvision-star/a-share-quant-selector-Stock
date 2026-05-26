"""P5 跟踪规则评估编排路由。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from web.backend.services.tracking_evaluation_service import tracking_evaluation_service


router = APIRouter(prefix="/api/tracking", tags=["跟踪评估"])


class EvaluateRequest(BaseModel):
    eval_date: Optional[str] = None
    only_codes: Optional[list[str]] = None


@router.post("/evaluate-rules")
async def evaluate_rules(payload: Optional[EvaluateRequest] = None):
    """触发一次活跃跟踪项规则评估，返回 evaluated/alerts_created/alerts_skipped_dup 摘要。"""
    if payload is None:
        payload = EvaluateRequest()
    summary = tracking_evaluation_service.evaluate_active_items(
        eval_date=payload.eval_date,
        only_codes=payload.only_codes,
    )
    return {"success": True, "data": summary}
