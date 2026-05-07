"""回测服务：复用策略结果、人工选股池和本地 CSV 行情。"""
import json
from pathlib import Path
import re
from typing import Optional

import pandas as pd

from utils.csv_manager import CSVManager
from utils.technical import calculate_zhixing_trend
from web.backend.backtest_engine.data_portal import CachingDailyDataPortal, CsvMinuteDataPortal, FunctionDailyDataPortal
from web.backend.backtest_engine.engine import BacktestEngine
from web.backend.backtest_engine.models import BacktestParams, SignalCandidate
from web.backend.backtest_engine.signal_source import StaticSignalSource
from web.backend.services import manual_selection_service
from web.backend.services import strategy_result_repository as strategy_repo


project_root = Path(__file__).resolve().parents[3]
csv_manager = CSVManager(str(project_root / "data"))
_stock_names_cache: Optional[dict] = None


def _load_stock_names() -> dict:
    global _stock_names_cache
    if _stock_names_cache is not None:
        return _stock_names_cache
    names_path = project_root / 'data' / 'stock_names.json'
    if names_path.exists():
        with open(names_path, 'r', encoding='utf-8') as file:
            _stock_names_cache = json.load(file)
    else:
        _stock_names_cache = {}
    return _stock_names_cache


def _stock_name(code: str) -> str:
    return _load_stock_names().get(code, '')


def _normalize_codes(values) -> list[str]:
    if not values:
        return []
    normalized = []
    for raw in values:
        code = str(raw or '').strip()
        if re.fullmatch(r'\d{6}', code) and code not in normalized:
            normalized.append(code)
    return normalized


def _load_price_frame(code: str) -> pd.DataFrame:
    frame = csv_manager.read_stock(code)
    if frame.empty:
        return frame
    frame = frame.copy()
    frame['date'] = pd.to_datetime(frame['date'])
    for column in ('open', 'high', 'low', 'close'):
        frame[column] = pd.to_numeric(frame[column], errors='coerce')
    frame = frame.dropna(subset=['date', 'open', 'high', 'low', 'close']).sort_values('date').reset_index(drop=True)
    trend = calculate_zhixing_trend(frame)
    frame['short_term_trend'] = trend['short_term_trend']
    frame['bull_bear_line'] = trend['bull_bear_line']
    return frame


def _fetch_strategy_candidates(params: dict, code: Optional[str] = None) -> list[dict]:
    all_items: list[dict] = []
    page = 1
    per_page = 200
    while page <= 100:
        payload = strategy_repo.query_results(
            strategy_filter=params.get('strategy', 'all'),
            start_date=params['start_date'],
            end_date=params['end_date'],
            code=code,
            page=page,
            per_page=per_page,
            sort_by='signal_date',
            sort_order='asc',
        )
        page_items = payload.get('items') or []
        all_items.extend(page_items)
        if len(page_items) < per_page or len(all_items) >= payload.get('total', 0):
            break
        page += 1
    return all_items


def _expand_codes_via_strategy(params: dict, codes: list[str]) -> tuple[list[dict], list[str]]:
    """对每个 input code 展开为策略命中过的 candidate；返回 (展开后的 candidates, 无命中的 code 列表)。"""
    expanded: list[dict] = []
    no_hit: list[str] = []
    for code in codes:
        items = _fetch_strategy_candidates(params, code=code)
        if not items:
            no_hit.append(code)
            continue
        for item in items:
            signal_date = item.get('signal_date') or item.get('trade_date')
            if not signal_date:
                continue
            expanded.append({
                'code': code,
                'name': item.get('name') or _stock_name(code),
                'strategy_name': item.get('strategy_name', ''),
                'trade_date': item.get('trade_date') or signal_date,
                'signal_date': signal_date,
                'source': 'codes',
            })
    return expanded, no_hit


def _fetch_candidates(params: dict) -> list[dict]:
    source = params.get('source', 'manual')
    selected_codes = set(_normalize_codes(params.get('selected_codes')))

    if source == 'strategy' and params.get('selected_candidates'):
        candidates = []
        for item in params.get('selected_candidates') or []:
            signal_date = item.get('signal_date') or item.get('trade_date')
            if not item.get('code') or not signal_date:
                continue
            candidates.append({
                'code': item['code'],
                'name': item.get('name') or _stock_name(item['code']),
                'strategy_name': item.get('strategy_name', ''),
                'trade_date': item.get('trade_date') or signal_date,
                'signal_date': signal_date,
                'source': 'strategy',
            })
        return candidates

    if source == 'codes':
        codes = _normalize_codes(params.get('input_codes'))
        if not codes:
            return []
        expanded, no_hit = _expand_codes_via_strategy(params, codes)
        if no_hit and bool(params.get('codes_fallback_to_start_date', False)):
            for code in no_hit:
                expanded.append({
                    'code': code,
                    'name': _stock_name(code),
                    'strategy_name': '输入个股(无信号回退)',
                    'trade_date': params['start_date'],
                    'signal_date': params['start_date'],
                    'source': 'codes',
                })
        return expanded

    if source == 'manual':
        items = manual_selection_service.list_selections(
            start_date=params['start_date'],
            end_date=params['end_date'],
        )
        candidates = [
            {
                'code': item['code'],
                'name': item.get('name', ''),
                'strategy_name': item.get('strategy_name', 'manual'),
                'trade_date': item['selection_date'],
                'signal_date': item.get('source_signal_date') or item.get('source_trade_date') or item['selection_date'],
                'source': 'manual',
            }
            for item in items
        ]
        return [item for item in candidates if not selected_codes or item['code'] in selected_codes]

    # source == 'strategy' 且未带 selected_candidates：若 input_codes 非空，按 code 分别展开
    input_codes = _normalize_codes(params.get('input_codes'))
    if source == 'strategy' and input_codes:
        expanded, _ = _expand_codes_via_strategy(params, input_codes)
        for item in expanded:
            item['source'] = 'strategy'
        return [item for item in expanded if not selected_codes or item['code'] in selected_codes]

    items = _fetch_strategy_candidates(params)
    candidates = []
    for item in items:
        signal_date = item.get('signal_date') or item.get('trade_date')
        if not item.get('code') or not signal_date:
            continue
        candidates.append({
            'code': item['code'],
            'name': item.get('name', ''),
            'strategy_name': item.get('strategy_name', ''),
            'trade_date': item.get('trade_date') or signal_date,
            'signal_date': signal_date,
            'source': 'strategy',
        })
    return [item for item in candidates if not selected_codes or item['code'] in selected_codes]


def run_backtest(params: dict) -> dict:
    candidates = [SignalCandidate.from_mapping(item) for item in _fetch_candidates(params)]
    engine = BacktestEngine(
        signal_source=StaticSignalSource(candidates),
        daily_portal=CachingDailyDataPortal(FunctionDailyDataPortal(_load_price_frame)),
        minute_portal=CsvMinuteDataPortal(project_root / "data" / "minute"),
    )
    return engine.run(BacktestParams.from_mapping(params))
