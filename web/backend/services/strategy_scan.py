"""正式扫描调度：冻结策略实例、进程隔离、完整结果和可取消的行情作业租约。"""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from contextlib import contextmanager
import hashlib
import multiprocessing
import os
from pathlib import Path
import pickle
import sys
import threading
import time


class ScanCancelled(RuntimeError):
    """扫描被主动停止，禁止发布未完成结果。"""


class ScanBusy(RuntimeError):
    """另一个行情写入或扫描正在执行。"""


_job_lock = threading.Lock()
_job = None
_worker_context = None


@contextmanager
def market_job(run_id, kind):
    global _job
    with _job_lock:
        if _job and _job['id'] != run_id:
            raise ScanBusy(f"已有行情任务正在执行：{_job['id']} ({_job['kind']})")
        if _job is None:
            _job = {'id': run_id, 'kind': kind, 'count': 0,
                    'started_at': time.time(), 'cancel': threading.Event()}
        _job['count'] += 1
        cancelled = _job['cancel']
    try:
        if cancelled.is_set():
            raise ScanCancelled('任务已取消')
        yield cancelled
    finally:
        with _job_lock:
            _job['count'] -= 1
            if not _job['count']:
                _job = None


def active_scan_status():
    with _job_lock:
        if not _job:
            return []
        return [{key: _job[key] for key in ('id', 'kind', 'started_at')} |
                {'status': 'cancelling' if _job['cancel'].is_set() else 'running'}]


def cancel_active_scans():
    with _job_lock:
        if not _job:
            return []
        _job['cancel'].set()
        return [_job['id']]


@contextmanager
def publication_guard(cancelled):
    # 取消与数据库提交以同一锁确定先后，避免检查完成后又发布已取消的扫描。
    with _job_lock:
        if cancelled.is_set():
            raise ScanCancelled('扫描已取消，未发布结果')
        yield


def file_manifest(paths):
    manifest = {}
    for raw_path in sorted(paths, key=str):
        path = Path(raw_path)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifest[str(path.resolve())] = digest
    return manifest


def _initialize_worker(frozen_items, names, target_date, data_dir):
    global _worker_context
    # 子进程只计算，不初始化业务数据库，也不重新读取可能已修改的策略配置。
    os.environ['QUANT_SCAN_WORKER'] = '1'
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / 'strategy'))
    from web.backend.services import strategy_service as service
    from utils.csv_manager import CSVManager
    items = pickle.loads(frozen_items)
    service.csv_manager = CSVManager(data_dir)
    _worker_context = (names, items, target_date, service._resolve_common_zhixing_params(items))


def _process_batch(codes):
    from web.backend.services.strategy_service import _process_one_stock
    return [_process_one_stock(code, *_worker_context) for code in codes]


def _stop_pool(pool):
    if hasattr(pool, 'terminate_workers'):
        pool.terminate_workers()
    else:
        processes = list((getattr(pool, '_processes', None) or {}).values())
        for process in processes:
            if process.is_alive():
                process.terminate()
        pool.shutdown(wait=True, cancel_futures=True)


def iter_scan_results(codes, stock_names, strategy_items, target_date, *,
                      backend='process', workers=None, batch_size=16,
                      data_dir=None, cancel_event=None, timeout_seconds=900):
    codes = list(codes)
    if len(codes) != len(set(codes)):
        raise ValueError('扫描股票代码重复')
    cancelled = cancel_event or threading.Event()
    started = time.monotonic()

    def check_running():
        if cancelled.is_set():
            raise ScanCancelled('扫描已取消，未发布结果')
        if time.monotonic() - started > timeout_seconds:
            raise TimeoutError(f'扫描超过 {timeout_seconds} 秒，未发布结果')

    check_running()
    if backend not in {'serial', 'process'}:
        raise ValueError(f'不支持的扫描后端：{backend}')
    if not codes:
        return
    from web.backend.services import strategy_service as service
    if backend == 'serial':
        shared = service._resolve_common_zhixing_params(strategy_items)
        original_manager = service.csv_manager
        try:
            if data_dir is not None:
                from utils.csv_manager import CSVManager
                service.csv_manager = CSVManager(str(data_dir))
            for code in codes:
                check_running()
                yield service._process_one_stock(code, stock_names, strategy_items, target_date, shared)
        finally:
            service.csv_manager = original_manager
        return
    if batch_size < 1:
        raise ValueError('batch_size 必须大于零')
    worker_count = min(len(codes), workers or min(8, os.cpu_count() or 1))
    if worker_count < 1:
        raise ValueError('workers 必须大于零')
    frozen_items = pickle.dumps(strategy_items, protocol=pickle.HIGHEST_PROTOCOL)
    pool = ProcessPoolExecutor(
        max_workers=worker_count, mp_context=multiprocessing.get_context('spawn'),
        initializer=_initialize_worker,
        initargs=(frozen_items, stock_names, target_date,
                  str(data_dir or service.project_root / 'data')),
    )
    completed = False
    try:
        pending = {}
        batches = iter([codes[i:i + batch_size] for i in range(0, len(codes), batch_size)])

        def submit_next():
            batch = next(batches, None)
            if batch is not None:
                pending[pool.submit(_process_batch, batch)] = set(batch)

        for _ in range(worker_count * 2):
            submit_next()
        seen = set()
        while pending:
            check_running()
            done, _ = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                expected = pending.pop(future)
                results = future.result()
                actual = [row['code'] for row in results]
                if len(actual) != len(expected) or set(actual) != expected or seen.intersection(actual):
                    raise RuntimeError('工作进程返回重复或缺失股票，未发布结果')
                seen.update(actual)
                for row in results:
                    check_running()
                    yield row
                submit_next()
        if seen != set(codes):
            raise RuntimeError('扫描结果覆盖不完整，未发布结果')
        completed = True
    finally:
        if completed:
            pool.shutdown(wait=True)
        else:
            _stop_pool(pool)
