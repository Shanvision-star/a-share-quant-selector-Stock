"""只读比较策略扫描的串行、线程和进程调度，并保存结果等价性与分阶段证据。"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import contextlib
import cProfile
import hashlib
import io
import json
import multiprocessing
from pathlib import Path
import pstats
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def initialize():
    global service, names, items, shared_params
    from web.backend.services import strategy_service as service
    with contextlib.redirect_stdout(io.StringIO()):
        names, items = service.get_resolved_strategy_items()
    shared_params = service._resolve_common_zhixing_params(items)


def scan_batch(task):
    codes, target = task
    rows = []
    for code in codes:
        started = time.perf_counter()
        row = service._process_one_stock(code, names, items, target, shared_params)
        rows.append((row, time.perf_counter() - started))
    return rows


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=service._json_default)


def data_identity(codes):
    # 仅记录输入文件状态；不改变 CSV，也不触发任何行情请求。
    state = [(code, service.csv_manager.get_stock_path(code).stat().st_size,
              service.csv_manager.get_stock_path(code).stat().st_mtime_ns) for code in codes]
    return hashlib.sha256(canonical(state).encode()).hexdigest()


def profile(codes, target, out, enabled):
    timings = defaultdict(float)
    counts = defaultdict(int)
    errors = []
    profiler = cProfile.Profile()
    started = time.perf_counter()
    if enabled:
        profiler.enable()
    for code in codes:
        t = time.perf_counter()
        status, name, frame, _ = service._prepare_stock_context(code, names, target)
        timings['read_and_trim'] += time.perf_counter() - t
        if status != 'ok':
            continue
        t = time.perf_counter()
        shared = service.prepare_shared_indicators(frame, zhixing_params=shared_params)
        timings['shared_indicators'] += time.perf_counter() - t
        for sf, _, strategy in items:
            t = time.perf_counter()
            try:
                strategy.analyze_stock(code, name, shared.copy())
            except Exception as exc:
                errors.append({'code': code, 'strategy': sf, 'error': str(exc)})
            timings[sf] += time.perf_counter() - t
            counts[sf] += 1
    if enabled:
        profiler.disable()
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).sort_stats('cumtime').print_stats(65)
        (out / 'profile.txt').write_text(output.getvalue(), encoding='utf-8')
        profiler.dump_stats(str(out / 'profile.pstats'))
    return {'measurement_seconds': time.perf_counter() - started, 'profiler_enabled': enabled,
            'timings': dict(timings), 'calls': dict(counts), 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--mode', choices=['serial', 'thread', 'process', 'profile', 'stages'], required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--count', type=int, default=512, help='0 表示本地全市场')
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compare', type=Path, help='另一模式生成的 results.json')
    args = parser.parse_args()
    if args.workers < 1 or args.count < 0 or args.batch_size < 1:
        parser.error('workers / batch-size 必须为正数，count 不能为负数')
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    initialize()
    setup_seconds = time.perf_counter() - started
    all_codes = sorted(service.csv_manager.list_all_stocks())
    snapshot = service._read_strategy_snapshot() or {}
    if args.count == 0 or args.count >= len(all_codes):
        codes = all_codes
    else:
        # 固定种子并包含当前全部命中，避免只测没有复杂形态的轻量股票。
        picked = {r['code'] for r in snapshot.get('results', []) if r['code'] in all_codes}
        picked.update(c for c in ['000717', '688613', '300987'] if c in all_codes)
        available = sorted(set(all_codes) - picked)
        if args.count < len(picked):
            codes = sorted(random.Random(42).sample(all_codes, args.count))
        else:
            picked.update(random.Random(42).sample(available, args.count - len(picked)))
            codes = sorted(picked)
    fingerprint = data_identity(codes)
    report = {'date': args.date, 'mode': args.mode, 'workers': args.workers,
              'batch_size': args.batch_size, 'count': len(codes), 'codes': codes,
              'python': sys.version, 'executable': sys.executable,
              'setup_seconds': setup_seconds, 'input_identity': fingerprint,
              'history_rows': service.DEFAULT_STRATEGY_SCAN_ROWS,
              'strategies': [sf for sf, _, _ in items]}
    if args.mode in ('profile', 'stages'):
        report.update(profile(codes, args.date, args.output, args.mode == 'profile'))
    else:
        batches = [(codes[i:i+args.batch_size], args.date)
                   for i in range(0, len(codes), args.batch_size)]
        started = time.perf_counter()
        cpu_started = time.process_time()
        data = []
        if args.mode == 'serial':
            for task in batches:
                data.extend(scan_batch(task))
        else:
            factory = ThreadPoolExecutor if args.mode == 'thread' else ProcessPoolExecutor
            kwargs = {'max_workers': args.workers}
            if args.mode == 'process':
                kwargs.update(initializer=initialize, mp_context=multiprocessing.get_context('spawn'))
            with factory(**kwargs) as pool:
                futures = [pool.submit(scan_batch, task) for task in batches]
                for future in as_completed(futures):
                    data.extend(future.result())
                    if len(data) % 256 == 0 or len(data) == len(codes):
                        print(f'{args.mode}: {len(data)}/{len(codes)} {time.perf_counter()-started:.2f}s', flush=True)
        report['seconds'] = time.perf_counter() - started
        report['parent_cpu_seconds'] = time.process_time() - cpu_started
        rows = sorted([row for row, _ in data], key=lambda row: row['code'])
        report['matched_stocks'] = sum(bool(row['hits']) for row in rows)
        report['slowest'] = sorted([{'code': row['code'], 'seconds': elapsed}
                                    for row, elapsed in data], key=lambda row: row['seconds'], reverse=True)[:20]
        report['result_sha256'] = hashlib.sha256(canonical(rows).encode()).hexdigest()
        (args.output / 'results.json').write_text(canonical(rows), encoding='utf-8')
        if args.compare:
            expected = json.loads(args.compare.read_text(encoding='utf-8'))
            report['matches_comparison'] = canonical(rows) == canonical(expected)
        if set(codes) == set(all_codes) and snapshot.get('trade_date') == args.date:
            groups = service._init_group_buffers(items, {}, 'all', args.date)
            for row in rows:
                service._merge_stock_hits_into_groups(groups, row)
            groups = service._finalize_grouped_results(groups, len(codes))
            actual = service._flatten_grouped_results(groups)
            report['signal_count'] = len(actual)
            report['snapshot_signal_count'] = len(snapshot['results'])
            report['matches_saved_snapshot'] = sorted(map(canonical, actual)) == sorted(map(canonical, snapshot['results']))
    report['inputs_unchanged'] = fingerprint == data_identity(codes)
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('codes', 'slowest')}, ensure_ascii=False), flush=True)
    assert report['inputs_unchanged'], '测量期间行情文件发生变化'
    assert report.get('matches_comparison', True), '调度模式之间结果不一致'
    assert report.get('matches_saved_snapshot', True), '与已保存全市场策略快照不一致'


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
