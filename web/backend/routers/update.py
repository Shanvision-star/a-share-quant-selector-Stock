"""数据更新接口"""
from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse
import json
import logging
from typing import List

logger = logging.getLogger(__name__)

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
    logger.debug("GET /api/data/status 被调用")
    from web.backend.services.data_service import get_data_status
    status = get_data_status()
    logger.debug("GET /api/data/status 返回: total_stocks=%s, is_fresh=%s", status.get("total_stocks"), status.get("is_fresh"))
    return {"success": True, "data": status}


@router.get("/data/init-status")
async def get_init_status():
    """
    首次运行检测：判断本地数据目录是否为空或严重过期。
    返回:
      state: "empty"  — 本地无数据，需要全量初始化
             "stale"  — 数据严重过期（max_lag_days 由调用方判断）
             "ready"  — 数据基本正常
      message: 人类可读说明
      total_stocks: 本地股票CSV总数
      max_lag_days: 最旧数据与今日相差天数（粗略估算）
    """
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

        # 抽样检查最旧数据日期
        import random
        sample = random.sample(all_stocks, min(20, total))
        expected_date = get_latest_trade_date()
        max_lag = 0

        for code in sample:
            df = csv_manager.read_stock(code)
            if not df.empty:
                stock_date = df.iloc[0]['date']
                if hasattr(stock_date, 'strftime'):
                    stock_date_str = stock_date.strftime('%Y-%m-%d')
                else:
                    stock_date_str = str(stock_date)[:10]
                try:
                    lag = (datetime.strptime(expected_date, '%Y-%m-%d') - datetime.strptime(stock_date_str, '%Y-%m-%d')).days
                    if lag > max_lag:
                        max_lag = lag
                except Exception:
                    pass

        logger.debug("init-status: expected_date=%s, max_lag_days=%d", expected_date, max_lag)

        if max_lag > 30:
            result = {
                "state": "stale",
                "message": f"本地数据已超过 {max_lag} 天未更新，建议重新同步行情数据。",
                "total_stocks": total,
                "max_lag_days": max_lag,
            }
            logger.info("init-status: state=stale, max_lag_days=%d", max_lag)
        else:
            result = {
                "state": "ready",
                "message": f"本地数据正常，共 {total} 只股票，最新数据距今 {max_lag} 天。",
                "total_stocks": total,
                "max_lag_days": max_lag,
            }
            logger.debug("init-status: state=ready, total=%d", total)

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
