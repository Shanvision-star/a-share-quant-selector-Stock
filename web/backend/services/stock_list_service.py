"""股票列表编排服务。"""

from typing import Iterable

_SORT_NEEDS_METRICS = {
    "latest_price",
    "change_pct",
    "market_cap",
    "latest_date",
    "k_value",
    "d_value",
    "j_value",
}


def filter_codes(codes: Iterable[str], stock_names: dict[str, str], search: str = "") -> list[str]:
    """按股票代码/名称过滤代码列表。"""
    code_list = list(codes)
    if not search:
        return code_list

    search_lower = search.lower()
    return [
        code
        for code in code_list
        if search_lower in code or search_lower in stock_names.get(code, "").lower()
    ]


def sort_codes(
    codes: Iterable[str],
    stock_names: dict[str, str],
    sort_by: str = "code",
    reverse: bool = False,
) -> list[str]:
    """按代码或名称排序。"""
    code_list = list(codes)
    if sort_by == "name":
        return sorted(code_list, key=lambda code: (stock_names.get(code, "未知"), code), reverse=reverse)
    return sorted(code_list, reverse=reverse)


def paginate_codes(codes: Iterable[str], page: int, per_page: int) -> tuple[list[str], int]:
    """分页截取代码列表并返回总数。"""
    code_list = list(codes)
    start = (page - 1) * per_page
    return code_list[start:start + per_page], len(code_list)


def build_stock_list_response(
    *,
    stocks: Iterable[str],
    stock_names: dict[str, str],
    csv_manager,
    page: int,
    per_page: int,
    search: str,
    sort_by: str,
    sort_order: str,
    ensure_metric_snapshot,
    build_stock_item,
    trigger_metric_snapshot_prewarm,
) -> dict:
    """编排股票列表查询并返回统一响应结构。"""
    filtered_codes = filter_codes(stocks, stock_names, search)
    reverse = sort_order == "desc"

    if sort_by in _SORT_NEEDS_METRICS:
        snapshot = ensure_metric_snapshot(filtered_codes, stock_names, csv_manager, wait=True)
        if snapshot and snapshot["sorted_codes"].get(sort_by):
            ordered_codes = snapshot["sorted_codes"][sort_by]
            if reverse:
                ordered_codes = list(reversed(ordered_codes))
            if search:
                allowed_codes = set(filtered_codes)
                ordered_codes = [code for code in ordered_codes if code in allowed_codes]
            page_codes, total = paginate_codes(ordered_codes, page=page, per_page=per_page)
        else:
            fallback_items = []
            for code in filtered_codes:
                item = build_stock_item(
                    code,
                    stock_names,
                    csv_manager,
                    include_kdj=True,
                    include_mini_kline=False,
                )
                if item:
                    fallback_items.append(item)

            fallback_items.sort(
                key=lambda item: (item.get(sort_by), item.get("code")),
                reverse=reverse,
            )
            fallback_codes = [item["code"] for item in fallback_items]
            page_codes, total = paginate_codes(fallback_codes, page=page, per_page=per_page)

        stock_list = []
        for code in page_codes:
            full_item = build_stock_item(
                code,
                stock_names,
                csv_manager,
                include_kdj=True,
                include_mini_kline=True,
            )
            if full_item:
                stock_list.append(full_item)
    else:
        trigger_metric_snapshot_prewarm(filtered_codes, stock_names, csv_manager)
        if sort_by == "name":
            ordered_codes = sort_codes(filtered_codes, stock_names, sort_by="name", reverse=reverse)
        else:
            ordered_codes = sort_codes(filtered_codes, stock_names, sort_by="code", reverse=reverse)
        page_codes, total = paginate_codes(ordered_codes, page=page, per_page=per_page)

        stock_list = []
        for code in page_codes:
            item = build_stock_item(
                code,
                stock_names,
                csv_manager,
                include_kdj=True,
                include_mini_kline=True,
            )
            if item:
                stock_list.append(item)

    return {
        "success": True,
        "data": stock_list,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }
