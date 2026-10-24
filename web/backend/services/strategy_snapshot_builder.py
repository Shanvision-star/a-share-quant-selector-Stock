"""正式全市场扫描与发布：逐股终态留档，完整成功后原子发布数据库版本。"""
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from web.backend.services import strategy_scan as runtime


def _validate_result(result, items):
    outcomes, hits = result['outcomes'], result.get('hits', {})
    code = result['code']
    has_error = any(value['status'] == 'error' for value in outcomes.values())
    if (result.get('status') == 'error') != has_error or set(hits) - set(outcomes):
        raise RuntimeError(f'{code} 股票与策略状态不一致')
    for sf, name, _ in items:
        outcome = outcomes[sf]
        hit = hits.get(sf)
        if outcome['status'] == 'matched':
            stock = (hit or {}).get('stock_result', {})
            signals = stock.get('signals', [])
            if (not signals or stock.get('code') != code or hit.get('strategy_name') != name
                    or outcome.get('signal_count') != len(signals)):
                raise RuntimeError(f'{code}/{sf} 命中与信号不一致')
        elif hit is not None or outcome.get('signal_count', 0) != 0:
            raise RuntimeError(f'{code}/{sf} 未命中终态与信号不一致')
    if result.get('status') in {'skip', 'invalid'} and any(value['status'] != 'skipped' for value in outcomes.values()):
        raise RuntimeError(f'{code} 跳过状态与策略终态不一致')


def build_snapshot(target_date=None, strategy_filter='all', progress_callback=None, run_id=None, strategy_filters=None):
    from web.backend.services import strategy_service as service
    run_id = run_id or service.repo.generate_run_id()
    with runtime.market_job(run_id, 'scan') as cancelled:
        return _build(service, target_date, strategy_filter, progress_callback, run_id, cancelled, strategy_filters)


