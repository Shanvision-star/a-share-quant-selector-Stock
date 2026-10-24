"""数据状态与更新服务"""
import queue
import sys
import asyncio
import concurrent.futures
import threading
import time
from pathlib import Path
from datetime import datetime, time as dt_time, timedelta
from typing import Any, Dict

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from utils.akshare_fetcher import AKShareFetcher
from utils.status_sampling import select_status_sample
from utils.trading_calendar import previous_a_share_trading_day
from web.backend.services import strategy_result_repository as repo
from web.backend.services.strategy_scan import market_job, cancel_active_scans, ScanBusy, ScanCancelled

csv_manager = CSVManager(str(project_root / "data"))
fetcher = AKShareFetcher(str(project_root / "data"))

_INTRADAY_FAST_START = dt_time(9, 0)
_INTRADAY_FAST_END = dt_time(15, 0)
_PROCESS_STARTED_AT = datetime.now()
_UPDATE_JOB_LOCK = threading.Lock()
_UPDATE_JOB_STATE: Dict[str, Any] = {}
_UPDATE_RUN_TYPES = {'update_and_rebuild', 'update_only'}


def _parse_repo_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def mark_stale_update_runs_interrupted() -> int:
    """把后端重启前遗留的 running 更新任务标记为中断。

    这些 run 只存在于 SQLite 记录里，真实线程已经随旧进程退出；如果不清理，
    页面会误以为仍有更新任务运行，并可能诱导用户重复启动全市场更新。
    """
    try:
        running = repo.list_runs(status='running', page=1, per_page=500).get('items', [])
    except Exception:
        return 0

    marked = 0
    message = '后端进程已重启，旧数据更新任务已中断；请重新执行本次更新。'
    for run in running:
        if run.get('run_type') not in _UPDATE_RUN_TYPES:
            continue
        started_at = _parse_repo_datetime(run.get('started_at'))
        if not started_at or started_at >= _PROCESS_STARTED_AT:
            continue
        run_id = run.get('run_id')
        if not run_id:
            continue
        try:
            repo.finish_run(run_id, 'error', message)
            repo.insert_event(run_id, 'error', message=message)
            marked += 1
        except Exception:
            pass
    return marked


def _resolve_update_trade_date(allow_intraday_fast: bool = False) -> str:
    """统一作业入口的默认目标日：9:00 前固定使用最近已完成交易日。"""
    now = datetime.now()
    now_time = now.time()
    if now_time >= _INTRADAY_FAST_END:
        target = now.date()
    elif allow_intraday_fast and _INTRADAY_FAST_START <= now_time < _INTRADAY_FAST_END:
        target = now.date()
    else:
        target = now.date() - timedelta(days=1)
    return previous_a_share_trading_day(target).strftime('%Y-%m-%d')


def _enqueue_init_progress(
    event_queue: queue.Queue,
    payload: Dict[str, Any],
    run_id: str,
    trade_date: str,
    progress_start: int,
    progress_span: int,
):
    """统一初始化进度映射，避免重复代码。"""
    raw_progress = max(0, min(100, int(payload.get('progress', 0))))
    mapped_progress = progress_start + int(raw_progress * progress_span / 100)
    data = dict(payload)
    data['progress'] = max(0, min(100, mapped_progress))
    data['status'] = 'running'
    data['run_id'] = run_id
    data['stage'] = 'update'
    data['phase'] = 'init_full'
    data['trade_date'] = trade_date
    event_queue.put({'event': 'init_progress', 'data': data})


