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


class TrackingBatchFromSelectionRequest(BaseModel):
    """从人工选股池批量加入跟踪。

    codes 留空 → 全部入选；提供 codes → 仅勾选导入，便于前端"全选/部分选"两路场景。
    """

    selection_date: str = Field(..., pattern=DATE_PATTERN)
    codes: Optional[list[str]] = Field(default=None, max_length=500)


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


@router.post("/tracking/batch-from-selection")
async def batch_tracking_from_selection(payload: TrackingBatchFromSelectionRequest):
    """从人工选股池批量加入跟踪。

    返回结构与 service.batch_from_selection 保持一致，前端按 created/skipped/failed 三段展示。
    """
    result = tracking_service.batch_from_selection(
        selection_date=payload.selection_date,
        codes=payload.codes,
    )
    return {"success": True, "data": result}


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