def _build(service, target_date, strategy_filter, emit, run_id, cancelled, strategy_filters):
    started = time.perf_counter()
    effective_date = target_date or service.get_latest_trade_date()
    strategy_filter = service._normalize_strategy_filter(strategy_filter)
    codes = sorted(service.csv_manager.list_all_stocks())
    expected_codes = set(codes)
    if not codes:
        raise RuntimeError('没有行情文件，不能发布空市场结果')
    root = service.project_root
    paths = [service.csv_manager.get_stock_path(code) for code in codes]
    paths += list((root / 'strategy').glob('*.py'))
    paths += list((root / 'config').rglob('*.yaml'))
    paths += list((root / 'config').rglob('*.json'))
    paths += [root / 'utils' / 'technical.py', root / 'utils' / 'csv_manager.py',
              Path(service.__file__), Path(runtime.__file__), Path(__file__)]
    names_file = root / 'data' / 'stock_names.json'
    if names_file.exists():
        paths.append(names_file)
    manifest = runtime.file_manifest(paths)
    input_id = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    registry = service.get_registry('config/strategy_params.yaml')
    registry.auto_register_from_directory('strategy')
    names = service._load_stock_names()
    items = service._resolve_selected_web_strategies(service._resolve_web_strategies(registry), strategy_filter)
    if strategy_filters is not None:
        selected = {service._normalize_strategy_filter(sf) for sf in strategy_filters}
        if not selected or 'all' in selected:
            raise ValueError('多选策略必须明确指定非空策略集合')
        items = [item for item in items if item[0] in selected]
        if {item[0] for item in items} != selected:
            raise RuntimeError('所选策略未全部注册')
    elif strategy_filter == 'all' and {item[0] for item in items} != set(service._STRATEGY_NAME_MAP):
        raise RuntimeError('全市场扫描策略未全部注册，未发布结果')
    if not items:
        raise RuntimeError('没有可执行策略，未发布结果')
    buffers = service._init_group_buffers(items, service._read_strategy_snapshot(),
             'selected' if strategy_filters is not None else strategy_filter, effective_date)
    expected_filters = {item[0] for item in items}
    counts = {sf: dict.fromkeys(('matched', 'not_matched', 'skipped', 'error'), 0) for sf in expected_filters}
    setup_seconds = time.perf_counter() - started
    if emit:
        for sf, name, _ in items:
            emit('strategy_start', {'status': 'running', 'progress': 0,
                 'message': f'开始扫描 {name}', 'strategy_filter': sf, 'strategy_name': name,
                 'processed': 0, 'total': len(codes), 'matched': 0})
    results = []
    seen = set()
    matched = 0
    compute_started = time.perf_counter()
    backend = 'serial' if os.getenv('QUANT_SCAN_DISABLE_PROCESS') == '1' else 'process'
    for result in runtime.iter_scan_results(codes, names, items, effective_date,
            backend=backend, data_dir=service.csv_manager.data_dir, cancel_event=cancelled):
        code = result.get('code')
        outcomes = result.get('outcomes', {})
        if code not in expected_codes or code in seen or set(outcomes) != expected_filters:
            raise RuntimeError(f'逐股逐策略结果不完整或重复：{code}')
        _validate_result(result, items)
        seen.add(code)
        for sf, outcome in outcomes.items():
            status = outcome.get('status')
            if status not in counts[sf]:
                raise RuntimeError(f'策略终态不完整：{code}/{sf}')
            counts[sf][status] += 1
        results.append(result)
        added, rows = service._merge_stock_hits_into_groups(buffers, result)
        matched += added
        progress = min(99, int(len(results) / len(codes) * 100))
        if emit and (rows or len(results) % 16 == 0 or len(results) == len(codes)):
            data = {'status': 'running', 'progress': progress, 'processed': len(results),
                    'total': len(codes), 'matched': matched, 'strategy_filter': strategy_filter,
                    'current_code': code, 'message': f'扫描中：{len(results)}/{len(codes)}，命中 {matched} 条'}
            if rows:
                emit('signal', dict(data, items=rows, provisional=True))
            emit('progress', data)
    compute_seconds = time.perf_counter() - compute_started
    if seen != expected_codes:
        raise RuntimeError('市场股票覆盖不完整，未发布结果')
    failed = [row for row in results if row.get('status') == 'error' or
              any(outcome['status'] == 'error' for outcome in row['outcomes'].values())]
    unchanged = manifest == runtime.file_manifest(paths) and codes == sorted(service.csv_manager.list_all_stocks())
    summary = {'run_id': run_id, 'target_date': effective_date, 'backend': backend,
               'workers': 1 if backend == 'serial' else min(8, len(codes), os.cpu_count() or 1), 'batch_size': 16,
               'total_stocks': len(codes), 'processed': len(results), 'error_stocks': len(failed),
               'outcomes': counts, 'input_id': input_id, 'inputs_unchanged': unchanged,
               'setup_seconds': setup_seconds, 'compute_seconds': compute_seconds,
               'validation_seconds': time.perf_counter() - compute_started - compute_seconds}
    audit_dir = service.WEB_STRATEGY_RESULTS_FILE.parent / 'scan_runs'
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_file = audit_dir / f'{run_id}-{strategy_filter}.json'
    audit = {'summary': summary, 'manifest': manifest, 'results': sorted(results, key=lambda row: row['code'])}
    audit_file.write_text(json.dumps(audit, ensure_ascii=False, default=service._json_default), encoding='utf-8')
    summary['audit_file'] = str(audit_file)
    if emit:
        emit('scan_summary', dict(summary, progress=99, total=len(codes), matched=matched,
                                 message='逐股逐策略核验完成'))
    if failed:
        raise RuntimeError(f'{len(failed)} 只股票出现策略异常，未覆盖有效缓存；详情：{audit_file}')
    if not unchanged:
        raise RuntimeError('扫描期间行情或策略输入发生变化，未发布结果')
    if cancelled.is_set():
        raise runtime.ScanCancelled('扫描已取消，未发布结果')
    groups = service._finalize_grouped_results(buffers, len(codes))
    for group in groups.values():
        group['results'].sort(key=lambda row: str(row.get('code', '')))
    flat = service._flatten_grouped_results(groups)
    snapshot = {'schema_version': service.WEB_STRATEGY_SCHEMA_VERSION, 'trade_date': effective_date,
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 'groups': groups,
                'available_groups': sorted(groups), 'results': flat,
                'total': len(flat), 'unique_total': len({str(row['code']) for row in flat}),
                '_run_id': run_id, 'scan_summary': summary}
    publish_started = time.perf_counter()
    cache_file = service.WEB_STRATEGY_RESULTS_FILE
    temp = cache_file.with_suffix('.tmp')
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, default=service._json_default), encoding='utf-8')
    # SQLite 是发布点；桌面与 MCP 均读取这一版本。JSON 作为可修复的兼容镜像。
    with runtime.publication_guard(cancelled):
        service._write_results_to_sqlite(run_id, effective_date, strategy_filter, groups, snapshot)
    try:
        temp.replace(cache_file)
    except OSError as exc:
        service.repo.insert_event(run_id, 'cache_mirror_warning', message=str(exc))
    service._clear_strategy_cache()
    timing = dict(summary, publish_seconds=time.perf_counter() - publish_started,
                  total_seconds=time.perf_counter() - started)
    if emit:
        emit('scan_timing', dict(timing, progress=100, message='正式扫描已发布'))
        for sf, name, _ in items:
            emit('strategy_complete', {'status': 'running', 'progress': 100,
                 'message': f'{name} 扫描完成', 'strategy_filter': sf, 'strategy_name': name,
                 'processed': len(codes), 'total': len(codes), 'matched': len(flat),
                 'group_total': groups[sf]['total']})
    return snapshot
