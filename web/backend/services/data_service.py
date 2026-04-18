"""数据状态与更新服务"""
import queue
import sys
import random
import asyncio
import concurrent.futures
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from utils.akshare_fetcher import AKShareFetcher
from web.backend.services import strategy_result_repository as repo

csv_manager = CSVManager(str(project_root / "data"))
fetcher = AKShareFetcher(str(project_root / "data"))


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
        sample = random.sample(codes, min(10, len(codes))) if codes else []
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


async def run_data_update(auto_rebuild: bool = True, target_date: str = None, pipeline: bool = False):
    """
    异步执行数据更新，通过 yield 返回进度消息（SSE）
    auto_rebuild=True 时，更新完成后自动执行策略缓存重建
    pipeline=True 时，每只股票更新后立即用内存 df 执行策略扫描，命中结果通过 signal 事件实时推送
    """
    from web.backend.services.strategy_service import (
        get_latest_trade_date,
        build_strategy_result_snapshot,
    )

    run_id = repo.generate_run_id()
    run_type = 'update_and_rebuild' if auto_rebuild else 'update_only'
    effective_date = target_date or get_latest_trade_date()

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
            pipeline_queue.put({
                'event': 'update_progress',
                'data': {
                    'status': 'running', 'progress': 5,
                    'message': f'Pipeline 策略初始化失败，降级为普通模式: {exc}',
                    'run_id': run_id, 'stage': 'update', 'trade_date': effective_date,
                },
            })

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
        except Exception:
            pass

    def do_update():
        return fetcher.daily_update(
            date=effective_date,
            progress_callback=enqueue_update_progress,
            on_stock_ready=on_stock_ready if pipeline else None,
        )

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        try:
            update_future = loop.run_in_executor(pool, do_update)
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

    while not update_queue.empty():
        yield update_queue.get_nowait()

    # drain 剩余 pipeline 事件
    while not pipeline_queue.empty():
        yield pipeline_queue.get_nowait()

    update_summary = update_summary or {}
    update_metrics = {
        key: update_summary.get(key)
        for key in (
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
            'cache_written',
            'cache_hit',
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

    if update_summary.get('status') == 'error':
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
                **update_metrics,
            },
        }
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
    yield {
        "event": "rebuild_start",
        "data": {
            "status": "running", "progress": 42,
            "message": f"{effective_date} 数据更新完成，开始自动重建策略缓存...",
            "run_id": run_id, "stage": "rebuild",
            "trade_date": effective_date,
        },
    }

    try:
        repo.update_run(run_id, stage='rebuild')
    except Exception:
        pass

    event_queue: queue.Queue = queue.Queue()

    def rebuild_progress_callback(event_type: str, data: dict):
        """将策略重建的进度映射到总体进度 42%-98%"""
        raw_progress = data.get('progress', 0)
        mapped_progress = 42 + int(raw_progress * 0.56)
        data['progress'] = min(98, mapped_progress)
        data['run_id'] = run_id
        data['stage'] = 'rebuild'
        event_queue.put({'event': event_type, 'data': data})

    try:
        rebuild_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        snapshot_future = loop.run_in_executor(
            rebuild_pool,
            lambda: build_strategy_result_snapshot(
                target_date=effective_date,
                strategy_filter='all',
                progress_callback=rebuild_progress_callback,
                run_id=run_id,
            ),
        )

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
