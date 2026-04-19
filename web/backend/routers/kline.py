"""K线数据接口"""
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/api", tags=["K线数据"])


@router.get("/kline/{code}")
async def get_kline(
    code: str,
    period: str = Query("daily", pattern="^(daily|weekly)$"),
    limit: int = Query(2600, ge=120, le=3200),
    adjust: str = Query("qfq", pattern="^(qfq|hfq|nfq)$"),
):
    """
    获取 K 线数据
    - code: 股票代码（如 000001）
    - period: daily / weekly
    - limit: 返回条数（120-3200，默认约10年日线）
    - adjust: qfq=前复权（默认）| hfq=后复权 | nfq=不复权
    """
    from web.backend.services.kline_service import get_kline
    result = get_kline(code, period, limit, adjust)
    if result is None:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不存在")
    return {"success": True, "data": result}


@router.get("/stock/price/{code}")
async def get_stock_price(code: str):
    """获取股票价格面板信息（右侧面板用）"""
    from web.backend.services.kline_service import get_stock_price_info
    result = get_stock_price_info(code)
    if result is None:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不存在")
    return {"success": True, "data": result}


@router.get("/stock/mini-kline/{code}")
async def get_mini_kline(code: str, days: int = Query(30, ge=5, le=90)):
    """迷你 K 线数据（首页缩略图）"""
    from web.backend.services.kline_service import get_mini_kline
    result = get_mini_kline(code, days)
    return {"success": True, "data": result}


@router.get("/kline/{code}/intraday")
async def get_intraday_kline_route(
    code: str,
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    period: str = Query("1", pattern="^(1|15)$"),
):
    """
    获取单日分时K线（仅供日K线弹窗使用）
    - date: 日期字符串，格式 YYYY-MM-DD
    - period: 分钟级别，1 或 15
    """
    from web.backend.services.kline_service import get_intraday_kline
    result = get_intraday_kline(code, date, period)
    return {"success": True, "data": result}


@router.get("/stock/info/{code}")
async def get_stock_info(code: str):
    """获取股票扩展信息：行业/地区/经营范围 + 概念标签（懒加载，有后端缓存）"""
    from web.backend.services.kline_service import get_stock_concept_tags, _fetch_stock_extra_info
    extra = _fetch_stock_extra_info(code)
    tags = get_stock_concept_tags(code)
    return {"success": True, "data": {
        "industry": extra.get('industry', ''),
        "region": extra.get('region', ''),
        "main_business": extra.get('main_business', ''),
        "concept_tags": tags,
    }}
