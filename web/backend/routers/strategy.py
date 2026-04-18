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


@router.get("/strategy/results/history")
async def get_strategy_results_history(
    strategy: str = Query("all", pattern="^(all|b1|b2|bowl)$"),
    start_date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end_date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    code: str = Query(None),
    keyword: str = Query(None),
    min_j_value: float = Query(None),
    max_j_value: float = Query(None),
    min_similarity: float = Query(None),
    max_similarity: float = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    sort_by: str = Query("trade_date"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
):
    """历史结果分页查询"""
    from web.backend.services import strategy_result_repository as repo

    results = repo.query_results(
        strategy_filter=strategy,
        start_date=start_date,
        end_date=end_date,
        code=code,
        keyword=keyword,
        min_j_value=min_j_value,
        max_j_value=max_j_value,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return {"success": True, "data": results}


@router.get("/strategy/results/dates")
async def get_available_dates(limit: int = Query(30, ge=1, le=100)):
    """获取有结果的交易日期列表"""
    from web.backend.services import strategy_result_repository as repo
    dates = repo.get_available_trade_dates(limit)
    return {"success": True, "data": dates}


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
            yield {"event": msg["event"], "data": json.dumps(msg["data"], ensure_ascii=False, default=str)}

    return EventSourceResponse(event_generator())


@router.get("/strategy/runs")
async def get_strategy_runs(
    run_type: str = Query(None),
    status: str = Query(None),
    strategy: str = Query("all", pattern="^(all|b1|b2|bowl)$"),
    date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """查询最近运行记录"""
    from web.backend.services import strategy_result_repository as repo
    runs = repo.list_runs(
        run_type=run_type,
        status=status,
        strategy_filter=None if strategy == 'all' else strategy,
        date=date,
        page=page,
        per_page=per_page,
    )
    return {"success": True, "data": runs}


@router.get("/strategy/runs/{run_id}")
async def get_strategy_run_detail(run_id: str):
    """查询单次作业摘要"""
    from web.backend.services import strategy_result_repository as repo
    run = repo.get_run(run_id)
    if not run:
        return {"success": False, "message": "作业不存在"}
    return {"success": True, "data": run}


@router.get("/strategy/runs/{run_id}/events")
async def get_strategy_run_events(run_id: str, limit: int = Query(500, ge=1, le=2000)):
    """查询单次作业事件归档"""
    from web.backend.services import strategy_result_repository as repo
    events = repo.get_run_events(run_id, limit)
    return {"success": True, "data": events}
