"""P4 跟踪告警事件 REST 接口。

提供 list/dispatch 端点；分发逻辑由 tracking_alert_service 实现。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from web.backend.services.tracking_alert_service import tracking_alert_service


router = APIRouter(prefix="/api/tracking/alerts", tags=["跟踪告警"])


@router.get("")
async def list_alerts(
    tracking_id: Optional[str] = None,
    eval_date: Optional[str] = None,
    ui_status: Optional[str] = None,
    limit: int = 500,
):
    """按可选条件分页返回告警事件，优先级升序排序。"""
    items = tracking_alert_service.list_alerts(
        tracking_id=tracking_id,
        eval_date=eval_date,
        ui_status=ui_status,
        limit=limit,
    )
    return {"success": True, "data": {"items": items}}


@router.post("/dispatch")
async def dispatch_alerts(
    slot: str = Query(..., description="钉钉推送时段，例如 09:00 / 11:30 / 15:30"),
    per_slot_limit: int = Query(8, ge=1, le=100),
):
    """按 slot 推送待处理告警；返回 {dispatched, deferred, aggregated}。"""
    summary = tracking_alert_service.dispatch_pending_alerts(
        slot=slot, per_slot_limit=per_slot_limit
    )
    return {"success": True, "data": summary}
