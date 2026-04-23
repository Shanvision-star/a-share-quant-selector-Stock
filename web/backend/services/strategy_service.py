"""策略执行服务 - 调用 strategy_registry"""
import asyncio
import concurrent.futures
import copy
import json
import queue
import sys
import threading
import time
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from strategy.strategy_registry import get_registry
from utils.csv_manager import CSVManager
from web.backend.services import strategy_result_repository as repo
from web.backend.services.config_service import get_config_with_revision, save_config, update_config_with_revision

csv_manager = CSVManager(str(project_root / "data"))
WEB_STRATEGY_RESULTS_FILE = project_root / "data" / "web_strategy_results.json"
WEB_STRATEGY_SCHEMA_VERSION = 1

_STRATEGY_CACHE = {}
_STRATEGY_CACHE_LOCK = threading.Lock()
_STRATEGY_CACHE_TTL_SECONDS = 300
_RESOLVED_ITEMS_CACHE_LOCK = threading.Lock()
_RESOLVED_ITEMS_CACHE_VERSION = 0
_CONFIG_UPDATE_LOCK = threading.Lock()
_STRATEGY_REBUILD_STATE_LOCK = threading.Lock()
# Web 端重建状态保存在进程内，用于驱动 SSE 进度展示并阻止重复重建。
_STRATEGY_REBUILD_STATE = {
    'is_running': False,
    'strategy_filter': 'all',
    'target_date': None,
    'started_at': None,
    'completed_at': None,
    'progress': 0,
    'message': '',
    'current_strategy': None,
    'processed': 0,
    'total': 0,
    'matched': 0,
    'last_status': 'idle',
}


class ConfigRefreshError(RuntimeError):
    """配置已回滚，但运行时刷新失败。"""


def _json_default(value):
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, 'item'):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _json_safe(value):
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return _json_default(value)

_STRATEGY_NAME_MAP = {
    'b1': ('B1CaseStrategy', 'B1CaseAnalyzer'),
    'b2': ('B2Strategy',),
    'bowl': ('BowlReboundStrategy',),
}

_B1_PARAM_META = {
    'lookback_days': {'label': '回看窗口(天)', 'min': 30, 'max': 200, 'step': 10, 'desc': '前瞻扫描回看天数'},
    'setup_window_days': {'label': 'Setup观察窗口', 'min': 1, 'max': 10, 'step': 1, 'desc': '观察窗口天数'},
    'anchor_kdj_max': {'label': '锚点J值上限', 'min': 5, 'max': 40, 'step': 5, 'desc': '低位触发日J值上限'},
    'no_break_days': {'label': '护盘天数', 'min': 1, 'max': 10, 'step': 1, 'desc': '连续不破开盘价天数'},
    'breakout_min_pct': {'label': '突破最小涨幅%', 'min': 2, 'max': 10, 'step': 0.5, 'desc': '大阳突破最小涨幅'},
    'breakout_min_streak': {'label': '连续走强天数', 'min': 2, 'max': 10, 'step': 1, 'desc': '突破后最少连续天数'},
    'revisit_kdj_max': {'label': '回踩J值上限', 'min': 5, 'max': 40, 'step': 5, 'desc': 'Setup窗口J值上限'},
    'revisit_band_pct': {'label': '回踩偏离%', 'min': 1, 'max': 10, 'step': 0.5, 'desc': '收盘价距多空线偏离区间'},
}

_PARAM_META = {
    'BowlReboundStrategy': {
        'N': {'label': '成交量倍数', 'min': 1, 'max': 10, 'step': 1, 'desc': '关键K线成交量 >= 前一日 * N'},
        'M': {'label': '回溯天数', 'min': 5, 'max': 60, 'step': 5, 'desc': 'M天内是否存在关键K线'},
        'CAP': {'label': '市值门槛(亿)', 'min': 10, 'max': 1000, 'step': 10, 'desc': '总市值门槛', 'scale': 1e8},
        'J_VAL': {'label': 'J值上限', 'min': 5, 'max': 50, 'step': 5, 'desc': 'KDJ的J值 <= J_VAL'},
        'M1': {'label': 'MA周期1', 'min': 5, 'max': 30, 'step': 1, 'desc': '知行多空线MA周期1'},
        'M2': {'label': 'MA周期2', 'min': 10, 'max': 60, 'step': 1, 'desc': '知行多空线MA周期2'},
        'M3': {'label': 'MA周期3', 'min': 30, 'max': 120, 'step': 1, 'desc': '知行多空线MA周期3'},
        'M4': {'label': 'MA周期4', 'min': 60, 'max': 250, 'step': 1, 'desc': '知行多空线MA周期4'},
        'duokong_pct': {'label': '多空线偏离%', 'min': 0.1, 'max': 10, 'step': 0.1, 'desc': '距离多空线百分比'},
        'short_pct': {'label': '短期趋势偏离%', 'min': 0.1, 'max': 10, 'step': 0.1, 'desc': '距离短期趋势线百分比'},
    },
    'B1CaseStrategy': _B1_PARAM_META,
    'B1CaseAnalyzer': _B1_PARAM_META,
    'B2Strategy': {
        'b1_kdj_threshold': {'label': 'B1极弱J阈值', 'min': 5, 'max': 30, 'step': 1, 'desc': 'B2前置B1的J值上限'},
        'b1_big_up_pct': {'label': '大阳涨幅%', 'min': 3, 'max': 10, 'step': 0.5, 'desc': '攻击波单根大阳最小涨幅'},
        'b2_breakout_pct': {'label': '突破涨幅%', 'min': 2, 'max': 10, 'step': 0.5, 'desc': 'B2突破日最小涨幅'},
        'b2_volume_ratio': {'label': '突破量比', 'min': 1, 'max': 5, 'step': 0.1, 'desc': 'B2突破日成交量相对近10日均量倍率'},
        'b2_must_follow_b1_days': {'label': 'B2距B1天数', 'min': 1, 'max': 5, 'step': 1, 'desc': 'B2突破必须距B1固定交易日差'},
    },
}


