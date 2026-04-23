"""股票列表接口"""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import math
import os
from pathlib import Path
import threading

import pandas as pd

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from web.backend.services.stock_list_service import METRIC_SORT_FIELDS, build_stock_list_response

router = APIRouter(prefix="/api", tags=["股票列表"])
logger = logging.getLogger(__name__)

_SORT_BY_PATTERN = f"^(code|name|{'|'.join(METRIC_SORT_FIELDS)})$"
_STOCK_ITEM_CACHE: dict[tuple[str, bool, bool], tuple[int, dict]] = {}
_STOCK_ITEM_CACHE_LOCK = threading.Lock()
_METRIC_SNAPSHOT_FILE = Path(__file__).resolve().parents[3] / 'data' / 'stock_list_metrics_cache.json'
_METRIC_SNAPSHOT_STATE = {
    'generation': 0,
    'signature': (),
    'building': False,
    'ready': False,
    'event': threading.Event(),
    'items_by_code': {},
    'sorted_codes': {},
}
_METRIC_SNAPSHOT_LOCK = threading.Lock()


def _safe_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if (math.isnan(number) or math.isinf(number)) else number


def _resolve_stock_csv_path(code: str, csv_manager) -> Path | None:
    # 兼容两种存储结构：data/60/600000.csv 和历史遗留的 data/600000.csv。
    canonical = csv_manager.get_stock_path(code)
    if canonical.exists():
        return canonical

    legacy = Path(csv_manager.data_dir) / f"{code}.csv"
    if legacy.exists():
        return legacy
    return None


def _read_stock_preview(csv_path: Path, nrows: int = 60) -> pd.DataFrame:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return pd.DataFrame()

    try:
        df = pd.read_csv(
            csv_path,
            usecols=lambda column: column in {'date', 'open', 'high', 'low', 'close', 'volume', 'market_cap'},
            nrows=nrows,
        )
        required_columns = {'date', 'open', 'high', 'low', 'close'}
        if not required_columns.issubset(df.columns):
            return pd.DataFrame()
        if 'market_cap' not in df.columns:
            df['market_cap'] = 0
        if 'volume' not in df.columns:
            df['volume'] = 0
        return df
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        logger.warning("Failed reading stock preview from %s: %s", csv_path, exc, exc_info=True)
        return pd.DataFrame()


def _calculate_latest_kdj(df: pd.DataFrame, n: int = 9, m1: int = 3, m2: int = 3) -> tuple[float, float, float]:
    if df.empty:
        return 0.0, 0.0, 0.0

    date_values = df['date'].tolist()
    is_descending = len(date_values) >= 2 and str(date_values[0]) > str(date_values[-1])
    df_calc = df.iloc[::-1] if is_descending else df

    lows = [_safe_float(value) for value in df_calc['low'].tolist()]
    highs = [_safe_float(value) for value in df_calc['high'].tolist()]
    closes = [_safe_float(value) for value in df_calc['close'].tolist()]

    k_value = 50.0
    d_value = 50.0

    for index in range(1, len(closes)):
        window_start = max(0, index - n + 1)
        low_min = min(lows[window_start:index + 1])
        high_max = max(highs[window_start:index + 1])

        if index < n - 1 or high_max == low_min:
            rsv = 50.0
        else:
            rsv = (closes[index] - low_min) / (high_max - low_min) * 100

        k_value = (rsv + k_value * (m1 - 1)) / m1
        d_value = (k_value + d_value * (m2 - 1)) / m2

    j_value = 3 * k_value - 2 * d_value
    return round(k_value, 2), round(d_value, 2), round(j_value, 2)


def _load_metric_snapshot_from_disk(signature: tuple[str, ...]):
    if not _METRIC_SNAPSHOT_FILE.exists():
        return None

    try:
        with open(_METRIC_SNAPSHOT_FILE, 'r', encoding='utf-8') as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed loading metric snapshot from %s: %s", _METRIC_SNAPSHOT_FILE, exc, exc_info=True)
        return None

    if payload.get('signature') != list(signature):
        return None

    items_by_code = payload.get('items_by_code') or {}
    sorted_codes = payload.get('sorted_codes') or {}
    if not items_by_code or not sorted_codes:
        return None

    return {
        'items_by_code': items_by_code,
        'sorted_codes': sorted_codes,
    }


