"""股票列表编排服务。"""

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, TypedDict

METRIC_SORT_FIELDS = (
    "latest_price",
    "change_pct",
    "market_cap",
    "latest_date",
    "k_value",
    "d_value",
    "j_value",
)

_SORT_NEEDS_METRICS = {
    *METRIC_SORT_FIELDS,
}


class MetricSnapshotPayload(TypedDict, total=False):
    """指标快照响应。"""

    items_by_code: dict[str, dict[str, Any]]
    sorted_codes: dict[str, list[str]]


class StockListResponsePayload(TypedDict):
    """股票列表接口统一响应。"""

    success: bool
    data: list[dict[str, Any]]
    total: int
    page: int
    per_page: int
    total_pages: int


class EnsureMetricSnapshot(Protocol):
    """构建/读取指标快照回调。"""

    def __call__(
        self,
        stocks: list[str],
        stock_names: dict[str, str],
        csv_manager: Any,
        wait: bool,
    ) -> MetricSnapshotPayload | None:
        ...


class BuildStockItem(Protocol):
    """构建单个股票项回调。"""

    def __call__(
        self,
        code: str,
        stock_names: dict[str, str],
        csv_manager: Any,
        include_kdj: bool = True,
        include_mini_kline: bool = True,
    ) -> dict[str, Any] | None:
        ...


class TriggerMetricSnapshotPrewarm(Protocol):
    """指标快照预热回调。"""

    def __call__(self, stocks: list[str], stock_names: dict[str, str], csv_manager: Any) -> None:
        ...


class LoadStockNames(Protocol):
    """股票名称加载回调。"""

    def __call__(self) -> dict[str, str]:
        ...


@dataclass(frozen=True)
class _StockListBuildContext:
    all_codes: list[str]
    stock_names: dict[str, str]
    csv_manager: Any
    page: int
    per_page: int
    sort_by: str
    reverse: bool
    allowed_codes: set[str] | None
    build_stock_item: BuildStockItem


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


def normalize_pagination(page: int, per_page: int) -> tuple[int, int]:
    """标准化分页参数，保障服务层分页安全。"""
    try:
        safe_page = int(page)
    except (TypeError, ValueError):
        safe_page = 1

    try:
        safe_per_page = int(per_page)
    except (TypeError, ValueError):
        safe_per_page = 10

    if safe_page < 1:
        safe_page = 1
    if safe_per_page < 10:
        safe_per_page = 10
    return safe_page, safe_per_page


def _build_full_stock_list(context: _StockListBuildContext, page_codes: Iterable[str]) -> list[dict[str, Any]]:
    stock_list: list[dict[str, Any]] = []
    for code in page_codes:
        item = context.build_stock_item(
            code,
            context.stock_names,
            context.csv_manager,
            include_kdj=True,
            include_mini_kline=True,
        )
        if item:
            stock_list.append(item)
    return stock_list


def _resolve_metric_page_codes(
    context: _StockListBuildContext,
    ensure_metric_snapshot: EnsureMetricSnapshot,
) -> tuple[list[str], int]:
    snapshot = ensure_metric_snapshot(context.all_codes, context.stock_names, context.csv_manager, wait=True)
    snapshot_sorted_codes = snapshot.get("sorted_codes") if isinstance(snapshot, dict) else None

    if isinstance(snapshot_sorted_codes, dict) and snapshot_sorted_codes.get(context.sort_by):
        ordered_codes = snapshot_sorted_codes[context.sort_by]
        if context.reverse:
            ordered_codes = list(reversed(ordered_codes))
        if context.allowed_codes is not None:
            ordered_codes = [code for code in ordered_codes if code in context.allowed_codes]
        return paginate_codes(ordered_codes, page=context.page, per_page=context.per_page)

    fallback_items: list[dict[str, Any]] = []
    for code in context.all_codes:
        item = context.build_stock_item(
            code,
            context.stock_names,
            context.csv_manager,
            include_kdj=True,
            include_mini_kline=False,
        )
        if item:
            fallback_items.append(item)

    fallback_items.sort(
        key=lambda item: (item.get(context.sort_by), item.get("code")),
        reverse=context.reverse,
    )
    fallback_codes = [item["code"] for item in fallback_items]
    if context.allowed_codes is not None:
        fallback_codes = [code for code in fallback_codes if code in context.allowed_codes]
    return paginate_codes(fallback_codes, page=context.page, per_page=context.per_page)


