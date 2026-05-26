"""人工选股池接口。"""
from typing import Any, Optional

from fastapi import APIRouter, File, Query, UploadFile
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


class ImportPastePayload(BaseModel):
    """粘贴文本入口；后端负责正则提取 6 位代码。"""

    selection_date: str = Field(..., pattern=DATE_PATTERN)
    text: str = Field(..., max_length=20000)


class ImportFromStrategyPayload(BaseModel):
    """从策略结果勾选入口；codes 由前端从策略结果页传入。

    后端不重复查策略结果表，避免与 strategy_results_dedupe 路径产生第二份事实。
    """

    selection_date: str = Field(..., pattern=DATE_PATTERN)
    codes: list[str] = Field(..., min_length=1, max_length=500)
    strategy_name: str = Field(..., min_length=1, max_length=80)
    source_trade_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)


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


# ---------- P1: 三入口批量导入 ----------


@router.post("/manual-selections/import-txt")
async def import_manual_selection_from_txt(
    selection_date: str = Query(..., pattern=DATE_PATTERN),
    file: UploadFile = File(...),
):
    """上传 txt 文件入口；按 utf-8 解码失败时回退 gbk，匹配国内研报常见编码。"""
    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="ignore")
    codes = service.parse_codes_from_text(text)
    result = service.import_codes_batch(
        selection_date=selection_date,
        codes=codes,
        import_type="txt",
    )
    return {"success": True, "data": result}


@router.post("/manual-selections/import-paste")
async def import_manual_selection_from_paste(payload: ImportPastePayload):
    codes = service.parse_codes_from_text(payload.text)
    result = service.import_codes_batch(
        selection_date=payload.selection_date,
        codes=codes,
        import_type="paste",
    )
    return {"success": True, "data": result}


@router.post("/manual-selections/import-from-strategy")
async def import_manual_selection_from_strategy(payload: ImportFromStrategyPayload):
    result = service.import_codes_batch(
        selection_date=payload.selection_date,
        codes=payload.codes,
        import_type="strategy_pick",
        strategy_name=payload.strategy_name,
        source_trade_date=payload.source_trade_date,
    )
    return {"success": True, "data": result}