def _load_stock_names() -> dict:
    names_file = project_root / "data" / "stock_names.json"
    if names_file.exists():
        with open(names_file, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {}


def _serialize_case_examples(cases: list, source: str) -> list:
    serialized = []
    for case in cases:
        date_value = (
            case.get('breakout_date')
            or case.get('case_date')
            or case.get('b2_date')
            or ''
        )
        serialized.append({
            'id': case.get('id', ''),
            'name': case.get('name', ''),
            'code': case.get('code', ''),
            'date': date_value,
            'description': case.get('description', ''),
            'tags': case.get('tags', []),
            'source': source,
        })
    return serialized


def _get_case_examples_for_strategy(strategy_name: str) -> list:
    try:
        from strategy.pattern_config import (
            B1_PERFECT_CASES,
            B1_STAGE_CASES,
            B2_PERFECT_CASES,
        )
    except Exception:
        return []

    if strategy_name in {'B1CaseStrategy', 'B1CaseAnalyzer'}:
        examples = _serialize_case_examples(B1_PERFECT_CASES, 'b1-perfect')
        examples.extend(_serialize_case_examples(B1_STAGE_CASES, 'b1-stage'))
        return examples

    if strategy_name == 'B2Strategy':
        return _serialize_case_examples(B2_PERFECT_CASES, 'b2-perfect')

    return []


def _normalize_strategy_filter(strategy_filter: str = None) -> str:
    normalized = (strategy_filter or 'all').lower()
    if normalized not in {'all', 'b1', 'b2', 'bowl'}:
        raise ValueError(f'不支持的策略筛选条件: {strategy_filter}')
    return normalized


def _get_expected_strategy_filters() -> list:
    return sorted(_STRATEGY_NAME_MAP.keys())


def _get_rebuild_state() -> dict:
    with _STRATEGY_REBUILD_STATE_LOCK:
        return dict(_STRATEGY_REBUILD_STATE)


def _begin_rebuild_state(strategy_filter: str, target_date: str, total: int) -> tuple[bool, dict]:
    with _STRATEGY_REBUILD_STATE_LOCK:
        if _STRATEGY_REBUILD_STATE['is_running']:
            return False, dict(_STRATEGY_REBUILD_STATE)

        _STRATEGY_REBUILD_STATE.update({
            'is_running': True,
            'strategy_filter': strategy_filter,
            'target_date': target_date,
            'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'completed_at': None,
            'progress': 0,
            'message': '准备开始重建策略缓存。',
            'current_strategy': None,
            'processed': 0,
            'total': total,
            'matched': 0,
            'last_status': 'running',
        })
        return True, dict(_STRATEGY_REBUILD_STATE)


def _update_rebuild_state(**kwargs) -> dict:
    with _STRATEGY_REBUILD_STATE_LOCK:
        _STRATEGY_REBUILD_STATE.update(kwargs)
        return dict(_STRATEGY_REBUILD_STATE)


def _finish_rebuild_state(status: str, message: str, progress: int = 100) -> dict:
    with _STRATEGY_REBUILD_STATE_LOCK:
        _STRATEGY_REBUILD_STATE.update({
            'is_running': False,
            'completed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'progress': progress,
            'message': message,
            'last_status': status,
        })
        return dict(_STRATEGY_REBUILD_STATE)


def get_latest_trade_date() -> str:
    now = datetime.now()
    if now.time() >= dt_time(15, 0):
        target = now.date()
    else:
        target = now.date() - timedelta(days=1)

    while target.weekday() >= 5:
        target -= timedelta(days=1)

    return target.strftime('%Y-%m-%d')


def _extract_signal_items(strategy_name: str, stock_result: dict) -> list:
    def normalize_date(value):
        if value is None:
            return ''
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d')
        text = str(value)
        return text[:10] if len(text) >= 10 else text

    def _build_reason(signal: dict) -> str:
        # 优先使用 reason (B2 string), 否则用 reasons (Bowl/B1 list)
        raw = signal.get('reason', '')
        if not raw:
            reasons_list = signal.get('reasons')
            if isinstance(reasons_list, list) and reasons_list:
                raw = '; '.join(str(r) for r in reasons_list)

        # 追加均线/趋势位置描述
        parts = [raw] if raw else []

        j_val = signal.get('j_value') or signal.get('J') or signal.get('j')
        if j_val is not None:
            try:
                parts.append(f'J={float(j_val):.1f}')
            except (ValueError, TypeError):
                pass

        close = signal.get('close')
        short_trend = signal.get('short_term_trend')
        bull_bear = signal.get('bull_bear_line')

        if close is not None and short_trend is not None:
            try:
                pos = '白线上方' if float(close) >= float(short_trend) else '白线下方'
                parts.append(pos)
            except (ValueError, TypeError):
                pass

        if close is not None and bull_bear is not None:
            try:
                pos = '黄线上方' if float(close) >= float(bull_bear) else '黄线下方'
                parts.append(pos)
            except (ValueError, TypeError):
                pass

        if short_trend is not None and bull_bear is not None:
            try:
                if float(short_trend) > float(bull_bear):
                    parts.append('均线多头')
                else:
                    parts.append('均线空头')
            except (ValueError, TypeError):
                pass

        return ' | '.join(parts) if parts else ''

    rows = []
    for signal in stock_result.get('signals', []) or [{}]:
        j_val = signal.get('j_value') or signal.get('J') or signal.get('j')
        rows.append({
            'code': stock_result.get('code', ''),
            'name': stock_result.get('name', '未知'),
            'strategy_name': strategy_name,
            'category': signal.get('category', strategy_name),
            'date': normalize_date(signal.get('date', '')),
            'trigger_price': signal.get('trigger_price', signal.get('close')),
            'close': signal.get('close'),
            'reason': _build_reason(signal),
            'j_value': j_val,
            'similarity_score': signal.get('similarity_score'),
            'signal': _json_safe(signal),
        })
    return rows


def _flatten_grouped_results(grouped_results: dict) -> list:
    flat_results = []
    for strategy_filter, group in grouped_results.items():
        for stock_result in group.get('results', []):
            # 快照同时保留分组结构和扁平结构：前者适合统计，后者适合前端直接渲染表格。
            rows = _extract_signal_items(group.get('strategy_name', strategy_filter), stock_result)
            for row in rows:
                row['strategy_filter'] = strategy_filter
            flat_results.extend(rows)

    flat_results.sort(
        key=lambda item: (
            item.get('date', ''),
            str(item.get('code', '')),
            str(item.get('strategy_name', '')),
        ),
        reverse=True,
    )
    return flat_results


def _analyze_stock_for_strategy(strategy, code: str, stock_names: dict):
    name = stock_names.get(code, '未知')
    invalid_keywords = ('退', '未知', '退市', '已退')
    if any(keyword in name for keyword in invalid_keywords):
        return None
    if name.startswith('ST') or name.startswith('*ST'):
        return None

    df = csv_manager.read_stock(code)
    if df.empty or len(df) < 60:
        return None

    try:
        if hasattr(strategy, 'calculate_indicators') and hasattr(strategy, 'select_stocks'):
            df_with_indicators = strategy.calculate_indicators(df.copy())
            signal_list = strategy.select_stocks(df_with_indicators, name)
            if signal_list:
                return {'code': code, 'name': name, 'signals': signal_list}
            return None

        result = strategy.analyze_stock(code, name, df)
        if result and result.get('signals'):
            return {
                'code': result['code'],
                'name': result.get('name', name),
                'signals': result['signals'],
            }
    except Exception:
        return None

    return None


def _scan_strategy(
    strategy_filter: str,
    strategy_name: str,
    strategy,
    stock_names: dict,
    all_stocks: list,
    stock_processed_callback=None,
) -> dict:
    signals = []
    worker_count = max(1, min(8, len(all_stocks)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(_analyze_stock_for_strategy, strategy, code, stock_names) for code in all_stocks]
        processed = 0
        for future in concurrent.futures.as_completed(futures):
            processed += 1
            try:
                result = future.result()
            except Exception:
                result = None
            if result:
                signals.append(result)
            if stock_processed_callback:
                stock_processed_callback(
                    strategy_filter,
                    strategy_name,
                    result,
                    processed,
                    len(all_stocks),
                    len(signals),
                )

    return {
        'strategy_filter': strategy_filter,
        'strategy_name': strategy_name,
        'results': signals,
        'total': len(signals),
        'scanned': len(all_stocks),
        'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ═══════════════════════════════════════════════════════════════════════
# 第一阶段重构: 按股票扫描一次，复用多个策略
# ═══════════════════════════════════════════════════════════════════════

def _resolve_selected_web_strategies(resolved_strategies: dict, strategy_filter: str) -> list:
    """解析目标策略集合，返回 [(filter_key, strategy_name, strategy_obj), ...]"""
    if strategy_filter == 'all':
        selected_filters = list(resolved_strategies.keys())
    else:
        if strategy_filter not in resolved_strategies:
            raise ValueError(f'未注册可用于 Web 的策略: {strategy_filter}')
        selected_filters = [strategy_filter]

    items = []
    for sf in selected_filters:
        entry = resolved_strategies[sf]
        items.append((sf, entry['strategy_name'], entry['strategy']))
    return items


def _init_group_buffers(
    selected_items: list,
    existing_snapshot: dict | None,
    strategy_filter: str,
    effective_date: str,
) -> dict:
    """初始化分组缓冲区，单策略重建时复用其他策略已有分组。"""
    if strategy_filter == 'all' or not existing_snapshot or existing_snapshot.get('trade_date') != effective_date:
        buffers = {}
    else:
        buffers = dict(existing_snapshot.get('groups', {}))

    for sf, strategy_name, _ in selected_items:
        buffers[sf] = {
            'strategy_filter': sf,
            'strategy_name': strategy_name,
            'results': [],
            'total': 0,
            'scanned': 0,
            'time': None,
        }
    return buffers


def _prepare_stock_context(code: str, stock_names: dict):
    """单只股票读取与预校验。返回 (status, name, df, reason)。"""
    name = stock_names.get(code, '未知')
    invalid_keywords = ('退', '未知', '退市', '已退')
    if any(keyword in name for keyword in invalid_keywords):
        return 'invalid', name, None, f'{name} 包含无效关键词'
    if name.startswith('ST') or name.startswith('*ST'):
        return 'invalid', name, None, f'{name} 为ST股票'

    df = csv_manager.read_stock(code)
    if df.empty or len(df) < 60:
        return 'skip', name, None, '数据不足'

    return 'ok', name, df, None


def _analyze_stock_multi_strategy(code: str, name: str, df, strategy_items: list) -> dict:
    """单只股票复用多策略分析。返回 hits dict，key 为 strategy_filter。"""
    hits = {}
    for sf, strategy_name, strategy in strategy_items:
        try:
            if hasattr(strategy, 'calculate_indicators') and hasattr(strategy, 'select_stocks'):
                df_with_indicators = strategy.calculate_indicators(df.copy())
                signal_list = strategy.select_stocks(df_with_indicators, name)
                if signal_list:
                    hits[sf] = {
                        'strategy_name': strategy_name,
                        'stock_result': {'code': code, 'name': name, 'signals': signal_list},
                    }
                continue

            result = strategy.analyze_stock(code, name, df)
            if result and result.get('signals'):
                hits[sf] = {
                    'strategy_name': strategy_name,
                    'stock_result': {
                        'code': result['code'],
                        'name': result.get('name', name),
                        'signals': result['signals'],
                    },
                }
        except Exception:
            continue
    return hits


def _merge_stock_hits_into_groups(group_buffers: dict, stock_analysis: dict) -> tuple:
    """合并单股结果到分组缓冲区。返回 (matched_row_count, emitted_rows)。"""
    emitted_rows = []
    for sf, hit in stock_analysis.get('hits', {}).items():
        if sf not in group_buffers:
            continue
        stock_result = hit['stock_result']
        strategy_name = hit['strategy_name']
        group_buffers[sf]['results'].append(stock_result)
        rows = _extract_signal_items(strategy_name, stock_result)
        for row in rows:
            row['strategy_filter'] = sf
        emitted_rows.extend(rows)
    return len(emitted_rows), emitted_rows


def _finalize_grouped_results(group_buffers: dict, scanned_total: int) -> dict:
    """从缓冲区生成最终 groups 结构。"""
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for sf, buf in group_buffers.items():
        buf['total'] = len(buf['results'])
        buf['scanned'] = scanned_total
        if buf['time'] is None:
            buf['time'] = now_str
    return group_buffers


def _process_one_stock(code: str, stock_names: dict, strategy_items: list) -> dict:
    """线程池任务：读取单只股票并在内存中复用多策略分析。"""
    status, name, df, reason = _prepare_stock_context(code, stock_names)
    if status != 'ok':
        return {'code': code, 'name': name, 'status': status, 'reason': reason, 'hits': {}}
    hits = _analyze_stock_multi_strategy(code, name, df, strategy_items)
    return {'code': code, 'name': name, 'status': 'ok', 'reason': None, 'hits': hits}


# ═══════════════════════════════════════════════════════════════════════
# Pipeline 模式：数据更新阶段内联策略扫描（Phase 2）
# ═══════════════════════════════════════════════════════════════════════

def _validate_stock_inline(code: str, name: str, df) -> tuple:
    """校验股票是否可用于策略扫描（跳过 csv_manager.read_stock）。
    返回 (status, name, df_or_None, reason_or_None)。"""
    invalid_keywords = ('退', '未知', '退市', '已退')
    if any(keyword in name for keyword in invalid_keywords):
        return 'invalid', name, None, f'{name} 包含无效关键词'
    if name.startswith('ST') or name.startswith('*ST'):
        return 'invalid', name, None, f'{name} 为ST股票'
    if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 60:
        return 'skip', name, None, '数据不足'
    return 'ok', name, df, None


def scan_one_stock_with_df(code: str, df, stock_names: dict, selected_items: list) -> list:
    """用内存中的 df 对单只股票执行多策略扫描。
    返回 flat list of signal row dicts（与 build_strategy_result_snapshot 中 emitted_rows 格式一致）。
    若无命中返回空列表。"""
    name = stock_names.get(code, '未知')
    status, _, validated_df, _ = _validate_stock_inline(code, name, df)
    if status != 'ok':
        return []

    hits = _analyze_stock_multi_strategy(code, name, validated_df, selected_items)
    if not hits:
        return []

    emitted_rows = []
    for sf, hit in hits.items():
        stock_result = hit['stock_result']
        strategy_name = hit['strategy_name']
        rows = _extract_signal_items(strategy_name, stock_result)
        for row in rows:
            row['strategy_filter'] = sf
        emitted_rows.extend(rows)
    return emitted_rows


# 缓存已解析的策略项，避免 pipeline 每次重复加载
_RESOLVED_ITEMS_CACHE = {'items': None, 'names': None, 'ts': 0}
_RESOLVED_ITEMS_TTL = 300  # 5 分钟


def _clear_resolved_items_cache() -> None:
    with _RESOLVED_ITEMS_CACHE_LOCK:
        global _RESOLVED_ITEMS_CACHE_VERSION
        _RESOLVED_ITEMS_CACHE_VERSION += 1
        _RESOLVED_ITEMS_CACHE.update({'items': None, 'names': None, 'ts': 0})


def get_resolved_strategy_items() -> tuple:
    """获取已初始化的 (stock_names, selected_items)，带 5 分钟内部缓存。
    供 pipeline 模式在数据更新阶段调用。"""
    while True:
        now_ts = time.time()
        with _RESOLVED_ITEMS_CACHE_LOCK:
            cache_version = _RESOLVED_ITEMS_CACHE_VERSION
            if (
                _RESOLVED_ITEMS_CACHE['items'] is not None
                and (now_ts - _RESOLVED_ITEMS_CACHE['ts']) < _RESOLVED_ITEMS_TTL
            ):
                return _RESOLVED_ITEMS_CACHE['names'], _RESOLVED_ITEMS_CACHE['items']

        registry = get_registry('config/strategy_params.yaml')
        registry.auto_register_from_directory('strategy')
        stock_names = _load_stock_names()
        resolved_strategies = _resolve_web_strategies(registry)
        selected_items = _resolve_selected_web_strategies(resolved_strategies, 'all')

        with _RESOLVED_ITEMS_CACHE_LOCK:
            if cache_version != _RESOLVED_ITEMS_CACHE_VERSION:
                continue
            _RESOLVED_ITEMS_CACHE['items'] = selected_items
            _RESOLVED_ITEMS_CACHE['names'] = stock_names
            _RESOLVED_ITEMS_CACHE['ts'] = now_ts
            return stock_names, selected_items


def _resolve_web_strategies(registry) -> dict:
    resolved = {}
    for strategy_filter, candidates in _STRATEGY_NAME_MAP.items():
        resolved_name = next((name for name in candidates if name in registry.strategies), None)
        if resolved_name:
            resolved[strategy_filter] = {
                'strategy_name': resolved_name,
                'strategy': registry.strategies[resolved_name],
            }
    return resolved


def _build_empty_payload(strategy_filter: str, requested_date: str, status: str, message: str, available_trade_date: str = None) -> dict:
    return {
        'requested_date': requested_date,
        'trade_date': available_trade_date,
        'strategy_filter': strategy_filter,
        'results': [],
        'groups': {},
        'available_groups': [],
        'group_totals': {},
        'total': 0,
        'unique_total': 0,
        'generated_at': None,
        'status': status,
        'source': 'empty',
        'message': message,
        'cache_file': str(WEB_STRATEGY_RESULTS_FILE),
    }


def _read_strategy_snapshot() -> dict | None:
    if not WEB_STRATEGY_RESULTS_FILE.exists():
        return None

    try:
        with open(WEB_STRATEGY_RESULTS_FILE, 'r', encoding='utf-8') as file:
            snapshot = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(snapshot, dict):
        return None
    if snapshot.get('schema_version') != WEB_STRATEGY_SCHEMA_VERSION:
        return None
    if not isinstance(snapshot.get('groups'), dict):
        return None
    if not isinstance(snapshot.get('results'), list):
        return None
    return snapshot


def _build_api_payload_from_snapshot(snapshot: dict, strategy_filter: str, requested_date: str, status: str, message: str) -> dict:
    groups = snapshot.get('groups', {})
    group_totals = {
        group_name: group.get('total', 0)
        for group_name, group in groups.items()
    }
    if strategy_filter == 'all':
        filtered_groups = groups
        filtered_results = snapshot.get('results', [])
    else:
        filtered_groups = {strategy_filter: groups[strategy_filter]} if strategy_filter in groups else {}
        filtered_results = [
            row for row in snapshot.get('results', [])
            if row.get('strategy_filter') == strategy_filter
        ]
    unique_total = len({str(item.get('code', '')) for item in filtered_results if item.get('code')})

    return {
        'requested_date': requested_date,
        'trade_date': snapshot.get('trade_date'),
        'strategy_filter': strategy_filter,
        'results': filtered_results,
        'groups': filtered_groups,
        'available_groups': sorted(groups.keys()),
        'group_totals': group_totals,
        'total': len(filtered_results),
        'unique_total': unique_total,
        'generated_at': snapshot.get('generated_at'),
        'status': status,
        'source': 'file',
        'message': message,
        'cache_file': str(WEB_STRATEGY_RESULTS_FILE),
    }


def build_strategy_result_snapshot(
    target_date: str = None,
    strategy_filter: str = 'all',
    progress_callback=None,
    run_id: str = None,
) -> dict:
    effective_date = target_date or get_latest_trade_date()
    strategy_filter = _normalize_strategy_filter(strategy_filter)

    registry = get_registry('config/strategy_params.yaml')
    registry.auto_register_from_directory('strategy')
    stock_names = _load_stock_names()
    all_stocks = csv_manager.list_all_stocks()
    resolved_strategies = _resolve_web_strategies(registry)

    # ── 第一阶段重构: 按股票扫描一次，复用多个策略 ──
    selected_items = _resolve_selected_web_strategies(resolved_strategies, strategy_filter)
    existing_snapshot = _read_strategy_snapshot()
    group_buffers = _init_group_buffers(selected_items, existing_snapshot, strategy_filter, effective_date)

    total_stocks = len(all_stocks)
    overall_processed = 0
    overall_matched = 0

    # 为每个策略发送 strategy_start 事件
    for index, (sf, strategy_name, _) in enumerate(selected_items, start=1):
        if progress_callback:
            progress_callback(
                'strategy_start',
                {
                    'status': 'running',
                    'progress': 0,
                    'message': f'开始扫描 {strategy_name}。',
                    'strategy_filter': sf,
                    'strategy_name': strategy_name,
                    'strategy_index': index,
                    'strategy_count': len(selected_items),
                    'processed': 0,
                    'total': total_stocks,
                    'matched': 0,
                },
            )

    # 并发遍历股票, 每只股票只 read_stock 一次
    worker_count = max(1, min(8, total_stocks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_process_one_stock, code, stock_names, selected_items): code
            for code in all_stocks
        }

        for future in concurrent.futures.as_completed(futures):
            overall_processed += 1
            try:
                stock_analysis = future.result()
            except Exception:
                stock_analysis = {'code': futures[future], 'name': '', 'status': 'error', 'hits': {}}

            added_rows, emitted_rows = _merge_stock_hits_into_groups(group_buffers, stock_analysis)
            overall_matched += added_rows

            progress = min(99, int((overall_processed / total_stocks) * 100))

            if emitted_rows and progress_callback:
                # 找出本次命中涉及的策略名（用于消息显示）
                hit_strategies = list({r.get('strategy_name', '') for r in emitted_rows})
                progress_callback(
                    'signal',
                    {
                        'status': 'running',
                        'progress': progress,
                        'message': f'{", ".join(hit_strategies)} 新增 {len(emitted_rows)} 条命中。',
                        'strategy_filter': strategy_filter,
                        'strategy_name': hit_strategies[0] if hit_strategies else '',
                        'items': emitted_rows,
                        'processed': overall_processed,
                        'total': total_stocks,
                        'matched': overall_matched,
                        'current_code': stock_analysis.get('code', ''),
                        'current_name': stock_analysis.get('name', ''),
                    },
                )

            should_emit_progress = (
                emitted_rows
                or overall_processed == total_stocks
                or overall_processed == 1
                or overall_processed % 10 == 0
            )
            if progress_callback and should_emit_progress:
                progress_callback(
                    'progress',
                    {
                        'status': 'running',
                        'progress': progress,
                        'message': f'扫描中：{overall_processed}/{total_stocks}，命中 {overall_matched} 条。',
                        'strategy_filter': strategy_filter,
                        'processed': overall_processed,
                        'total': total_stocks,
                        'matched': overall_matched,
                        'current_code': stock_analysis.get('code', ''),
                        'current_name': stock_analysis.get('name', ''),
                    },
                )

    groups = _finalize_grouped_results(group_buffers, total_stocks)

    # 为每个策略发送 strategy_complete 事件
    for sf, strategy_name, _ in selected_items:
        if progress_callback:
            progress_callback(
                'strategy_complete',
                {
                    'status': 'running',
                    'progress': 99,
                    'message': f'{strategy_name} 扫描完成，共命中 {groups[sf]["total"]} 只股票。',
                    'strategy_filter': sf,
                    'strategy_name': strategy_name,
                    'processed': overall_processed,
                    'total': total_stocks,
                    'matched': overall_matched,
                    'group_total': groups[sf]['total'],
                },
            )

    flat_results = _flatten_grouped_results(groups)
    snapshot = {
        'schema_version': WEB_STRATEGY_SCHEMA_VERSION,
        'trade_date': effective_date,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'groups': groups,
        'available_groups': sorted(groups.keys()),
        'results': flat_results,
        'total': sum(group.get('total', 0) for group in groups.values()),
        'unique_total': len({
            str(item.get('code', ''))
            for item in flat_results
            if item.get('code')
        }),
        '_run_id': run_id,
    }

    WEB_STRATEGY_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = WEB_STRATEGY_RESULTS_FILE.with_suffix('.tmp')
    with open(temp_file, 'w', encoding='utf-8') as file:
        json.dump(snapshot, file, ensure_ascii=False, indent=2, default=_json_default)
    temp_file.replace(WEB_STRATEGY_RESULTS_FILE)

    with _STRATEGY_CACHE_LOCK:
        _STRATEGY_CACHE.clear()

    # ── SQLite 双写：将结果写入 SQLite ──
    run_id = snapshot.get('_run_id')
    if run_id:
        try:
            _write_results_to_sqlite(run_id, effective_date, strategy_filter, groups, snapshot)
        except Exception:
            pass  # SQLite 写入失败不阻塞主流程

    return snapshot


def _write_results_to_sqlite(run_id: str, trade_date: str, strategy_filter: str, groups: dict, snapshot: dict):
    """将策略结果批量写入 SQLite"""
    batch = []
    for sf, group in groups.items():
        strategy_name = group.get('strategy_name', sf)
        for stock_result in group.get('results', []):
            rows = _extract_signal_items(strategy_name, stock_result)
            for row in rows:
                batch.append({
                    'run_id': run_id,
                    'trade_date': trade_date,
                    'strategy_filter': sf,
                    'strategy_name': strategy_name,
                    'code': row.get('code', ''),
                    'name': row.get('name', ''),
                    'category': row.get('category', ''),
                    'signal_date': row.get('date', ''),
                    'trigger_price': row.get('trigger_price'),
                    'close': row.get('close'),
                    'j_value': row.get('j_value'),
                    'similarity_score': row.get('similarity_score'),
                    'reason': row.get('reason', ''),
                    'signal': row.get('signal', {}),
                })

    if batch:
        repo.insert_results_batch(batch)

    # 保存快照摘要
    group_totals = {sf: g.get('total', 0) for sf, g in groups.items()}
    repo.save_snapshot(
        run_id=run_id,
        trade_date=trade_date,
        strategy_filter=strategy_filter,
        total_results=snapshot.get('total', 0),
        available_groups=sorted(groups.keys()),
        group_totals=group_totals,
    )


def get_strategy_cache_status(strategy_filter: str = 'all', target_date: str = None) -> dict:
    strategy_filter = _normalize_strategy_filter(strategy_filter)
    effective_date = target_date or get_latest_trade_date()
    snapshot = _read_strategy_snapshot()
    expected_groups = _get_expected_strategy_filters()
    rebuild_state = _get_rebuild_state()
    repo_strategy_filter = None if strategy_filter == 'all' else strategy_filter

    # 从 SQLite 获取最新运行记录
    last_run = None
    running_run = None
    sqlite_summary = None
    try:
        runs = repo.list_runs(date=effective_date, strategy_filter=repo_strategy_filter, per_page=1)
        if runs['items']:
            last_run = runs['items'][0]
        running_runs = repo.list_runs(
            date=effective_date,
            status='running',
            strategy_filter=repo_strategy_filter,
            per_page=1,
        )
        if running_runs['items']:
            running_run = running_runs['items'][0]
        sqlite_summary = repo.get_result_summary_for_date(effective_date)
    except Exception:
        pass

    if not rebuild_state.get('is_running') and running_run:
        latest_event = None
        try:
            events = repo.get_run_events(running_run['run_id'], limit=50)
            if events:
                latest_event = events[-1]
        except Exception:
            latest_event = None

        rebuild_state = {
            'is_running': True,
            'strategy_filter': running_run.get('strategy_filter'),
            'target_date': running_run.get('trade_date'),
            'started_at': running_run.get('started_at'),
            'completed_at': running_run.get('completed_at'),
            'progress': latest_event.get('progress', 0) if latest_event else 0,
            'message': (
                (latest_event or {}).get('message')
                or running_run.get('message')
                or '策略缓存正在重建。'
            ),
            'current_strategy': (latest_event or {}).get('strategy_name'),
            'processed': running_run.get('processed_count', 0),
            'total': running_run.get('total_count', 0),
            'matched': running_run.get('matched_count', 0),
            'last_status': running_run.get('status', 'running'),
        }

    payload = {
        'requested_date': effective_date,
        'strategy_filter': strategy_filter,
        'cache_file': str(WEB_STRATEGY_RESULTS_FILE),
        'exists': snapshot is not None,
        'trade_date': None,
        'generated_at': None,
        'total': 0,
        'unique_total': 0,
        'available_groups': [],
        'missing_groups': expected_groups,
        'group_totals': {},
        'status': 'missing',
        'message': '策略缓存文件不存在，请先手动重建。',
        'is_latest': False,
        'selected_strategy_available': strategy_filter == 'all',
        'rebuild': rebuild_state,
        'last_run_id': last_run['run_id'] if last_run else None,
        'latest_run_status': last_run['status'] if last_run else None,
        'source': 'empty',
        'sqlite_summary': sqlite_summary,
    }

    if snapshot is None:
        if rebuild_state.get('is_running'):
            payload['status'] = 'running'
            payload['message'] = rebuild_state.get('message') or '策略缓存正在重建。'
        return payload

    groups = snapshot.get('groups', {})
    available_groups = sorted(groups.keys())
    missing_groups = sorted(set(expected_groups) - set(available_groups))
    snapshot_date = snapshot.get('trade_date')
    if strategy_filter == 'all':
        selected_results = snapshot.get('results', [])
    else:
        selected_results = [
            row for row in snapshot.get('results', [])
            if row.get('strategy_filter') == strategy_filter
        ]
    selected_unique_total = len({
        str(item.get('code', ''))
        for item in selected_results
        if item.get('code')
    })

    payload.update({
        'trade_date': snapshot_date,
        'generated_at': snapshot.get('generated_at'),
        'total': len(selected_results),
        'unique_total': selected_unique_total,
        'available_groups': available_groups,
        'missing_groups': missing_groups,
        'group_totals': {
            group_name: group.get('total', 0)
            for group_name, group in groups.items()
        },
        'is_latest': snapshot_date == effective_date,
        'selected_strategy_available': strategy_filter == 'all' or strategy_filter in available_groups,
    })

    if snapshot_date != effective_date:
        payload['status'] = 'stale'
        payload['message'] = f'当前缓存日期为 {snapshot_date}，目标日期 {effective_date} 尚未生成。'
    elif strategy_filter != 'all' and strategy_filter not in available_groups:
        payload['status'] = 'not_found'
        payload['message'] = f'当前缓存未包含 {strategy_filter} 策略结果，请单独重建该策略。'
    elif missing_groups:
        payload['status'] = 'partial'
        payload['message'] = f'当日缓存可用，但仍缺少策略分组: {", ".join(missing_groups)}。'
    else:
        payload['status'] = 'ready'
        payload['message'] = '当日策略缓存可直接复用。'

    if rebuild_state.get('is_running'):
        payload['status'] = 'running'
        payload['message'] = rebuild_state.get('message') or '策略缓存正在重建。'

    return payload


async def stream_strategy_cache_rebuild(strategy_filter: str = 'all', target_date: str = None):
    strategy_filter = _normalize_strategy_filter(strategy_filter)
    effective_date = target_date or get_latest_trade_date()

    registry = get_registry('config/strategy_params.yaml')
    registry.auto_register_from_directory('strategy')
    resolved_strategies = _resolve_web_strategies(registry)

    if strategy_filter == 'all':
        selected_filters = list(resolved_strategies.keys())
    elif strategy_filter in resolved_strategies:
        selected_filters = [strategy_filter]
    else:
        yield {
            'event': 'error',
            'data': {
                'status': 'error',
                'progress': 100,
                'message': f'未注册可用于 Web 的策略: {strategy_filter}',
            },
        }
        return

    total_tasks = max(1, len(csv_manager.list_all_stocks()))
    started, state = _begin_rebuild_state(strategy_filter, effective_date, total_tasks)
    if not started:
        yield {
            'event': 'error',
            'data': {
                'status': 'busy',
                'progress': state.get('progress', 0),
                'message': (
                    '已有策略缓存重建任务在执行中：'
                    f"{state.get('strategy_filter')} / {state.get('target_date')}"
                ),
                'rebuild': state,
            },
        }
        return

    # 生成 run_id 并写入 SQLite
    run_id = repo.generate_run_id()
    try:
        repo.create_run(run_id, 'rebuild_only', effective_date, strategy_filter, total_tasks)
    except Exception:
        pass

    event_queue: queue.Queue = queue.Queue()
    done_event = threading.Event()

    def emit(event: str, data: dict):
        data['run_id'] = run_id

        if event in {'start', 'strategy_start', 'progress', 'signal', 'strategy_complete'}:
            _update_rebuild_state(
                progress=data.get('progress', _get_rebuild_state().get('progress', 0)),
                message=data.get('message', _get_rebuild_state().get('message', '')),
                current_strategy=data.get('strategy_name', _get_rebuild_state().get('current_strategy')),
                processed=data.get('processed', _get_rebuild_state().get('processed', 0)),
                total=data.get('total', _get_rebuild_state().get('total', 0)),
                matched=data.get('matched', _get_rebuild_state().get('matched', 0)),
            )
        elif event == 'complete':
            _finish_rebuild_state('done', data.get('message', '策略缓存重建完成。'), 100)
        elif event == 'error':
            _finish_rebuild_state('error', data.get('message', '策略缓存重建失败。'), 100)

        # 写入 SQLite 事件表（仅关键事件，不写高频 progress 事件）
        if event in {'start', 'strategy_start', 'signal', 'strategy_complete', 'complete', 'error'}:
            try:
                repo.insert_event(
                    run_id=run_id,
                    event_type=event,
                    strategy_filter=data.get('strategy_filter'),
                    strategy_name=data.get('strategy_name'),
                    progress=data.get('progress'),
                    message=data.get('message'),
                    payload=data if event == 'signal' else None,
                )
            except Exception:
                pass

        event_queue.put({'event': event, 'data': data})

    def worker():
        try:
            emit(
                'start',
                {
                    'status': 'start',
                    'progress': 1,
                    'message': f'开始重建 {strategy_filter} 策略缓存，目标日期 {effective_date}。',
                    'strategy_filter': strategy_filter,
                    'target_date': effective_date,
                    'processed': 0,
                    'total': total_tasks,
                    'matched': 0,
                },
            )
            snapshot = build_strategy_result_snapshot(
                target_date=effective_date,
                strategy_filter=strategy_filter,
                progress_callback=emit,
                run_id=run_id,
            )
            emit(
                'complete',
                {
                    'status': 'done',
                    'progress': 100,
                    'message': '策略缓存重建完成。',
                    'strategy_filter': strategy_filter,
                    'target_date': effective_date,
                    'trade_date': snapshot.get('trade_date'),
                    'generated_at': snapshot.get('generated_at'),
                    'available_groups': sorted(snapshot.get('groups', {}).keys()),
                    'total_results': snapshot.get('total', 0),
                    'cache_file': str(WEB_STRATEGY_RESULTS_FILE),
                },
            )
            try:
                repo.finish_run(run_id, 'done', '策略缓存重建完成。',
                                matched_count=snapshot.get('total', 0),
                                processed_count=total_tasks)
            except Exception:
                pass
        except Exception as exc:
            emit(
                'error',
                {
                    'status': 'error',
                    'progress': 100,
                    'message': f'策略缓存重建失败: {exc}',
                    'strategy_filter': strategy_filter,
                    'target_date': effective_date,
                },
            )
            try:
                repo.finish_run(run_id, 'error', str(exc))
            except Exception:
                pass
        finally:
            done_event.set()

    threading.Thread(target=worker, daemon=True).start()

    while not done_event.is_set() or not event_queue.empty():
        try:
            yield event_queue.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.1)


def run_strategy(strategy_filter: str = 'all', target_date: str = None) -> dict:
    strategy_filter = _normalize_strategy_filter(strategy_filter)
    effective_date = target_date or get_latest_trade_date()
    cache_key = (strategy_filter, effective_date)

    with _STRATEGY_CACHE_LOCK:
        cached = _STRATEGY_CACHE.get(cache_key)
        if cached and (time.time() - cached['ts']) < _STRATEGY_CACHE_TTL_SECONDS:
            return cached['value']

    snapshot = _read_strategy_snapshot()
    if snapshot is None:
        payload = _build_empty_payload(
            strategy_filter,
            effective_date,
            'missing',
            '策略结果缓存文件不存在，请先生成 web_strategy_results.json。',
        )
    else:
        # Web 接口默认走“快照优先”，不会在读接口里实时重跑全市场扫描。
        snapshot_date = snapshot.get('trade_date')
        available_groups = set(snapshot.get('groups', {}).keys())
        missing_groups = sorted(set(_get_expected_strategy_filters()) - available_groups)
        if target_date and snapshot_date != effective_date:
            payload = _build_empty_payload(
                strategy_filter,
                effective_date,
                'not_found',
                f'未找到 {effective_date} 的策略缓存结果。',
                snapshot_date,
            )
        elif strategy_filter != 'all' and strategy_filter not in available_groups:
            payload = _build_empty_payload(
                strategy_filter,
                effective_date,
                'not_found',
                f'缓存中未包含 {strategy_filter} 策略结果，请先重建该策略。',
                snapshot_date,
            )
        elif snapshot_date == effective_date:
            payload = _build_api_payload_from_snapshot(
                snapshot,
                strategy_filter,
                effective_date,
                'partial' if strategy_filter == 'all' and missing_groups else 'ready',
                (
                    f'已从离线缓存读取策略结果，但仍缺少策略分组: {", ".join(missing_groups)}。'
                    if strategy_filter == 'all' and missing_groups
                    else '已从离线缓存读取策略结果。'
                ),
            )
        else:
            payload = _build_api_payload_from_snapshot(
                snapshot,
                strategy_filter,
                effective_date,
                'stale',
                f'当前缓存日期为 {snapshot_date}，尚未生成 {effective_date} 的策略结果，已返回最近一次缓存。',
            )

    with _STRATEGY_CACHE_LOCK:
        _STRATEGY_CACHE[cache_key] = {'ts': time.time(), 'value': payload}

    return payload


def _clear_strategy_cache() -> None:
    with _STRATEGY_CACHE_LOCK:
        _STRATEGY_CACHE.clear()


def _invalidate_persisted_strategy_results() -> None:
    try:
        WEB_STRATEGY_RESULTS_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _validate_strategy_config_update(strategy_name: str, new_params: dict) -> dict:
    registry = get_registry('config/strategy_params.yaml')
    registry.auto_register_from_directory('strategy')
    strategy = registry.get_strategy(strategy_name)
    if strategy is None:
        raise ValueError(f"未知策略: {strategy_name}")
    if not new_params:
        raise ValueError("参数不能为空")

    validated_params = {}
    current_params = strategy.params
    param_meta = _PARAM_META.get(strategy_name, {})
    for key, value in new_params.items():
        if key not in current_params:
            raise ValueError(f"未知参数: {key}")

        expected_value = current_params[key]
        if isinstance(expected_value, bool):
            if not isinstance(value, bool):
                raise ValueError(f"参数 {key} 必须为布尔值")
        elif isinstance(expected_value, int) and not isinstance(expected_value, bool):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"参数 {key} 必须为整数")
        elif isinstance(expected_value, float):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"参数 {key} 必须为数字")
            value = float(value)
        elif isinstance(expected_value, str):
            if not isinstance(value, str):
                raise ValueError(f"参数 {key} 必须为字符串")

        meta = param_meta.get(key, {})
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            min_value = meta.get('min')
            max_value = meta.get('max')
            if min_value is not None and value < min_value:
                raise ValueError(f"参数 {key} 不能小于 {min_value}")
            if max_value is not None and value > max_value:
                raise ValueError(f"参数 {key} 不能大于 {max_value}")

        validated_params[key] = value

    return validated_params


