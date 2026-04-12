"""策略选股接口"""
import json

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api", tags=["策略选股"])


@router.get("/strategy/results")
async def get_strategy_results(
    strategy: str = Query("all", pattern="^(all|b1|b2|bowl)$"),
    date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """
    获取策略选股结果
    - strategy: all / b1 / b2 / bowl
    - date: 指定日期（可选，默认最新交易日）
    """
    from web.backend.services.strategy_service import run_strategy
    results = run_strategy(strategy, date)
    return {"success": True, "data": results}


@router.get("/strategy/cache/status")
async def get_strategy_cache_status(
    strategy: str = Query("all", pattern="^(all|b1|b2|bowl)$"),
    date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """获取策略缓存状态"""
    from web.backend.services.strategy_service import get_strategy_cache_status as get_cache_status

    status = get_cache_status(strategy, date)
    return {"success": True, "data": status}


@router.post("/strategy/cache/rebuild")
async def rebuild_strategy_cache(
    strategy: str = Query("all", pattern="^(all|b1|b2|bowl)$"),
    date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """手动重建策略缓存（SSE 流式返回进度）"""
    from web.backend.services.strategy_service import stream_strategy_cache_rebuild

    async def event_generator():
        async for msg in stream_strategy_cache_rebuild(strategy, date):
            yield {"event": msg["event"], "data": json.dumps(msg["data"], ensure_ascii=False)}

    return EventSourceResponse(event_generator())