def _save_metric_snapshot_to_disk(signature: tuple[str, ...], items_by_code: dict[str, dict], sorted_codes: dict[str, list[str]]):
    try:
        _METRIC_SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file = _METRIC_SNAPSHOT_FILE.with_suffix('.tmp')
        payload = {
            'signature': list(signature),
            'items_by_code': items_by_code,
            'sorted_codes': sorted_codes,
        }
        with open(temp_file, 'w', encoding='utf-8') as file:
            json.dump(payload, file, ensure_ascii=False)
        temp_file.replace(_METRIC_SNAPSHOT_FILE)
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("Failed saving metric snapshot to %s: %s", _METRIC_SNAPSHOT_FILE, exc, exc_info=True)


def invalidate_stock_list_cache():
    with _STOCK_ITEM_CACHE_LOCK:
        _STOCK_ITEM_CACHE.clear()
    try:
        if _METRIC_SNAPSHOT_FILE.exists():
            _METRIC_SNAPSHOT_FILE.unlink()
    except OSError as exc:
        logger.warning("Failed invalidating metric snapshot file %s: %s", _METRIC_SNAPSHOT_FILE, exc, exc_info=True)
    with _METRIC_SNAPSHOT_LOCK:
        _METRIC_SNAPSHOT_STATE['generation'] += 1
        _METRIC_SNAPSHOT_STATE['signature'] = ()
        _METRIC_SNAPSHOT_STATE['building'] = False
        _METRIC_SNAPSHOT_STATE['ready'] = False
        _METRIC_SNAPSHOT_STATE['event'] = threading.Event()
        _METRIC_SNAPSHOT_STATE['items_by_code'] = {}
        _METRIC_SNAPSHOT_STATE['sorted_codes'] = {}


def _build_metric_snapshot(
    stocks: list[str],
    stock_names: dict,
    csv_manager,
    signature: tuple[str, ...],
    generation: int,
    build_event: threading.Event | None = None,
):
    items_by_code: dict[str, dict] = {}
    worker_count = min(16, max(4, (os.cpu_count() or 4) * 2))

    def _task(code: str):
        return code, _build_stock_item(
            code,
            stock_names,
            csv_manager,
            include_kdj=True,
            include_mini_kline=False,
        )

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            for code, item in executor.map(_task, stocks):
                if item:
                    items_by_code[code] = item

        sorted_codes = {
            metric: [
                code for code, _ in sorted(
                    items_by_code.items(),
                    key=lambda entry: (entry[1].get(metric), entry[0]),
                )
            ]
            for metric in METRIC_SORT_FIELDS
        }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.error("Failed building metric snapshot: %s", exc, exc_info=True)
        with _METRIC_SNAPSHOT_LOCK:
            if _METRIC_SNAPSHOT_STATE['generation'] == generation and _METRIC_SNAPSHOT_STATE['signature'] == signature:
                _METRIC_SNAPSHOT_STATE['building'] = False
                _METRIC_SNAPSHOT_STATE['ready'] = False
                _METRIC_SNAPSHOT_STATE['event'].set()
        if build_event:
            build_event.set()
        return

    with _METRIC_SNAPSHOT_LOCK:
        if _METRIC_SNAPSHOT_STATE['generation'] != generation or _METRIC_SNAPSHOT_STATE['signature'] != signature:
            if build_event:
                build_event.set()
            return

        _METRIC_SNAPSHOT_STATE['items_by_code'] = items_by_code
        _METRIC_SNAPSHOT_STATE['sorted_codes'] = sorted_codes
        _METRIC_SNAPSHOT_STATE['building'] = False
        _METRIC_SNAPSHOT_STATE['ready'] = True
        _METRIC_SNAPSHOT_STATE['event'].set()

    _save_metric_snapshot_to_disk(signature, items_by_code, sorted_codes)
    if build_event:
        build_event.set()


