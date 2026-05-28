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


class TrackingBatchCreateRequest(BaseModel):
    """TXT/粘贴 批量导入请求。

    text 与 codes 二选一：前端粘贴整段文本走 text，已分词列表走 codes，
    便于复用同一接口承接 TXT 上传 + 输入框粘贴 两种入口。
    """

    text: Optional[str] = Field(default=None, description="原始文本，按行/逗号/空白切分")
    codes: Optional[list[str]] = Field(default=None, max_length=500)
    signal_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)
    strategy_name: str = "manual_batch"
    evaluate_now: bool = True
    # 导入前先刷新每只股票近期行情 CSV（推荐勾选，否则 evaluate_now 在数据陈旧时无效）
    refresh_data: bool = False


class TrackingBatchDeleteRequest(BaseModel):
    """批量删除请求。"""

    tracking_ids: list[str] = Field(..., min_length=1, max_length=500)


class TrackingEntryPriceUpdateRequest(BaseModel):
    """手动修正买入价请求。

    - entry_price 必须 > 0；
    - entry_date / quantity 可选，传则一并更新；
    - 后端会自动 force=True 重算 latest_return_pct。
    """

    entry_price: float = Field(..., gt=0)
    entry_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)
    quantity: Optional[int] = Field(default=None, ge=0)
    eval_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)


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


# 关键：以下两个固定路径必须保持在 GET /tracking/{tracking_id} 之前注册，
# 否则会被路径参数兜底吞掉，导致 422/404；route_order 回归测试同步守护。
@router.post("/tracking/batch-create")
async def batch_create_tracking(payload: TrackingBatchCreateRequest):
    """通过 TXT/粘贴文本批量加入跟踪。

    入口收敛：
    1. 上传 TXT 文件 → 前端读出文本后塞 text；
    2. 粘贴文本框 → 直接塞 text；
    3. 已有分词列表 → 直接塞 codes。

    返回 created（含完整 item，已自动评估出 entry_price/latest_return_pct）
    / skipped（重复活跃跟踪）/ failed（格式非法或创建失败）。
    """
    raw_codes: list[str] = []
    invalid_tokens: list[str] = []
    if payload.text:
        parsed, invalid_tokens = tracking_service.parse_codes(payload.text)
        raw_codes.extend(parsed)
    if payload.codes:
        raw_codes.extend(payload.codes)
    if not raw_codes:
        raise HTTPException(status_code=400, detail="未解析到任何有效股票代码")

    # 若前端勾选"导入前刷新行情"，在创建前逐一增量更新 CSV，
    # 确保 evaluate_now=True 时能找到 signal_date 之后的交易日并落 entry_price。
    if payload.refresh_data and raw_codes:
        from web.backend.services.tracking_sync_service import _fetch_and_update_single
        for code in raw_codes:
            _fetch_and_update_single(code)

    result = tracking_service.batch_create_codes(
        codes=raw_codes,
        signal_date=payload.signal_date,
        strategy_name=payload.strategy_name,
        evaluate_now=payload.evaluate_now,
    )
    # 把 parse 阶段就识别出的非法 token 合并到 failed，前端一次性展示
    for tok in invalid_tokens:
        result["failed"].append({"code": tok, "reason": "格式非法（需 6 位数字）"})
    return {"success": True, "data": result}


@router.post("/tracking/batch-delete")
async def batch_delete_tracking(payload: TrackingBatchDeleteRequest):
    """批量删除跟踪记录。"""
    result = tracking_service.batch_delete(payload.tracking_ids)
    return {"success": True, "data": result}