def get_data_status() -> dict:
    """
    获取数据状态报告
    - 列出各板块(00/30/60/68)的股票数量
    - 抽样检查各板块最新数据日期
    - 计算数据过期比例
    """
    all_stocks = csv_manager.list_all_stocks()

    boards = {'00': [], '30': [], '60': [], '68': []}
    for code in all_stocks:
        prefix = code[:2]
        if prefix in boards:
            boards[prefix].append(code)

    from web.backend.services.strategy_service import get_latest_trade_date
    expected_date = get_latest_trade_date()

    board_status = {}
    latest_dates = []
    stale_count = 0
    checked = 0

    for board_name, codes in boards.items():
        sample = select_status_sample(codes, sample_size=10) if codes else []
        board_latest = None
        board_stale = 0

        for code in sample:
            df = csv_manager.read_stock(code)
            if not df.empty:
                stock_date = df.iloc[0]['date'].strftime('%Y-%m-%d') if hasattr(df.iloc[0]['date'], 'strftime') else str(df.iloc[0]['date'])[:10]
                if stock_date < expected_date:
                    board_stale += 1
                    stale_count += 1
                if board_latest is None or stock_date > board_latest:
                    board_latest = stock_date
                checked += 1

        board_status[board_name] = {
            'total': len(codes),
            'latest_date': board_latest or '-',
            'stale_ratio': round(board_stale / max(len(sample), 1) * 100, 1),
        }
        if board_latest:
            latest_dates.append(board_latest)

    return {
        'total_stocks': len(all_stocks),
        'latest_date': max(latest_dates) if latest_dates else '-',
        'stale_count': stale_count,
        'checked_count': checked,
        'is_fresh': stale_count / max(checked, 1) < 0.3,
        'boards': board_status,
    }


