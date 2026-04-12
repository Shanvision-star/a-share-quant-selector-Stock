"""K线数据接口"""
from fastapi import APIRouter, Query, HTTPException

router = APIRouter(prefix="/api", tags=["K线数据"])


@router.get("/kline/{code}")
async def get_kline(
    code: str,
    period: str = Query("daily", pattern="^(daily|weekly)$"),
    limit: int = Query(250, ge=30, le=1000),
):
    """
    获取 K 线数据
    - code: 股票代码（如 000001）
    - period: daily / weekly
    - limit: 返回条数（30-1000）
    """
    from web.backend.services.kline_service import get_kline
    result = get_kline(code, period, limit)
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
