"""股票列表编排服务。"""

from typing import Iterable


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