def get_strategies_config() -> dict:
    registry = get_registry('config/strategy_params.yaml')
    registry.auto_register_from_directory('strategy')
    raw_config, revision, updated_at = get_config_with_revision()
    strategies = registry.get_registered_strategies()
    configs = []
    for name, strategy in strategies.items():
        configs.append({
            'strategy_name': name,
            'params': raw_config.get(name, strategy.params),
            'param_meta': _PARAM_META.get(name, {}),
            'case_examples': _get_case_examples_for_strategy(name),
        })
    return {
        'revision': revision,
        'updated_at': updated_at,
        'configs': configs,
    }


def update_strategy_config(strategy_name: str, new_params: dict, expected_revision: str) -> tuple[bool, str]:
    validated_params = _validate_strategy_config_update(strategy_name, new_params)
    with _CONFIG_UPDATE_LOCK:
        original_config, _, _ = get_config_with_revision()
        original_config = copy.deepcopy(original_config)
        success, revision = update_config_with_revision(strategy_name, validated_params, expected_revision)
        if not success:
            return False, revision

        registry = get_registry('config/strategy_params.yaml')
        try:
            registry.reload_params()
            _invalidate_persisted_strategy_results()
            _clear_resolved_items_cache()
            _clear_strategy_cache()
            return True, revision
        except Exception as exc:
            try:
                save_config(original_config)
                registry.reload_params()
                _clear_resolved_items_cache()
                _clear_strategy_cache()
            except Exception as rollback_exc:
                raise ConfigRefreshError("配置刷新失败，且回滚失败") from rollback_exc
            raise ConfigRefreshError("配置刷新失败，已回滚") from exc
