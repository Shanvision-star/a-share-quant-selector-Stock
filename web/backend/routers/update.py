"""数据更新接口"""
from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["数据更新"])


@router.post("/update")
async def trigger_update(
    auto_rebuild: bool = Query(True),
    date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    pipeline: bool = Query(False),
    allow_intraday_fast: bool = Query(False),
    init_if_empty: bool = Query(True),
    strategies: str = Query(None, description="按策略筛选；逗号分隔，如 b1,b2,bowl,brick,zettaranc；为空或 all 表示全部"),
):
    """触发数据更新（SSE 流式返回进度）
    auto_rebuild=True 时，更新完成后自动执行全策略缓存重建。
    pipeline=True 且 auto_rebuild=False 时，更新阶段内联筛选；自动重建时在阶段二统一筛选并实时推送。
    allow_intraday_fast=True 时，允许盘中手动使用当天快照；15:00 后会自动使用快路径。
    init_if_empty=True 时，首次无数据会先自动执行全量初始化再继续日更。
    strategies 为逗号分隔的策略集合（b1/b2/bowl/brick/zettaranc），为空或包含 all 时按全部执行。
    """
    from web.backend.services.data_service import run_data_update

    requested = None
    if strategies:
        requested = [s.strip().lower() for s in strategies.split(',') if s.strip()]
        if not requested or 'all' in requested:
            requested = None

    async def event_generator():
        async for msg in run_data_update(
            auto_rebuild=auto_rebuild,
            target_date=date,
            pipeline=pipeline,
            allow_intraday_fast=allow_intraday_fast,
            init_if_empty=init_if_empty,
            strategies=requested,
        ):
            yield {"event": msg["event"], "data": json.dumps(msg["data"], ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/data/init")
async def trigger_init(max_stocks: int = Query(None, ge=1)):
    """触发首次全量初始化（SSE 流式返回进度）。"""
    from web.backend.services.data_service import run_data_init

    async def event_generator():
        async for msg in run_data_init(max_stocks=max_stocks):
            yield {"event": msg["event"], "data": json.dumps(msg["data"], ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.get("/data/status")
def get_data_status():
    """获取数据新鲜度报告"""
    logger.debug("GET /api/data/status 被调用")
    from web.backend.services.data_service import get_data_status
    status = get_data_status()
    logger.debug("GET /api/data/status 返回: total_stocks=%s, is_fresh=%s", status.get("total_stocks"), status.get("is_fresh"))
    return {"success": True, "data": status}


@router.get("/data/init-status")
def get_init_status():
    """
    首次运行检测：判断本地数据目录是否为空或严重过期。
    返回:
      state: "empty"  — 本地无数据，需要全量初始化
             "stale"  — 数据严重过期（max_lag_days 由调用方判断）
             "ready"  — 数据基本正常
      message: 人类可读说明
      total_stocks: 本地股票CSV总数
      max_lag_days: 全部 CSV 首行中最旧有效日期的滞后天数
    """
    # 文件枚举和 CSV 读取交给 FastAPI 线程池，避免首页检查阻塞 Agent/MCP 回读。
    logger.debug("GET /api/data/init-status 被调用")
    try:
        from web.backend.services.data_service import csv_manager
        from web.backend.services.strategy_service import get_latest_trade_date
        from datetime import datetime

        all_stocks = csv_manager.list_all_stocks()
        total = len(all_stocks)
        logger.debug("init-status: 共检测到 %d 只股票CSV", total)

        if total == 0:
            result = {
                "state": "empty",
                "message": "本地数据目录为空，请先执行全量数据初始化。",
                "total_stocks": 0,
                "max_lag_days": 0,
            }
            logger.info("init-status: state=empty，本地无数据")
            return {"success": True, "data": result}

        # 全量只读首行，少数停牌/退市记录不能代表整个市场的新鲜度。
        expected_date = get_latest_trade_date()
        expected = datetime.strptime(expected_date, '%Y-%m-%d').date()
        max_lag = 0
        latest_date = None
        current_count = 0
        severely_stale = 0
        invalid_count = 0
        for code in all_stocks:
            stock_date = csv_manager.read_latest_date(code)
            if stock_date is None or stock_date > expected:
                invalid_count += 1
                continue
            lag = (expected - stock_date).days
            max_lag = max(max_lag, lag)
            latest_date = max(latest_date or stock_date, stock_date)
            current_count += lag == 0
            severely_stale += lag > 30

        stale = (severely_stale + invalid_count) / total >= 0.3
        result = {
            "state": "stale" if stale else "ready",
            "message": (
                f"{severely_stale} 只股票超过 30 天未更新，{invalid_count} 只日期异常，请检查并更新数据。"
                if stale else
                f"{current_count}/{total} 只到达 {expected_date}，其余 {total - current_count} 只待检查或无当日行情。"
            ),
            "total_stocks": total,
            "max_lag_days": max_lag,
            "expected_date": expected_date,
            "latest_date": latest_date.isoformat() if latest_date else None,
            "checked_count": total,
            "current_count": current_count,
            "lagging_count": total - current_count - invalid_count,
            "severely_stale_count": severely_stale,
            "invalid_count": invalid_count,
        }

        return {"success": True, "data": result}

    except Exception as e:
        logger.exception("init-status 检测异常: %s", e)
        return {
            "success": False,
            "data": {
                "state": "ready",
                "message": f"状态检测失败（{e}），默认跳过初始化。",
                "total_stocks": 0,
                "max_lag_days": 0,
            },
        }


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
