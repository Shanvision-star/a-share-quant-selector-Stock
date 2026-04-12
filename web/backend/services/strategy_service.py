"""策略执行服务 - 调用 strategy_registry"""
import asyncio
import concurrent.futures
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

csv_manager = CSVManager(str(project_root / "data"))
WEB_STRATEGY_RESULTS_FILE = project_root / "data" / "web_strategy_results.json"
WEB_STRATEGY_SCHEMA_VERSION = 1

_STRATEGY_CACHE = {}
_STRATEGY_CACHE_LOCK = threading.Lock()
_STRATEGY_CACHE_TTL_SECONDS = 300
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

_STRATEGY_NAME_MAP = {
    'b1': ('B1CaseStrategy', 'B1CaseAnalyzer'),
    'b2': ('B2CaseAnalyzer',),
    'bowl': ('BowlReboundStrategy',),
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
    'B1CaseStrategy': {
        'lookback_days': {'label': '回看窗口(天)', 'min': 30, 'max': 200, 'step': 10, 'desc': '前瞻扫描回看天数'},
        'setup_window_days': {'label': 'Setup观察窗口', 'min': 1, 'max': 10, 'step': 1, 'desc': '观察窗口天数'},
        'anchor_kdj_max': {'label': '锚点J值上限', 'min': 5, 'max': 40, 'step': 5, 'desc': '低位触发日J值上限'},
        'no_break_days': {'label': '护盘天数', 'min': 1, 'max': 10, 'step': 1, 'desc': '连续不破开盘价天数'},
        'breakout_min_pct': {'label': '突破最小涨幅%', 'min': 2, 'max': 10, 'step': 0.5, 'desc': '大阳突破最小涨幅'},
        'breakout_min_streak': {'label': '连续走强天数', 'min': 2, 'max': 10, 'step': 1, 'desc': '突破后最少连续天数'},
        'revisit_kdj_max': {'label': '回踩J值上限', 'min': 5, 'max': 40, 'step': 5, 'desc': 'Setup窗口J值上限'},
        'revisit_band_pct': {'label': '回踩偏离%', 'min': 1, 'max': 10, 'step': 0.5, 'desc': '收盘价距多空线偏离区间'},
    },
}


