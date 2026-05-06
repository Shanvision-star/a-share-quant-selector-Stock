"""人工选股池接口。"""
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from web.backend.services import manual_selection_service as service


router = APIRouter(prefix="/api", tags=["人工选股"])

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class ManualSelectionPayload(BaseModel):
    selection_date: str = Field(..., pattern=DATE_PATTERN)
    code: str = Field(..., pattern=r"^\d{6}$")
    name: str = Field(default="", max_length=80)
    strategy_name: str = Field(default="", max_length=80)
    source_trade_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)
    source_signal_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)
    source_payload: dict[str, Any] = Field(default_factory=dict)
    note: str = Field(default="", max_length=500)


@router.get("/manual-selections")
async def list_manual_selections(
    date: str = Query(None, pattern=DATE_PATTERN),
    start_date: str = Query(None, pattern=DATE_PATTERN),
    end_date: str = Query(None, pattern=DATE_PATTERN),
):
    items = service.list_selections(selection_date=date, start_date=start_date, end_date=end_date)
    return {"success": True, "data": items}


@router.get("/manual-selections/dates")
async def list_manual_selection_dates(limit: int = Query(60, ge=1, le=300)):
    return {"success": True, "data": service.list_selection_dates(limit)}


@router.post("/manual-selections")
async def upsert_manual_selection(payload: ManualSelectionPayload):
    item = service.upsert_selection(payload.dict())
    return {"success": True, "data": item}


@router.delete("/manual-selections")
async def delete_manual_selection(
    date: str = Query(..., pattern=DATE_PATTERN),
    code: str = Query(..., pattern=r"^\d{6}$"),
):
    deleted = service.delete_selection(date, code)
    return {"success": True, "data": {"deleted": deleted}}