def _ensure_metric_snapshot(stocks: list[str], stock_names: dict, csv_manager, wait: bool):
    signature = tuple(stocks)
    start_build = False

    with _METRIC_SNAPSHOT_LOCK:
        if _METRIC_SNAPSHOT_STATE['ready'] and _METRIC_SNAPSHOT_STATE['signature'] == signature:
            return {
                'items_by_code': _METRIC_SNAPSHOT_STATE['items_by_code'],
                'sorted_codes': _METRIC_SNAPSHOT_STATE['sorted_codes'],
            }

        if _METRIC_SNAPSHOT_STATE['building'] and _METRIC_SNAPSHOT_STATE['signature'] == signature:
            event = _METRIC_SNAPSHOT_STATE['event']
            generation = _METRIC_SNAPSHOT_STATE['generation']
        else:
            event = None
            generation = _METRIC_SNAPSHOT_STATE['generation']

    disk_snapshot = _load_metric_snapshot_from_disk(signature)
    if disk_snapshot:
        with _METRIC_SNAPSHOT_LOCK:
            _METRIC_SNAPSHOT_STATE['signature'] = signature
            _METRIC_SNAPSHOT_STATE['building'] = False
            _METRIC_SNAPSHOT_STATE['ready'] = True
            _METRIC_SNAPSHOT_STATE['event'].set()
            _METRIC_SNAPSHOT_STATE['items_by_code'] = disk_snapshot['items_by_code']
            _METRIC_SNAPSHOT_STATE['sorted_codes'] = disk_snapshot['sorted_codes']
        return disk_snapshot

    with _METRIC_SNAPSHOT_LOCK:
        if _METRIC_SNAPSHOT_STATE['ready'] and _METRIC_SNAPSHOT_STATE['signature'] == signature:
            return {
                'items_by_code': _METRIC_SNAPSHOT_STATE['items_by_code'],
                'sorted_codes': _METRIC_SNAPSHOT_STATE['sorted_codes'],
            }

        if _METRIC_SNAPSHOT_STATE['building'] and _METRIC_SNAPSHOT_STATE['signature'] == signature:
            event = _METRIC_SNAPSHOT_STATE['event']
            generation = _METRIC_SNAPSHOT_STATE['generation']
        else:
            generation = _METRIC_SNAPSHOT_STATE['generation'] + 1
            event = threading.Event()
            _METRIC_SNAPSHOT_STATE['generation'] = generation
            _METRIC_SNAPSHOT_STATE['signature'] = signature
            _METRIC_SNAPSHOT_STATE['building'] = True
            _METRIC_SNAPSHOT_STATE['ready'] = False
            _METRIC_SNAPSHOT_STATE['event'] = event
            _METRIC_SNAPSHOT_STATE['items_by_code'] = {}
            _METRIC_SNAPSHOT_STATE['sorted_codes'] = {}
            start_build = True

    if start_build:
        if wait:
            _build_metric_snapshot(stocks, stock_names, csv_manager, signature, generation, event)
        else:
            threading.Thread(
                target=_build_metric_snapshot,
                args=(stocks, stock_names, csv_manager, signature, generation, event),
                daemon=True,
            ).start()
    elif wait:
        event.wait(timeout=20)

    with _METRIC_SNAPSHOT_LOCK:
        if _METRIC_SNAPSHOT_STATE['ready'] and _METRIC_SNAPSHOT_STATE['signature'] == signature:
            return {
                'items_by_code': _METRIC_SNAPSHOT_STATE['items_by_code'],
                'sorted_codes': _METRIC_SNAPSHOT_STATE['sorted_codes'],
            }
    return None


def _trigger_metric_snapshot_prewarm(stocks: list[str], stock_names: dict, csv_manager):
    _ensure_metric_snapshot(stocks, stock_names, csv_manager, wait=False)


def trigger_metric_snapshot_prewarm():
    from web.backend.services.kline_service import csv_manager, _load_stock_names

    stock_names = _load_stock_names()
    stocks = sorted({code for code in csv_manager.list_all_stocks() if code.isdigit() and len(code) == 6})
    if not stocks:
        return
    _trigger_metric_snapshot_prewarm(stocks, stock_names, csv_manager)


