"""单股跟踪接口。"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from web.backend.services.tracking_service import tracking_service


router = APIRouter(prefix="/api", tags=["单股跟踪"])

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class TrackingCreateRequest(BaseModel):
    code: str = Field(..., pattern=r"^\d{6}$")
    name: str = ""
    strategy_name: str = ""
    source: str = "manual"
    source_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)
    signal_date: str = Field(..., pattern=DATE_PATTERN)
    params: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


def _payload_to_dict(payload: TrackingCreateRequest) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


@router.post("/tracking")
async def create_tracking_item(payload: TrackingCreateRequest):
    """创建单股跟踪记录。"""
    try:
        item = tracking_service.create_item(_payload_to_dict(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": item}


@router.get("/tracking")
async def list_tracking_items(
    status: str = Query(default="all"),
    code: Optional[str] = Query(default=None, pattern=r"^\d{6}$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """查询单股跟踪列表。"""
    return {"success": True, "data": {"items": tracking_service.list_items(status=status, code=code, limit=limit)}}


@router.get("/tracking/{tracking_id}")
async def get_tracking_item(tracking_id: str):
    """查询单条跟踪记录。"""
    item = tracking_service.get_item(tracking_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"跟踪记录不存在: {tracking_id}")
    return {"success": True, "data": item}


@router.post("/tracking/{tracking_id}/evaluate")
async def evaluate_tracking_item(
    tracking_id: str,
    date: Optional[str] = Query(default=None, pattern=DATE_PATTERN),
):
    """评估单条跟踪记录并生成下一步建议。"""
    try:
        item = tracking_service.evaluate_item(tracking_id, date)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"跟踪记录不存在: {tracking_id}") from exc
    return {"success": True, "data": item}


@router.post("/tracking/evaluate")
async def evaluate_tracking_items(date: Optional[str] = Query(default=None, pattern=DATE_PATTERN)):
    """批量评估未结束的跟踪记录。"""
    return {"success": True, "data": tracking_service.evaluate_items(date)}


@router.get("/tracking/{tracking_id}/events")
async def list_tracking_events(
    tracking_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
):
    """查询单股跟踪事件流。"""
    if not tracking_service.get_item(tracking_id):
        raise HTTPException(status_code=404, detail=f"跟踪记录不存在: {tracking_id}")
    return {"success": True, "data": {"items": tracking_service.list_events(tracking_id, limit)}}
