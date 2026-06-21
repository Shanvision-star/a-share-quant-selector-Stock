"""验证回测异步任务服务的提交、完成、失败和持久化记录。"""

import json
import sqlite3
import time
from threading import Event

from web.backend.services.backtest_job_service import BacktestJobManager, BacktestTaskRepository


def _memory_connection():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class _RecordingConnection:
    def __init__(self, conn):
        self.conn = conn
        self.task_list_sql = []

    def execute(self, sql, parameters=()):
        normalized = " ".join(sql.split()).lower()
        if "from backtest_tasks" in normalized and "order by created_at" in normalized:
            self.task_list_sql.append(normalized)
            assert "select *" not in normalized
            assert "result_json" not in normalized
        return self.conn.execute(sql, parameters)

    def commit(self):
        return self.conn.commit()


def test_backtest_repository_records_reproducible_manifest_hashes():
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)
    task = {
        "task_id": "bt_manifest",
        "status": "queued",
        "created_at": "2026-05-08 09:30:00",
        "params": {"end_date": "2026-04-24", "start_date": "2026-04-24"},
        "message": "排队中",
    }

    repository.create(task)
    created = repository.get("bt_manifest")
    repository.update("bt_manifest", status="done", result={"summary": {"trade_count": 1, "return_pct": 2.5}})
    finished = repository.get("bt_manifest")

    assert created["engine_version"] == "backtest-engine-v1-phase-c"
    assert len(created["request_hash"]) == 16
    assert finished["request_hash"] == created["request_hash"]
    assert len(finished["result_hash"]) == 16
    assert finished["summary"]["trade_count"] == 1


def test_backtest_repository_request_hash_is_stable_for_param_key_order():
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)

    repository.create(
        {
            "task_id": "bt_order_a",
            "status": "queued",
            "created_at": "2026-05-08 09:30:00",
            "params": {"start_date": "2026-04-24", "end_date": "2026-04-24"},
            "message": "排队中",
        }
    )
    repository.create(
        {
            "task_id": "bt_order_b",
            "status": "queued",
            "created_at": "2026-05-08 09:31:00",
            "params": {"end_date": "2026-04-24", "start_date": "2026-04-24"},
            "message": "排队中",
        }
    )

    assert repository.get("bt_order_a")["request_hash"] == repository.get("bt_order_b")["request_hash"]


def test_backtest_repository_update_none_result_clears_result_manifest():
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)
    repository.create(
        {
            "task_id": "bt_clear_result",
            "status": "queued",
            "created_at": "2026-05-08 09:30:00",
            "params": {"start_date": "2026-04-24", "end_date": "2026-04-24"},
            "result": {"summary": {"trade_count": 1}},
            "message": "排队中",
        }
    )

    repository.update("bt_clear_result", result=None)

    detail = repository.get("bt_clear_result")
    assert detail["result"] is None
    assert detail["result_hash"] is None
    assert detail["summary"] == {}


def test_backtest_repository_list_recent_omits_heavy_result_by_default():
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)
    repository.create(
        {
            "task_id": "bt_history",
            "status": "queued",
            "created_at": "2026-05-08 09:30:00",
            "params": {"start_date": "2026-04-24", "end_date": "2026-04-24"},
            "message": "排队中",
        }
    )
    repository.update("bt_history", status="done", result={"summary": {"trade_count": 1}, "trades": [{"code": "000001"}]})

    history_item = repository.list_recent(limit=1)[0]
    detail_item = repository.get("bt_history")

    assert history_item["result"] is None
    assert history_item["summary"]["trade_count"] == 1
    assert detail_item["result"]["trades"][0]["code"] == "000001"


def test_backtest_repository_lightweight_list_query_does_not_select_result_json():
    conn = _memory_connection()
    recording = _RecordingConnection(conn)
    repository = BacktestTaskRepository(lambda: recording)
    repository.create(
        {
            "task_id": "bt_lightweight_sql",
            "status": "queued",
            "created_at": "2026-05-08 09:30:00",
            "params": {"start_date": "2026-04-24", "end_date": "2026-04-24"},
            "message": "排队中",
        }
    )
    repository.update(
        "bt_lightweight_sql",
        status="done",
        result={"summary": {"trade_count": 1}, "trades": [{"code": "000001", "payload": "x" * 1024}]},
    )

    history_item = repository.list_recent(limit=1)[0]

    assert recording.task_list_sql
    assert history_item["result"] is None
    assert history_item["summary"]["trade_count"] == 1


def test_backtest_repository_backfills_legacy_summary_from_result_json():
    conn = _memory_connection()
    conn.execute(
        """
        CREATE TABLE backtest_tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            updated_at TEXT NOT NULL,
            error TEXT,
            params_json TEXT,
            result_json TEXT,
            total_count INTEGER DEFAULT 0,
            processed_count INTEGER DEFAULT 0,
            current_code TEXT,
            progress_pct INTEGER DEFAULT 0,
            message TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO backtest_tasks
        (task_id, status, created_at, updated_at, error, params_json, result_json, total_count,
         processed_count, current_code, progress_pct, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "bt_legacy",
            "done",
            "2026-05-08 09:30:00",
            "2026-05-08 09:31:00",
            "",
            json.dumps({"start_date": "2026-04-24", "end_date": "2026-04-24"}, ensure_ascii=False),
            json.dumps({"summary": {"trade_count": 7}, "trades": [{"code": "000001"}]}, ensure_ascii=False),
            0,
            0,
            "",
            100,
            "完成",
        ),
    )
    conn.commit()

    repository = BacktestTaskRepository(lambda: conn)
    history_item = repository.list_recent(limit=1)[0]
    detail_item = repository.get("bt_legacy")

    assert history_item["result"] is None
    assert history_item["summary"]["trade_count"] == 7
    assert detail_item["summary"]["trade_count"] == 7
    assert len(detail_item["result_hash"]) == 16


def test_backtest_repository_detail_can_include_events():
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)
    repository.create(
        {
            "task_id": "bt_events",
            "status": "queued",
            "created_at": "2026-05-08 09:30:00",
            "params": {"start_date": "2026-04-24", "end_date": "2026-04-24"},
            "message": "排队中",
        }
    )
    repository.add_event("bt_events", "progress", {"current_code": "000001"})

    detail = repository.get("bt_events", include_events=True)

    assert detail["events"][-1]["event_type"] == "progress"
    assert detail["events"][-1]["payload"]["current_code"] == "000001"


def test_backtest_job_manager_get_returns_repository_manifest_and_events():
    conn = _memory_connection()
    repository = BacktestTaskRepository(lambda: conn)

    def runner(params, progress_callback=None):
        progress_callback({"total_count": 1, "processed_count": 1, "current_code": "000001"})
        return {"summary": {"trade_count": 3}, "params": params}

    manager = BacktestJobManager(runner=runner, repository=repository, max_workers=1)
    submitted = manager.submit({"start_date": "2026-04-24", "end_date": "2026-04-24"})
    manager.wait(submitted["task_id"], timeout=2)

    detail = manager.get(submitted["task_id"])
    detail_with_events = manager.get(submitted["task_id"], include_events=True)

    assert detail["engine_version"] == "backtest-engine-v1-phase-c"
    assert len(detail["request_hash"]) == 16
    assert len(detail["result_hash"]) == 16
    assert detail["summary"]["trade_count"] == 3
    assert detail_with_events["events"][-1]["event_type"] == "done"


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