@router.get("/tracking")
async def list_tracking_items(
    status: str = Query(default="all"),
    code: Optional[str] = Query(default=None, pattern=r"^\d{6}$"),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """查询单股跟踪列表。"""
    return {"success": True, "data": {"items": tracking_service.list_items(status=status, code=code, limit=limit)}}


@router.get("/tracking/stock-name/{code}")
async def get_tracking_stock_name(code: str):
    """根据 6 位股票代码返回名称，用于前端单股输入时自动补全名称。

    路由顺序约束：必须注册在 GET /tracking/{tracking_id} 之前，否则 FastAPI 会把
    "stock-name" 当成 tracking_id 命中下方路由导致 404。
    """
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="股票代码必须是 6 位数字")
    try:
        # 延迟导入，避免循环依赖以及在路由模块加载时拖入 kline_service 副作用
        from web.backend.services.kline_service import get_stock_name
        name = get_stock_name(code)
    except Exception as exc:  # 容错：名称查不到不算硬错误，返回"未知"由前端展示
        return {"success": True, "data": {"code": code, "name": "未知"}, "warning": str(exc)}
    return {"success": True, "data": {"code": code, "name": name}}


@router.get("/tracking/signal-close/{code}")
async def get_tracking_signal_close(code: str, date: str):
    """查询指定 code 在指定 signal_date（含之前最近交易日）的收盘价。

    用途：前端单股加入跟踪表单选好信号日后，自动把买入价默认填成信号日收盘价，
    用户可再手动覆盖。

    路由顺序约束：必须注册在 GET /tracking/{tracking_id} 之前。
    """
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(status_code=400, detail="股票代码必须是 6 位数字")
    try:
        data = tracking_service.get_signal_close(code, date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": data}


@router.get("/tracking/{tracking_id}")
async def get_tracking_item(tracking_id: str):
    """查询单条跟踪记录。"""
    item = tracking_service.get_item(tracking_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"跟踪记录不存在: {tracking_id}")
    return {"success": True, "data": item}


@router.delete("/tracking/{tracking_id}")
async def delete_tracking_item(tracking_id: str):
    """删除单条跟踪记录及其事件流。

    DELETE 与 GET 的方法不同，FastAPI 不会因路径冲突被吞，但保留在此聚合，
    便于审查与维护。
    """
    ok = tracking_service.delete_item(tracking_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"跟踪记录不存在: {tracking_id}")
    return {"success": True, "data": {"tracking_id": tracking_id, "deleted": True}}


@router.patch("/tracking/{tracking_id}/entry-price")
async def patch_tracking_entry_price(tracking_id: str, payload: TrackingEntryPriceUpdateRequest):
    """手动修改买入价（可选同步修改买入日期/数量），并强制重算 latest_return_pct。

    用于实际成交价与系统假设不符的修正场景；
    后端走 update_entry_price → evaluate_item(force=True)，绕过同日短路。
    HTTP 方法用 PATCH 与已有的 GET / POST /tracking/{id}/* 互不冲突，无需调整路由顺序测试。
    """
    try:
        item = tracking_service.update_entry_price(
            tracking_id,
            entry_price=payload.entry_price,
            entry_date=payload.entry_date,
            quantity=payload.quantity,
            eval_date=payload.eval_date,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"跟踪记录不存在: {tracking_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@router.post("/tracking/sync-close")
async def sync_close_tracking(
    date: Optional[str] = Query(default=None, pattern=DATE_PATTERN, description="评估基准日，默认取最新收盘日"),
):
    """收盘同步：仅更新活跃跟踪股票的近期行情 CSV，再批量评估推进状态。

    对比全市场更新（可能数分钟），本接口只刷跟踪列表中的 N 只股票，
    通常 5-50 只，耗时秒级，适合每日 15:30 后手动一键触发。
    返回结构：{total_codes, updated, skipped, errors, evaluation{total, status_changes}}。
    """
    from web.backend.services.tracking_sync_service import tracking_sync_service as _tss

    result = _tss.sync_and_evaluate(eval_date=date)
    return {"success": True, "data": result}


@router.get("/tracking/{tracking_id}/events")
async def list_tracking_events(
    tracking_id: str,
    limit: int = Query(default=200, ge=1, le=1000),
):
    """查询单股跟踪事件流。"""
    if not tracking_service.get_item(tracking_id):
        raise HTTPException(status_code=404, detail=f"跟踪记录不存在: {tracking_id}")
    return {"success": True, "data": {"items": tracking_service.list_events(tracking_id, limit)}}
