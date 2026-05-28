"""P7 OrderIntent 确认 / 否决路由：把 LLM 建议落地为可审计的事件。

- POST /api/tracking/{tracking_id}/confirm-intent
- POST /api/tracking/{tracking_id}/reject-intent
- 不接入真实下单通道，仅写 tracking_events，由前端/调度后续消费。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from web.backend.services.tracking_service import tracking_service


router = APIRouter(prefix="/api/tracking", tags=["跟踪意图动作"])


class ConfirmIntentRequest(BaseModel):
    """确认意图入参：intent 可省略，使用 tracking_items.latest_intent。"""

    intent: dict | None = Field(default=None, description="覆盖性 OrderIntent，可包含 side/code/qty_hint/reason")


class RejectIntentRequest(BaseModel):
    """否决意图入参：必须给出业务原因，便于后续复盘。"""

    reason: str = Field(default="", description="否决原因，落入事件 payload")


@router.post("/{tracking_id}/confirm-intent")
async def confirm_intent(tracking_id: str, payload: ConfirmIntentRequest | None = None):
    """确认 OrderIntent：写事件并返回更新后的跟踪项。"""
    try:
        item = tracking_service.confirm_intent(
            tracking_id,
            intent=(payload.intent if payload else None),
        )
    except KeyError:
        # KeyError 对应未知 tracking_id，转换成 404 响应
        raise HTTPException(status_code=404, detail=f"tracking_id 不存在: {tracking_id}")
    return {"success": True, "data": item}


@router.post("/{tracking_id}/reject-intent")
async def reject_intent(tracking_id: str, payload: RejectIntentRequest | None = None):
    """否决 OrderIntent：next_action 回落 HOLD 并写事件。"""
    try:
        item = tracking_service.reject_intent(
            tracking_id,
            reason=(payload.reason if payload else ""),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"tracking_id 不存在: {tracking_id}")
    return {"success": True, "data": item}