def _build_stock_item(
    code: str,
    stock_names: dict,
    csv_manager,
    include_kdj: bool = True,
    include_mini_kline: bool = True,
):
    csv_path = _resolve_stock_csv_path(code, csv_manager)
    if csv_path is None:
        return None

    mtime_ns = csv_path.stat().st_mtime_ns
    cache_key = (code, include_kdj, include_mini_kline)
    with _STOCK_ITEM_CACHE_LOCK:
        cached = _STOCK_ITEM_CACHE.get(cache_key)
    if cached and cached[0] == mtime_ns:
        item = dict(cached[1])
        item['name'] = stock_names.get(code, item.get('name', '未知'))
        return item

    # 列表只依赖最新截面与近60根K线指标，无需整文件读取。
    df = _read_stock_preview(csv_path, nrows=60)
    if df.empty or len(df) < 2:
        return None

    latest = df.iloc[0]
    prev = df.iloc[1]

    latest_close = _safe_float(latest.get('close', 0))
    prev_close = _safe_float(prev.get('close', 0))
    change_pct = ((latest_close - prev_close) / prev_close * 100) if prev_close else 0

    latest_date = latest.get('date')
    if hasattr(latest_date, 'strftime'):
        latest_date_str = latest_date.strftime('%Y-%m-%d')
    else:
        latest_date_str = str(latest_date)[:10]

    market_cap = _safe_float(latest.get('market_cap', 0)) / 1e8

    k_value = 0.0
    d_value = 0.0
    j_value = 0.0
    if include_kdj:
        recent_df = df.head(60)
        if not recent_df.empty:
            try:
                k_value, d_value, j_value = _calculate_latest_kdj(recent_df)
            except (RuntimeError, TypeError, ValueError, ZeroDivisionError) as exc:
                logger.warning("Failed calculating KDJ for %s: %s", code, exc, exc_info=True)

    item = {
        'code': code,
        'name': stock_names.get(code, '未知'),
        'latest_price': round(latest_close, 2),
        'change_pct': round(change_pct, 2),
        'latest_date': latest_date_str,
        'market_cap': round(market_cap, 2),
        'k_value': k_value,
        'd_value': d_value,
        'j_value': j_value,
        'data_count': len(df),
    }

    if include_mini_kline:
        mini_kline = []
        mini_df = df.head(30)
        for i in range(len(mini_df) - 1, -1, -1):
            row = mini_df.iloc[i]
            row_date = row.get('date')
            if hasattr(row_date, 'strftime'):
                date_text = row_date.strftime('%Y-%m-%d')
            else:
                date_text = str(row_date)[:10]
            mini_kline.append([
                date_text,
                round(_safe_float(row.get('open')), 2),
                round(_safe_float(row.get('close')), 2),
                round(_safe_float(row.get('high')), 2),
                round(_safe_float(row.get('low')), 2),
            ])
        item['mini_kline'] = mini_kline

    with _STOCK_ITEM_CACHE_LOCK:
        _STOCK_ITEM_CACHE[cache_key] = (mtime_ns, item)
    return dict(item)


@router.get("/stock/list")
async def get_stock_list(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=500),
    search: str = Query("", max_length=20),
    sort_by: str = Query('code', pattern=_SORT_BY_PATTERN),
    sort_order: str = Query('asc', pattern='^(asc|desc)$'),
):
    """
    获取股票列表（分页）
    - page: 页码
    - per_page: 每页数量
    - search: 搜索关键词（代码或名称）
    """
    from web.backend.services.kline_service import csv_manager, _load_stock_names

    stock_names = _load_stock_names()
    stocks = sorted({code for code in csv_manager.list_all_stocks() if code.isdigit() and len(code) == 6})

    return await run_in_threadpool(
        build_stock_list_response,
        stocks=stocks,
        stock_names=stock_names,
        csv_manager=csv_manager,
        page=page,
        per_page=per_page,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        ensure_metric_snapshot=_ensure_metric_snapshot,
        build_stock_item=_build_stock_item,
        trigger_metric_snapshot_prewarm=_trigger_metric_snapshot_prewarm,
    )