def _build_metric_sort_response(
    context: _StockListBuildContext,
    ensure_metric_snapshot: EnsureMetricSnapshot,
) -> tuple[list[dict[str, Any]], int]:
    page_codes, total = _resolve_metric_page_codes(context, ensure_metric_snapshot)
    return _build_full_stock_list(context, page_codes), total


def _build_non_metric_sort_response(
    context: _StockListBuildContext,
    trigger_metric_snapshot_prewarm: TriggerMetricSnapshotPrewarm,
) -> tuple[list[dict[str, Any]], int]:
    trigger_metric_snapshot_prewarm(context.all_codes, context.stock_names, context.csv_manager)
    if context.sort_by == "name":
        ordered_codes = sort_codes(context.all_codes, context.stock_names, sort_by="name", reverse=context.reverse)
    else:
        ordered_codes = sort_codes(context.all_codes, context.stock_names, sort_by="code", reverse=context.reverse)
    if context.allowed_codes is not None:
        ordered_codes = [code for code in ordered_codes if code in context.allowed_codes]

    page_codes, total = paginate_codes(ordered_codes, page=context.page, per_page=context.per_page)
    return _build_full_stock_list(context, page_codes), total


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
    ensure_metric_snapshot: EnsureMetricSnapshot,
    build_stock_item: BuildStockItem,
    trigger_metric_snapshot_prewarm: TriggerMetricSnapshotPrewarm,
) -> StockListResponsePayload:
    """编排股票列表查询并返回统一响应结构。"""
    page, per_page = normalize_pagination(page, per_page)
    all_codes = list(stocks)
    filtered_codes = filter_codes(all_codes, stock_names, search)
    allowed_codes = set(filtered_codes) if search else None

    context = _StockListBuildContext(
        all_codes=all_codes,
        stock_names=stock_names,
        csv_manager=csv_manager,
        page=page,
        per_page=per_page,
        sort_by=sort_by,
        reverse=sort_order == "desc",
        allowed_codes=allowed_codes,
        build_stock_item=build_stock_item,
    )

    if sort_by in _SORT_NEEDS_METRICS:
        stock_list, total = _build_metric_sort_response(context, ensure_metric_snapshot)
    else:
        stock_list, total = _build_non_metric_sort_response(context, trigger_metric_snapshot_prewarm)

    return {
        "success": True,
        "data": stock_list,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
    }


def build_stock_list_response_from_sources(
    *,
    csv_manager,
    load_stock_names: LoadStockNames,
    page: int,
    per_page: int,
    search: str,
    sort_by: str,
    sort_order: str,
    ensure_metric_snapshot: EnsureMetricSnapshot,
    build_stock_item: BuildStockItem,
    trigger_metric_snapshot_prewarm: TriggerMetricSnapshotPrewarm,
) -> StockListResponsePayload:
    """从数据源加载股票清单后编排统一响应。"""
    stock_names = load_stock_names()
    stocks = sorted({
        code
        for code in csv_manager.list_all_stocks()
        if code.isdigit() and len(code) == 6
    })
    return build_stock_list_response(
        stocks=stocks,
        stock_names=stock_names,
        csv_manager=csv_manager,
        page=page,
        per_page=per_page,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        ensure_metric_snapshot=ensure_metric_snapshot,
        build_stock_item=build_stock_item,
        trigger_metric_snapshot_prewarm=trigger_metric_snapshot_prewarm,
    )