async def run_data_update(
    auto_rebuild: bool = True,
    target_date: str = None,
    pipeline: bool = False,
    allow_intraday_fast: bool = False,
    init_if_empty: bool = True,
    strategies: list = None,
):
    """数据更新统一入口：同一进程内只允许一个全市场更新任务运行。"""
    effective_date = target_date if target_date else _resolve_update_trade_date(
        allow_intraday_fast=allow_intraday_fast
    )

    if not _UPDATE_JOB_LOCK.acquire(blocking=False):
        active_state = dict(_UPDATE_JOB_STATE)
        active_run_id = active_state.get('run_id', '')
        active_date = active_state.get('trade_date', '')
        yield {
            "event": "error",
            "data": {
                "status": "busy",
                "progress": 100,
                "message": (
                    f"已有数据更新任务正在运行（run_id: {active_run_id or '-'}，"
                    f"日期: {active_date or '-'}），请等待完成后再启动。"
                ),
                "active_run_id": active_run_id,
                "active_trade_date": active_date,
                "stage": "update",
                "trade_date": effective_date,
            },
        }
        return

    run_id = repo.generate_run_id()
    _UPDATE_JOB_STATE.clear()
    _UPDATE_JOB_STATE.update({
        'is_running': True,
        'run_id': run_id,
        'trade_date': effective_date,
        'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })

    messages = _market_update_messages(
        auto_rebuild=auto_rebuild,
        target_date=target_date,
        pipeline=pipeline,
        allow_intraday_fast=allow_intraday_fast,
        init_if_empty=init_if_empty,
        strategies=strategies,
        _run_id=run_id,
        _effective_date=effective_date,
    )
    try:
        async for msg in messages:
            yield msg
    finally:
        try:
            await messages.aclose()
        finally:
            _UPDATE_JOB_STATE.clear()
            _UPDATE_JOB_LOCK.release()


async def _market_update_messages(**kwargs):
    run_id = kwargs['_run_id']
    started = time.perf_counter()
    try:
        with market_job(run_id, 'update') as cancelled:
            messages = _run_data_update_unlocked(**kwargs, _cancel_event=cancelled)
            terminal = False
            try:
                async for message in messages:
                    terminal = message['event'] in {'job_complete', 'error'}
                    if cancelled.is_set() and not terminal:
                        message['data']['status'] = 'cancelling'
                        message['data']['message'] = '正在等待行情写入结束，完成后停止作业'
                    if message['event'] in {'update_complete', 'job_complete', 'error', 'pipeline_error'}:
                        message['data']['elapsed_seconds'] = time.perf_counter() - started
                        repo.insert_event(run_id, message['event'], payload=message['data'])
                    yield message
            finally:
                if not terminal:
                    cancel_active_scans()
                    _record_interrupted_market_job(run_id)
                await messages.aclose()
    except (ScanBusy, ScanCancelled) as exc:
        if repo.get_run(run_id):
            repo.finish_run(run_id, 'error', str(exc))
        yield {'event': 'error', 'data': {'status': 'busy' if isinstance(exc, ScanBusy) else 'error',
               'run_id': run_id, 'progress': 100, 'message': str(exc)}}


def _check_market_cancelled(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise ScanCancelled('行情作业已取消，未发布结果')


def _record_interrupted_market_job(run_id):
    try:
        run = repo.get_run(run_id)
        if run is None:
            return
        from web.backend.services.strategy_service import WEB_STRATEGY_RESULTS_FILE
        published = repo.get_published_snapshot(str(WEB_STRATEGY_RESULTS_FILE.resolve()))
        # 取消与提交已有共同锁；断连发生在提交之后不能把已发布运行改为失败。
        # 仓储读口限定当前缓存且排除失效版本，旧 run 或其他配置缓存不能充当成功证据。
        if (published and published.get('_authoritative')
                and published.get('_run_id') == run_id
                and published.get('trade_date') == run.get('trade_date')):
            summary = published.get('scan_summary') or {}
            processed = summary.get('processed')
            if processed is None:
                processed = summary.get('total_stocks', run.get('total_count', 0))
            repo.finish_run(run_id, 'done', '正式结果已发布；发布后连接中断',
                            matched_count=int(published.get('total') or 0),
                            processed_count=int(processed or 0))
            return
        repo.finish_run(run_id, 'error', '连接中断或任务取消；等待已开始的行情写入结束')
    except Exception:
        pass


def _execute_market_writer(run_id, kind, operation, cancelled=None):
    """真实写入线程持有租约，避免 SSE 断连后后台写入与新扫描重叠。"""
    with market_job(run_id, kind) as worker_cancelled:
        _check_market_cancelled(cancelled)
        result = operation()
        _check_market_cancelled(cancelled)
        _check_market_cancelled(worker_cancelled)
        return result


def _observe_market_future(future):
    # 断连后流不再 await，仍领取后台异常，避免产生无人处理的 Future 告警。
    if not future.cancelled():
        future.exception()


async def _run_data_update_unlocked(
    auto_rebuild: bool = True,
    target_date: str = None,
    pipeline: bool = False,
    allow_intraday_fast: bool = False,
    init_if_empty: bool = True,
    strategies: list = None,
    _run_id: str = None,
    _effective_date: str = None,
    _cancel_event=None,
):
    """
    异步执行数据更新，通过 yield 返回进度消息（SSE）
    auto_rebuild=True 时，更新完成后自动执行策略缓存重建
    pipeline=True 且 auto_rebuild=False 时，每只股票更新后内联筛选；统一作业只在重建阶段筛选一次。
    strategies 为 None 或 ['all'] 时跑全部策略；否则只对所选策略增量重建缓存
    """
    from web.backend.services.strategy_service import (
        build_strategy_result_snapshot,
    )

    # 自动重建会覆盖全市场并推送 signal；更新阶段再筛一次会重复计算，且可能使用不同历史窗口。
    pipeline = pipeline and not auto_rebuild

    run_id = _run_id or repo.generate_run_id()
    run_type = 'update_and_rebuild' if auto_rebuild else 'update_only'
    if _effective_date:
        effective_date = _effective_date
    elif target_date:
        effective_date = target_date
    else:
        effective_date = _resolve_update_trade_date(allow_intraday_fast=allow_intraday_fast)

    try:
        repo.create_run(run_id, run_type, effective_date, 'all')
    except Exception:
        pass

    yield {
        "event": "job_start",
        "data": {
            "status": "start", "progress": 2,
            "message": (
                f"开始统一作业：{effective_date} 数据更新"
                + (" + 策略重建" if auto_rebuild else "")
            ),
            "run_id": run_id, "run_type": run_type, "stage": "update",
            "trade_date": effective_date,
        },
    }

    # ─── 预检查：先判断本地数据完整性 ───
    all_stocks = csv_manager.list_all_stocks()
    precheck_state = 'ready' if all_stocks else 'empty'
    yield {
        "event": "precheck",
        "data": {
            "status": "running",
            "progress": 4,
            "message": (
                f"更新前预检查完成：本地CSV {len(all_stocks)} 只"
                if all_stocks else
                "更新前预检查：本地无CSV，将进入首次全量初始化"
            ),
            "run_id": run_id,
            "stage": "update",
            "phase": "precheck",
            "trade_date": effective_date,
            "precheck_state": precheck_state,
            "total_stocks": len(all_stocks),
            "allow_intraday_fast": bool(allow_intraday_fast),
            "init_if_empty": bool(init_if_empty),
        },
    }

    if not all_stocks and not init_if_empty:
        message = "本地无数据，请先执行全量初始化（/api/data/init）"
        try:
            repo.finish_run(run_id, 'error', message)
            repo.insert_event(run_id, 'error', message=message)
        except Exception:
            pass
        yield {
            "event": "error",
            "data": {
                "status": "error", "progress": 100,
                "message": message,
                "run_id": run_id,
                "stage": "update",
                "phase": "precheck",
                "trade_date": effective_date,
                "precheck_state": "empty",
            },
        }
        return

    if not all_stocks and init_if_empty:
        init_queue: queue.Queue = queue.Queue()
        init_message = "首次使用，开始全量初始化（6年历史）..."
        yield {
            "event": "init_start",
            "data": {
                "status": "running",
                "progress": 5,
                "message": init_message,
                "run_id": run_id,
                "stage": "update",
                "phase": "init_full",
                "trade_date": effective_date,
            },
        }

        def enqueue_init_progress(payload: Dict[str, Any]):
            _enqueue_init_progress(
                event_queue=init_queue,
                payload=payload,
                run_id=run_id,
                trade_date=effective_date,
                progress_start=5,
                progress_span=20,
            )

        def do_init():
            return _execute_market_writer(run_id, 'init',
                lambda: fetcher.init_full_data(progress_callback=enqueue_init_progress), _cancel_event)

        init_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            init_future = asyncio.get_event_loop().run_in_executor(init_pool, do_init)
            init_future.add_done_callback(_observe_market_future)
            while not init_future.done() or not init_queue.empty():
                drained = False
                try:
                    yield init_queue.get_nowait()
                    drained = True
                except queue.Empty:
                    pass
                if not drained:
                    await asyncio.sleep(0.05)
            init_summary = await init_future
        finally:
            init_pool.shutdown(wait=False, cancel_futures=True)
        _check_market_cancelled(_cancel_event)

        while not init_queue.empty():
            yield init_queue.get_nowait()

        init_summary = init_summary or {}
        if init_summary.get('status') == 'error':
            message = init_summary.get('message') or '全量初始化失败'
            try:
                repo.finish_run(run_id, 'error', message)
                repo.insert_event(run_id, 'error', message=message)
            except Exception:
                pass
            yield {
                "event": "error",
                "data": {
                    "status": "error",
                    "progress": 100,
                    "message": message,
                    "run_id": run_id,
                    "stage": "update",
                    "phase": "init_full",
                    "trade_date": effective_date,
                },
            }
            return

        yield {
            "event": "init_complete",
            "data": {
                "status": "running",
                "progress": 25,
                "message": (
                    f"全量初始化完成：成功 {init_summary.get('success', 0)}，"
                    f"失败 {init_summary.get('failed', 0)}，开始增量更新"
                ),
                "run_id": run_id,
                "stage": "update",
                "phase": "init_full",
                "trade_date": effective_date,
                "init_total": init_summary.get('total', 0),
                "init_success": init_summary.get('success', 0),
                "init_failed": init_summary.get('failed', 0),
            },
        }

    # ─── 阶段 1：数据更新 ───
    yield {
        "event": "update_start",
        "data": {
            "status": "running", "progress": 5,
            "message": f"开始更新 {effective_date} 数据...",
            "run_id": run_id, "stage": "update",
            "trade_date": effective_date,
            "scan_total": 0,
            "checked": 0,
            "to_update": 0,
            "up_to_date": 0,
            "completed": 0,
            "updated": 0,
            "failed": 0,
            "remaining": 0,
            "verify_total": 0,
            "verify_reached": 0,
        },
    }

    update_queue: queue.Queue = queue.Queue()

    def enqueue_update_progress(payload: dict):
        raw_progress = max(0, min(100, int(payload.get('progress', 0))))
        mapped_progress = 5 + int(raw_progress * 0.35)
        data = dict(payload)
        data['progress'] = min(40, mapped_progress)
        data['status'] = 'running'
        data['run_id'] = run_id
        data['stage'] = 'update'
        data['trade_date'] = effective_date
        update_queue.put({'event': 'update_progress', 'data': data})

    # ── Pipeline 模式：初始化策略上下文 + on_stock_ready 回调 ──
    pipeline_queue: queue.Queue = queue.Queue()
    pipeline_stock_names = None
    pipeline_selected_items = None
    pipeline_errors = []
    pipeline_error_lock = threading.Lock()

    def record_pipeline_error(code, exc):
        with pipeline_error_lock:
            pipeline_errors.append({'code': code, 'error_type': type(exc).__name__, 'error_message': str(exc)})
            error_count = len(pipeline_errors)
        pipeline_queue.put({'event': 'pipeline_error', 'data': {
            'status': 'error', 'progress': 5, 'run_id': run_id, 'stage': 'update',
            'trade_date': effective_date, 'code': code, 'error_type': type(exc).__name__,
            'message': f'策略检查失败：{code or "初始化"}，{exc}', 'pipeline_error_count': error_count,
        }})

    if pipeline:
        try:
            from web.backend.services.strategy_service import (
                get_resolved_strategy_items,
                scan_one_stock_with_df,
            )
            pipeline_stock_names, pipeline_selected_items = get_resolved_strategy_items()
        except Exception as exc:
            # 策略初始化失败不阻塞数据更新，降级为非 pipeline 模式
            pipeline = False
            record_pipeline_error(None, exc)

    def on_stock_ready(code, df):
        """pipeline 回调：更新成功后立即执行策略扫描（在线程池线程中运行）"""
        if not pipeline or pipeline_selected_items is None:
            return
        try:
            from web.backend.services.strategy_service import scan_one_stock_with_df
            rows = scan_one_stock_with_df(code, df, pipeline_stock_names, pipeline_selected_items)
            if rows:
                pipeline_queue.put({
                    'event': 'signal',
                    'data': {
                        'status': 'running',
                        'message': f'更新阶段命中 {len(rows)} 条',
                        'items': rows,
                        'run_id': run_id,
                        'stage': 'update',
                        'trade_date': effective_date,
                    },
                })
        except Exception as exc:
            record_pipeline_error(code, exc)

    def do_update():
        return _execute_market_writer(run_id, 'update', lambda: fetcher.daily_update(
            date=effective_date,
            progress_callback=enqueue_update_progress,
            on_stock_ready=on_stock_ready if pipeline else None,
            allow_intraday_fast=allow_intraday_fast,
        ), _cancel_event)

    loop = asyncio.get_event_loop()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        try:
            update_future = loop.run_in_executor(pool, do_update)
            update_future.add_done_callback(_observe_market_future)
            while not update_future.done() or not update_queue.empty() or not pipeline_queue.empty():
                drained = False
                for q in (update_queue, pipeline_queue):
                    try:
                        yield q.get_nowait()
                        drained = True
                    except queue.Empty:
                        pass
                if not drained:
                    await asyncio.sleep(0.05)

            update_summary = await update_future
        except Exception as exc:
            try:
                repo.finish_run(run_id, 'error', f'数据更新失败: {exc}')
                repo.insert_event(run_id, 'error', message=str(exc))
            except Exception:
                pass
            yield {
                "event": "error",
                "data": {
                    "status": "error", "progress": 100,
                    "message": f"数据更新失败: {exc}",
                    "run_id": run_id, "stage": "update",
                    "trade_date": effective_date,
                },
            }
            return
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    _check_market_cancelled(_cancel_event)

    while not update_queue.empty():
        yield update_queue.get_nowait()

    # drain 剩余 pipeline 事件
    while not pipeline_queue.empty():
        yield pipeline_queue.get_nowait()

    update_summary = update_summary or {}
    actual_update_date = update_summary.get('target_date') or effective_date
    actual_update_date = str(actual_update_date)[:10] if actual_update_date else effective_date
    if actual_update_date != effective_date:
        requested_effective_date = effective_date
        effective_date = actual_update_date
        try:
            repo.update_run(run_id, trade_date=effective_date)
            repo.insert_event(
                run_id,
                'target_date_adjusted',
                message=f'更新目标日期从 {requested_effective_date} 调整为 {effective_date}',
            )
        except Exception:
            pass
    update_summary['target_date'] = effective_date

    update_metrics = {
        key: update_summary.get(key)
        for key in (
            'target_date',
            'scan_total',
            'checked',
            'to_update',
            'up_to_date',
            'completed',
            'updated',
            'failed',
            'remaining',
            'verify_total',
            'verify_reached',
            'verification_passed',
            'cache_written',
            'cache_hit',
            'allow_intraday_fast',
            'precheck_state',
            'init_total',
            'init_success',
            'init_failed',
            'fast_path_total',
            'fast_path_success',
            'fast_path_failed',
            'short_path_total',
            'short_path_success',
            'short_path_failed',
            'slow_path_total',
            'slow_path_reasons',
            'retry_total',
            'retry_success',
            'retry_failed',
        )
        if key in update_summary
    }

    if update_summary.get('completed', 0) > 0 and not update_summary.get('cache_hit'):
        try:
            from web.backend.routers.stock import invalidate_stock_list_cache, trigger_metric_snapshot_prewarm
            invalidate_stock_list_cache()
            trigger_metric_snapshot_prewarm()
        except Exception:
            pass

    # 行情未完整验证时保留旧快照，不能把混合日期结果发布成当日全市场完成。
    update_status = update_summary.get('status')
    if update_status in {'error', 'partial'}:
        message = update_summary.get('message') or '数据更新失败'
        try:
            repo.finish_run(run_id, 'error', message)
            repo.insert_event(run_id, 'error', message=message)
        except Exception:
            pass
        yield {
            "event": "error",
            "data": {
                "status": "error", "progress": 100,
                "message": message,
                "run_id": run_id, "stage": "update",
                "trade_date": effective_date,
                "update_status": update_status,
                **update_metrics,
            },
        }
        return

    if pipeline_errors:
        message = f'行情更新已完成，但 {len(pipeline_errors)} 项策略检查失败；未发布策略结果'
        repo.finish_run(run_id, 'error', message)
        yield {'event': 'error', 'data': {
            'status': 'error', 'progress': 100, 'message': message, 'run_id': run_id,
            'stage': 'pipeline', 'trade_date': effective_date, 'update_status': update_status,
            'pipeline_error_count': len(pipeline_errors), 'pipeline_errors': pipeline_errors[:20],
            **update_metrics,
        }}
        return

    yield {
        "event": "update_complete",
        "data": {
            "status": "running", "progress": 40,
            "message": update_summary.get('message') or f"{effective_date} 数据更新完成",
            "run_id": run_id, "stage": "update",
            "trade_date": effective_date,
            **update_metrics,
        },
    }

    if not auto_rebuild:
        _check_market_cancelled(_cancel_event)
        try:
            repo.finish_run(run_id, 'done', update_summary.get('message') or f'{effective_date} 数据更新完成')
        except Exception:
            pass
        yield {
            "event": "job_complete",
            "data": {
                "status": "done", "progress": 100,
                "message": update_summary.get('message') or f"{effective_date} 数据更新完成",
                "run_id": run_id,
                "trade_date": effective_date,
                **update_metrics,
            },
        }
        return

    # ─── 阶段 2：自动策略缓存重建 ───
    _check_market_cancelled(_cancel_event)
    yield {
        "event": "rebuild_start",
        "data": {
            "status": "running", "progress": 42,
            "message": f"{effective_date} 数据更新完成，开始自动重建策略缓存...",
            "run_id": run_id, "stage": "rebuild",
            "trade_date": effective_date,
        },
    }

    rebuild_total = max(1, len(csv_manager.list_all_stocks()))
    try:
        repo.update_run(
            run_id,
            stage='rebuild',
            total_count=rebuild_total,
            processed_count=0,
            matched_count=0,
            message=f'{effective_date} 数据更新完成，策略缓存重建中',
        )
    except Exception:
        pass

    event_queue: queue.Queue = queue.Queue()
    last_persisted_progress = -5

    def rebuild_progress_callback(event_type: str, data: dict):
        """将策略重建的进度映射到总体进度 42%-98%"""
        nonlocal last_persisted_progress
        if event_type in {'scan_summary', 'scan_timing'}:
            repo.insert_event(run_id, event_type, payload=data)
        raw_progress = data.get('progress', 0)
        processed = int(data.get('processed') or 0)
        total = int(data.get('total') or rebuild_total)
        matched = int(data.get('matched') or 0)
        if raw_progress >= last_persisted_progress + 5 or raw_progress >= 100:
            try:
                repo.update_run(
                    run_id,
                    processed_count=processed,
                    total_count=total,
                    matched_count=matched,
                    message=data.get('message') or '策略缓存重建中',
                )
                last_persisted_progress = raw_progress
            except Exception:
                pass
        mapped_progress = 42 + int(raw_progress * 0.56)
        data['progress'] = min(98, mapped_progress)
        data['run_id'] = run_id
        data['stage'] = 'rebuild'
        event_queue.put({'event': event_type, 'data': data})

    try:
        rebuild_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        # 解析待重建策略集
        valid_filters = ['b1', 'b2', 'bowl', 'brick', 'zettaranc']
        if not strategies or set(strategies) >= set(valid_filters):
            target_filters = ['all']
        else:
            target_filters = [s for s in strategies if s in valid_filters] or ['all']

        def _run_rebuild():
            # 所选策略一次计算并一次发布，任何策略失败都不能留下半个正式快照。
            options = {'strategy_filters': target_filters} if target_filters != ['all'] else {}
            return build_strategy_result_snapshot(
                target_date=effective_date,
                strategy_filter='all',
                progress_callback=rebuild_progress_callback,
                run_id=run_id,
                **options,
            )
        snapshot_future = loop.run_in_executor(rebuild_pool, _run_rebuild)

        while not snapshot_future.done() or not event_queue.empty():
            try:
                yield event_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)

        snapshot = await snapshot_future
        rebuild_pool.shutdown(wait=False)

        while not event_queue.empty():
            yield event_queue.get_nowait()

        try:
            repo.finish_run(
                run_id, 'done', f'统一作业完成：{effective_date} 数据更新 + 策略重建',
                matched_count=snapshot.get('total', 0),
                processed_count=rebuild_total,
            )
            repo.insert_event(run_id, 'job_complete', message='统一作业完成')
        except Exception:
            pass

        yield {
            "event": "job_complete",
            "data": {
                "status": "done", "progress": 100,
                "message": f"统一作业完成：{effective_date} 数据更新 + 策略重建，共命中 {snapshot.get('total', 0)} 条结果",
                "run_id": run_id,
                "trade_date": snapshot.get('trade_date'),
                "total_results": snapshot.get('total', 0),
                "available_groups": sorted(snapshot.get('groups', {}).keys()),
            },
        }

    except Exception as exc:
        if 'rebuild_pool' in locals():
            rebuild_pool.shutdown(wait=False)
        while not event_queue.empty():
            yield event_queue.get_nowait()

        try:
            repo.finish_run(run_id, 'error', f'策略重建失败: {exc}')
        except Exception:
            pass

        yield {
            "event": "error",
            "data": {
                "status": "error", "progress": 100,
                "message": f"策略缓存重建失败: {exc}",
                "run_id": run_id, "stage": "rebuild",
                "trade_date": effective_date,
            },
        }


async def run_data_init(max_stocks: int = None):
    run_id = repo.generate_run_id()
    try:
        with market_job(run_id, 'init') as cancelled:
            messages = _run_data_init_unlocked(max_stocks, _run_id=run_id, _cancel_event=cancelled)
            terminal = False
            try:
                async for message in messages:
                    terminal = message['event'] in {'job_complete', 'error'}
                    if cancelled.is_set() and not terminal:
                        message['data']['status'] = 'cancelling'
                        message['data']['message'] = '正在等待初始化写入结束'
                    yield message
            finally:
                if not terminal:
                    cancel_active_scans()
                    _record_interrupted_market_job(run_id)
                await messages.aclose()
    except (ScanBusy, ScanCancelled) as exc:
        yield {'event': 'error', 'data': {'status': 'error', 'message': str(exc), 'progress': 100}}


async def _run_data_init_unlocked(max_stocks: int = None, _run_id=None, _cancel_event=None):
    """异步执行首次全量初始化，通过 SSE 返回进度。"""
    from web.backend.services.strategy_service import get_latest_trade_date

    run_id = _run_id or repo.generate_run_id()
    run_type = 'init_only'
    effective_date = get_latest_trade_date()

    try:
        repo.create_run(run_id, run_type, effective_date, 'all')
    except Exception:
        pass

    yield {
        "event": "init_start",
        "data": {
            "status": "running",
            "progress": 2,
            "message": "开始首次全量初始化（6年历史）...",
            "run_id": run_id,
            "stage": "update",
            "phase": "init_full",
            "trade_date": effective_date,
        },
    }

    init_queue: queue.Queue = queue.Queue()

    def enqueue_init_progress(payload: Dict[str, Any]):
        _enqueue_init_progress(
            event_queue=init_queue,
            payload=payload,
            run_id=run_id,
            trade_date=effective_date,
            progress_start=2,
            progress_span=93,
        )

    def do_init():
        return _execute_market_writer(run_id, 'init', lambda: fetcher.init_full_data(
            max_stocks=max_stocks, progress_callback=enqueue_init_progress), _cancel_event)

    loop = asyncio.get_event_loop()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        try:
            init_future = loop.run_in_executor(pool, do_init)
            init_future.add_done_callback(_observe_market_future)
            while not init_future.done() or not init_queue.empty():
                drained = False
                try:
                    yield init_queue.get_nowait()
                    drained = True
                except queue.Empty:
                    pass
                if not drained:
                    await asyncio.sleep(0.05)
            init_summary = await init_future
        except Exception as exc:
            message = f"初始化失败: {exc}"
            try:
                repo.finish_run(run_id, 'error', message)
                repo.insert_event(run_id, 'error', message=message)
            except Exception:
                pass
            yield {
                "event": "error",
                "data": {
                    "status": "error",
                    "progress": 100,
                    "message": message,
                    "run_id": run_id,
                    "stage": "update",
                    "phase": "init_full",
                    "trade_date": effective_date,
                },
            }
            return
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    _check_market_cancelled(_cancel_event)

    while not init_queue.empty():
        yield init_queue.get_nowait()

    init_summary = init_summary or {}
    if init_summary.get('status') == 'error':
        message = init_summary.get('message') or '初始化失败'
        try:
            repo.finish_run(run_id, 'error', message)
            repo.insert_event(run_id, 'error', message=message)
        except Exception:
            pass
        yield {
            "event": "error",
            "data": {
                "status": "error",
                "progress": 100,
                "message": message,
                "run_id": run_id,
                "stage": "update",
                "phase": "init_full",
                "trade_date": effective_date,
            },
        }
        return

    try:
        repo.finish_run(
            run_id,
            'done',
            (
                f"全量初始化完成：总计 {init_summary.get('total', 0)}，"
                f"成功 {init_summary.get('success', 0)}，失败 {init_summary.get('failed', 0)}"
            ),
        )
        repo.insert_event(run_id, 'job_complete', message='全量初始化完成')
    except Exception:
        pass

    yield {
        "event": "job_complete",
        "data": {
            "status": "done",
            "progress": 100,
            "message": (
                f"全量初始化完成：总计 {init_summary.get('total', 0)}，"
                f"成功 {init_summary.get('success', 0)}，失败 {init_summary.get('failed', 0)}"
            ),
            "run_id": run_id,
            "stage": "update",
            "phase": "init_full",
            "trade_date": effective_date,
            "init_total": init_summary.get('total', 0),
            "init_success": init_summary.get('success', 0),
            "init_failed": init_summary.get('failed', 0),
        },
    }