def _load_stock_names() -> dict:
    names_file = project_root / "data" / "stock_names.json"
    if names_file.exists():
        with open(names_file, 'r', encoding='utf-8') as file:
            return json.load(file)
    return {}


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
    rows = []
    for signal in stock_result.get('signals', []) or [{}]:
        rows.append({
            'code': stock_result.get('code', ''),
            'name': stock_result.get('name', '未知'),
            'strategy_name': strategy_name,
            'category': signal.get('category', strategy_name),
            'date': signal.get('date', ''),
            'trigger_price': signal.get('trigger_price', signal.get('close')),
            'close': signal.get('close'),
            'reason': signal.get('reason', ''),
            'j_value': signal.get('j_value', signal.get('j')),
            'similarity_score': signal.get('similarity_score'),
            'signal': signal,
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

    return {
        'requested_date': requested_date,
        'trade_date': snapshot.get('trade_date'),
        'strategy_filter': strategy_filter,
        'results': filtered_results,
        'groups': filtered_groups,
        'available_groups': sorted(groups.keys()),
        'group_totals': group_totals,
        'total': len(filtered_results),
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
) -> dict:
    effective_date = target_date or get_latest_trade_date()
    strategy_filter = _normalize_strategy_filter(strategy_filter)

    registry = get_registry('config/strategy_params.yaml')
    registry.auto_register_from_directory('strategy')
    stock_names = _load_stock_names()
    all_stocks = csv_manager.list_all_stocks()
    resolved_strategies = _resolve_web_strategies(registry)

    if strategy_filter == 'all':
        selected_filters = list(resolved_strategies.keys())
    else:
        if strategy_filter not in resolved_strategies:
            raise ValueError(f'未注册可用于 Web 的策略: {strategy_filter}')
        selected_filters = [strategy_filter]

    existing_snapshot = _read_strategy_snapshot()
    if strategy_filter == 'all' or not existing_snapshot or existing_snapshot.get('trade_date') != effective_date:
        groups = {}
    else:
        # 单策略重建时尽量复用同交易日的其他策略分组，避免把已有结果整体清空。
        groups = dict(existing_snapshot.get('groups', {}))

    total_tasks = max(1, len(all_stocks) * max(len(selected_filters), 1))
    overall_processed = 0
    overall_matched = 0

    for index, selected_filter in enumerate(selected_filters, start=1):
        item = resolved_strategies[selected_filter]

        if progress_callback:
            progress_callback(
                'strategy_start',
                {
                    'status': 'running',
                    'progress': min(99, int((overall_processed / total_tasks) * 100)),
                    'message': f'开始扫描 {item["strategy_name"]}。',
                    'strategy_filter': selected_filter,
                    'strategy_name': item['strategy_name'],
                    'strategy_index': index,
                    'strategy_count': len(selected_filters),
                    'processed': overall_processed,
                    'total': total_tasks,
                    'matched': overall_matched,
                },
            )

        def on_stock_processed(
            callback_filter: str,
            strategy_name: str,
            stock_result: dict | None,
            strategy_processed: int,
            strategy_total: int,
            strategy_matched: int,
        ):
            nonlocal overall_processed, overall_matched
            overall_processed += 1

            message = (
                f'{strategy_name} 扫描中：{strategy_processed}/{strategy_total}，'
                f'当前命中 {strategy_matched} 只股票。'
            )
            progress = min(99, int((overall_processed / total_tasks) * 100))

            if stock_result:
                rows = _extract_signal_items(strategy_name, stock_result)
                overall_matched += len(rows)
                if progress_callback:
                    progress_callback(
                        'signal',
                        {
                            'status': 'running',
                            'progress': progress,
                            'message': f'{strategy_name} 新增 {len(rows)} 条命中。',
                            'strategy_filter': callback_filter,
                            'strategy_name': strategy_name,
                            'items': rows,
                            'processed': overall_processed,
                            'total': total_tasks,
                            'matched': overall_matched,
                            'strategy_processed': strategy_processed,
                            'strategy_total': strategy_total,
                            'strategy_matched': strategy_matched,
                        },
                    )

            should_emit_progress = (
                stock_result is not None
                or strategy_processed == strategy_total
                or overall_processed == 1
                or overall_processed % 50 == 0
            )
            if progress_callback and should_emit_progress:
                progress_callback(
                    'progress',
                    {
                        'status': 'running',
                        'progress': progress,
                        'message': message,
                        'strategy_filter': callback_filter,
                        'strategy_name': strategy_name,
                        'processed': overall_processed,
                        'total': total_tasks,
                        'matched': overall_matched,
                        'strategy_processed': strategy_processed,
                        'strategy_total': strategy_total,
                        'strategy_matched': strategy_matched,
                    },
                )

        groups[selected_filter] = _scan_strategy(
            selected_filter,
            item['strategy_name'],
            item['strategy'],
            stock_names,
            all_stocks,
            stock_processed_callback=on_stock_processed,
        )

        if progress_callback:
            progress_callback(
                'strategy_complete',
                {
                    'status': 'running',
                    'progress': min(99, int((overall_processed / total_tasks) * 100)),
                    'message': f'{item["strategy_name"]} 扫描完成，共命中 {groups[selected_filter]["total"]} 只股票。',
                    'strategy_filter': selected_filter,
                    'strategy_name': item['strategy_name'],
                    'processed': overall_processed,
                    'total': total_tasks,
                    'matched': overall_matched,
                    'group_total': groups[selected_filter]['total'],
                },
            )

    snapshot = {
        'schema_version': WEB_STRATEGY_SCHEMA_VERSION,
        'trade_date': effective_date,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'groups': groups,
        'available_groups': sorted(groups.keys()),
        'results': _flatten_grouped_results(groups),
        'total': sum(group.get('total', 0) for group in groups.values()),
    }

    WEB_STRATEGY_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = WEB_STRATEGY_RESULTS_FILE.with_suffix('.tmp')
    with open(temp_file, 'w', encoding='utf-8') as file:
        json.dump(snapshot, file, ensure_ascii=False, indent=2)
    temp_file.replace(WEB_STRATEGY_RESULTS_FILE)

    with _STRATEGY_CACHE_LOCK:
        _STRATEGY_CACHE.clear()

    return snapshot


def get_strategy_cache_status(strategy_filter: str = 'all', target_date: str = None) -> dict:
    strategy_filter = _normalize_strategy_filter(strategy_filter)
    effective_date = target_date or get_latest_trade_date()
    snapshot = _read_strategy_snapshot()
    expected_groups = _get_expected_strategy_filters()
    rebuild_state = _get_rebuild_state()

    payload = {
        'requested_date': effective_date,
        'strategy_filter': strategy_filter,
        'cache_file': str(WEB_STRATEGY_RESULTS_FILE),
        'exists': snapshot is not None,
        'trade_date': None,
        'generated_at': None,
        'total': 0,
        'available_groups': [],
        'missing_groups': expected_groups,
        'group_totals': {},
        'status': 'missing',
        'message': '策略缓存文件不存在，请先手动重建。',
        'is_latest': False,
        'selected_strategy_available': strategy_filter == 'all',
        'rebuild': rebuild_state,
    }

    if snapshot is None:
        return payload

    groups = snapshot.get('groups', {})
    available_groups = sorted(groups.keys())
    missing_groups = sorted(set(expected_groups) - set(available_groups))
    snapshot_date = snapshot.get('trade_date')

    payload.update({
        'trade_date': snapshot_date,
        'generated_at': snapshot.get('generated_at'),
        'total': snapshot.get('total', 0),
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

    total_tasks = max(1, len(csv_manager.list_all_stocks()) * max(len(selected_filters), 1))
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

    event_queue: queue.Queue = queue.Queue()
    done_event = threading.Event()

    def emit(event: str, data: dict):
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


def get_strategies_config() -> list:
    registry = get_registry('config/strategy_params.yaml')
    registry.auto_register_from_directory('strategy')
    configs = []
    for name, strategy in registry.strategies.items():
        configs.append({
            'strategy_name': name,
            'params': strategy.params,
            'param_meta': _PARAM_META.get(name, {}),
        })
    return configs


def update_strategy_config(strategy_name: str, new_params: dict) -> bool:
    import yaml
    config_file = project_root / 'config' / 'strategy_params.yaml'

    with open(config_file, 'r', encoding='utf-8') as file:
        config = yaml.safe_load(file) or {}

    if strategy_name not in config:
        config[strategy_name] = {}

    config[strategy_name].update(new_params)

    with open(config_file, 'w', encoding='utf-8') as file:
        yaml.dump(config, file, allow_unicode=True, default_flow_style=False)

    return True
