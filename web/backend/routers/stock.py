"""股票列表接口"""
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api", tags=["股票列表"])


@router.get("/stock/list")
async def get_stock_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=500),
    search: str = Query("", max_length=20),
):
    """
    获取股票列表（分页）
    - page: 页码
    - per_page: 每页数量
    - search: 搜索关键词（代码或名称）
    """
    from web.backend.services.kline_service import csv_manager, _load_stock_names

    stock_names = _load_stock_names()
    stocks = csv_manager.list_all_stocks()

    # 搜索过滤
    if search:
        search_lower = search.lower()
        stocks = [
            c for c in stocks
            if search_lower in c or search_lower in stock_names.get(c, '').lower()
        ]

    total = len(stocks)
    start = (page - 1) * per_page
    paginated = stocks[start:start + per_page]

    stock_list = []
    for code in paginated:
        df = csv_manager.read_stock(code)
        if not df.empty and len(df) >= 2:
            latest = df.iloc[0]
            prev = df.iloc[1]
            prev_close = float(prev['close'])
            change_pct = ((float(latest['close']) - prev_close) / prev_close * 100) if prev_close else 0

            stock_list.append({
                'code': code,
                'name': stock_names.get(code, '未知'),
                'latest_price': round(float(latest['close']), 2),
                'change_pct': round(change_pct, 2),
                'latest_date': latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else str(latest['date'])[:10],
                'market_cap': round(float(latest.get('market_cap', 0)) / 1e8, 2),
                'data_count': len(df),
            })

    return {
        "success": True,
        "data": stock_list,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }
