"""验证回测异步任务服务的提交、完成、失败和持久化记录。"""

import sqlite3
import time
from threading import Event

from web.backend.services.backtest_job_service import BacktestJobManager, BacktestTaskRepository


def _memory_connection():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def test_backtest_job_manager_returns_task_status_and_result():
    """任务提交后应立即返回 task_id，后台完成后可查询结果。"""
    def slow_runner(params):
        time.sleep(0.02)
        return {"summary": {"trade_count": 1}, "params": params}

    manager = BacktestJobManager(
        runner=slow_runner,
        max_workers=1,
    )

    submitted = manager.submit({"start_date": "2026-04-24", "end_date": "2026-04-24"})

    assert submitted["task_id"]
    assert submitted["status"] in {"queued", "running"}

    task = manager.wait(submitted["task_id"], timeout=2)

    assert task["status"] == "done"
    assert task["result"]["summary"]["trade_count"] == 1
    assert task["finished_at"]

    fetched = manager.get(submitted["task_id"])
    assert fetched["status"] == "done"
    assert fetched["result"]["params"]["start_date"] == "2026-04-24"


def test_backtest_job_manager_records_failure_message():
    """后台异常不能吞掉，应记录 failed 状态和错误消息供前端展示。"""
    def fail_runner(params):
        time.sleep(0.01)
        raise RuntimeError("boom")

    manager = BacktestJobManager(runner=fail_runner, max_workers=1)

    submitted = manager.submit({"start_date": "2026-04-24", "end_date": "2026-04-24"})
    task = manager.wait(submitted["task_id"], timeout=2)

    assert task["status"] == "failed"
    assert "boom" in task["error"]
    assert task["finished_at"]


def test_backtest_job_repository_persists_finished_task_across_manager_instances():
    """任务完成后应写入 SQLite，新 manager 可恢复并查询历史任务。"""
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)
    manager = BacktestJobManager(
        runner=lambda params, progress_callback=None: {"summary": {"trade_count": 2}, "params": params},
        repository=repository,
        max_workers=1,
    )

    submitted = manager.submit({"start_date": "2026-04-24", "end_date": "2026-04-24"})
    task = manager.wait(submitted["task_id"], timeout=2)
    restored = BacktestJobManager(
        runner=lambda params, progress_callback=None: {},
        repository=repository,
        max_workers=1,
    )

    fetched = restored.get(task["task_id"])
    history = restored.list_recent(limit=5)

    assert fetched["status"] == "done"
    assert fetched["result"]["summary"]["trade_count"] == 2
    assert history[0]["task_id"] == task["task_id"]


def test_backtest_job_manager_records_progress_events():
    """runner 回调进度时，任务和事件流都要持久化，供前端显示真实进度。"""
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)

    def runner(params, progress_callback=None):
        progress_callback({"total_count": 3, "processed_count": 1, "current_code": "000001"})
        progress_callback({"total_count": 3, "processed_count": 2, "current_code": "000002"})
        return {"summary": {"trade_count": 1}}

    manager = BacktestJobManager(runner=runner, repository=repository, max_workers=1)

    submitted = manager.submit({"start_date": "2026-04-24", "end_date": "2026-04-24"})
    task = manager.wait(submitted["task_id"], timeout=2)
    events = manager.list_events(submitted["task_id"])

    assert task["processed_count"] == 2
    assert task["total_count"] == 3
    assert task["progress_pct"] == 100
    assert task["current_code"] == "000002"
    progress_events = [event for event in events if event["event_type"] == "progress"]
    assert progress_events
    assert progress_events[-1]["payload"]["progress_pct"] == 66


def test_backtest_job_manager_cancels_running_task_on_next_progress():
    """运行中的任务收到取消请求后，应在下一次进度边界停止并记录 canceled。"""
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)
    first_progress = Event()
    allow_next_progress = Event()

    def runner(params, progress_callback=None):
        progress_callback({"total_count": 2, "processed_count": 1, "current_code": "000001"})
        first_progress.set()
        assert allow_next_progress.wait(2)
        progress_callback({"total_count": 2, "processed_count": 2, "current_code": "000002"})
        return {"summary": {"trade_count": 99}}

    manager = BacktestJobManager(runner=runner, repository=repository, max_workers=1)
    submitted = manager.submit({"start_date": "2026-04-24", "end_date": "2026-04-24"})

    assert first_progress.wait(2)
    canceling = manager.cancel(submitted["task_id"])
    allow_next_progress.set()
    task = manager.wait(submitted["task_id"], timeout=2)
    event_types = [event["event_type"] for event in manager.list_events(submitted["task_id"])]

    assert canceling["status"] == "cancel_requested"
    assert task["status"] == "canceled"
    assert task["result"] is None
    assert "取消" in task["message"]
    assert "cancel_requested" in event_types
    assert "canceled" in event_types
    assert "failed" not in event_types


def test_backtest_job_manager_cancels_queued_task_before_runner_starts():
    """排队中的任务可直接取消，不能再进入 runner。"""
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)
    blocker_started = Event()
    release_blocker = Event()
    started_names = []

    def runner(params, progress_callback=None):
        started_names.append(params["name"])
        if params["name"] == "blocker":
            blocker_started.set()
            assert release_blocker.wait(2)
        return {"summary": {"trade_count": 0}}

    manager = BacktestJobManager(runner=runner, repository=repository, max_workers=1)
    blocker = manager.submit({"name": "blocker", "start_date": "2026-04-24", "end_date": "2026-04-24"})
    assert blocker_started.wait(2)
    queued = manager.submit({"name": "queued", "start_date": "2026-04-24", "end_date": "2026-04-24"})

    canceled = manager.cancel(queued["task_id"])
    release_blocker.set()
    manager.wait(blocker["task_id"], timeout=2)
    queued_task = manager.get(queued["task_id"])

    assert canceled["status"] == "canceled"
    assert queued_task["status"] == "canceled"
    assert "queued" not in started_names


def test_backtest_job_manager_cancels_persisted_task_without_future():
    """服务重启后没有内存 Future 的未完成任务，应可直接标记为 canceled。"""
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)
    repository.create(
        {
            "task_id": "bt_persisted",
            "status": "queued",
            "created_at": "2026-05-08 09:30:00",
            "params": {"start_date": "2026-04-24", "end_date": "2026-04-24"},
            "message": "排队中",
        }
    )
    manager = BacktestJobManager(
        runner=lambda params, progress_callback=None: {"summary": {"trade_count": 0}},
        repository=repository,
        max_workers=1,
    )

    canceled = manager.cancel("bt_persisted")
    events = manager.list_events("bt_persisted")

    assert canceled["status"] == "canceled"
    assert canceled["finished_at"]
    assert events[-1]["event_type"] == "canceled"
