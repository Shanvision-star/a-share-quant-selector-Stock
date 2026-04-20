"""数据更新接口"""
from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse
import json
from typing import List

router = APIRouter(prefix="/api", tags=["数据更新"])


@router.post("/update")
async def trigger_update(
    auto_rebuild: bool = Query(True),
    date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    pipeline: bool = Query(False),
):
    """触发数据更新（SSE 流式返回进度）
    auto_rebuild=True 时，更新完成后自动执行全策略缓存重建
    pipeline=True 时，更新阶段即内联执行策略扫描并实时推送命中结果
    """
    from web.backend.services.data_service import run_data_update

    async def event_generator():
        async for msg in run_data_update(auto_rebuild=auto_rebuild, target_date=date, pipeline=pipeline):
            yield {"event": msg["event"], "data": json.dumps(msg["data"], ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.get("/data/status")
async def get_data_status():
    """获取数据新鲜度报告"""
    from web.backend.services.data_service import get_data_status
    status = get_data_status()
    return {"success": True, "data": status}


@router.get("/market-cap")
async def get_market_cap(codes: str = Query(None, description="逗号分隔的股票代码；为空则返回全部")):
    """
    从内存缓存（AKShareFetcher._market_cap_cache）按需返回市值。
    前端在收到 market_cap_complete 事件后调用此接口刷新显示的市值数据。
    返回：{code: 市值（亿元）}
    """
    from web.backend.services.data_service import fetcher
    from utils.akshare_fetcher import _market_cap_cache_lock

    with _market_cap_cache_lock:
        cache: dict = dict(fetcher._market_cap_cache)

    if codes:
        code_list = [c.strip().zfill(6) for c in codes.split(',') if c.strip()]
        result = {c: round(cache.get(c, 0) / 1e8, 2) for c in code_list}
    else:
        result = {c: round(v / 1e8, 2) for c, v in cache.items()}

    return {"success": True, "data": result, "total": len(result)}
