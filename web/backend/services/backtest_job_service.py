"""回测异步任务服务。

当前阶段使用进程内任务表和线程池，把长回测从 HTTP 请求生命周期中拆出去。
后续如果需要跨进程恢复，再替换为 SQLite/Redis 持久化队列。
"""

from __future__ import annotations

from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from datetime import datetime
import inspect
import json
from threading import Lock
from typing import Callable
from uuid import uuid4

from web.backend.services.sqlite_service import get_connection
from web.backend.services.backtest_service import run_backtest


BacktestRunner = Callable[[dict], dict]

TERMINAL_STATUSES = {"done", "failed", "canceled"}
CANCEL_STATUSES = {"cancel_requested", "canceled"}


class BacktestJobCancelled(Exception):
    """回测任务被用户请求取消。"""


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _decode_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _encode_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _progress_pct(processed_count: int, total_count: int) -> int:
    if total_count <= 0:
        return 0
    return max(0, min(100, int(processed_count / total_count * 100)))


class BacktestTaskRepository:
    """SQLite 回测任务仓储，保存任务状态和事件流。"""

    def __init__(self, connection_factory=get_connection):
        self.connection_factory = connection_factory
        self._ensure_schema()

    def _conn(self):
        return self.connection_factory()

    def _ensure_schema(self):
        conn = self._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_tasks (
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
            CREATE TABLE IF NOT EXISTS backtest_task_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                progress_pct INTEGER,
                message TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_tasks_created_at ON backtest_tasks(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_tasks_status ON backtest_tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_backtest_events_task_id ON backtest_task_events(task_id)")
        conn.commit()

    def create(self, task: dict):
        conn = self._conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO backtest_tasks
            (task_id, status, created_at, started_at, finished_at, updated_at, error,
             params_json, result_json, total_count, processed_count, current_code, progress_pct, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["task_id"],
                task.get("status", "queued"),
                task.get("created_at") or _now_text(),
                task.get("started_at"),
                task.get("finished_at"),
                _now_text(),
                task.get("error", ""),
                _encode_json(task.get("params") or {}),
                _encode_json(task.get("result")) if task.get("result") is not None else None,
                int(task.get("total_count") or 0),
                int(task.get("processed_count") or 0),
                task.get("current_code") or "",
                int(task.get("progress_pct") or 0),
                task.get("message") or "",
            ),
        )
        conn.commit()
        self.add_event(task["task_id"], "queued", {"status": task.get("status", "queued")})

    def update(self, task_id: str, **changes):
        if not changes:
            return
        columns = []
        values = []
        mapping = {
            "params": "params_json",
            "result": "result_json",
        }
        for key, value in changes.items():
            column = mapping.get(key, key)
            if column in {"params_json", "result_json"}:
                value = _encode_json(value) if value is not None else None
            columns.append(f"{column} = ?")
            values.append(value)
        columns.append("updated_at = ?")
        values.append(_now_text())
        values.append(task_id)
        conn = self._conn()
        conn.execute(f"UPDATE backtest_tasks SET {', '.join(columns)} WHERE task_id = ?", values)
        conn.commit()

    def get(self, task_id: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM backtest_tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_recent(self, limit: int = 20) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM backtest_tasks ORDER BY created_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def add_event(self, task_id: str, event_type: str, payload: dict | None = None, message: str = ""):
        payload = payload or {}
        progress = payload.get("progress_pct")
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO backtest_task_events
            (task_id, event_type, progress_pct, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, event_type, progress, message or payload.get("message", ""), _encode_json(payload), _now_text()),
        )
        conn.commit()

    def list_events(self, task_id: str, limit: int = 500) -> list[dict]:
        rows = self._conn().execute(
            """
            SELECT * FROM backtest_task_events
            WHERE task_id = ?
            ORDER BY event_id ASC
            LIMIT ?
            """,
            (task_id, max(1, int(limit))),
        ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["payload"] = _decode_json(item.pop("payload_json", None), {})
            events.append(item)
        return events

    def _row_to_task(self, row) -> dict:
        item = dict(row)
        item["params"] = _decode_json(item.pop("params_json", None), {})
        item["result"] = _decode_json(item.pop("result_json", None), None)
        item["error"] = item.get("error") or ""
        item["current_code"] = item.get("current_code") or ""
        item["message"] = item.get("message") or ""
        item["total_count"] = int(item.get("total_count") or 0)
        item["processed_count"] = int(item.get("processed_count") or 0)
        item["progress_pct"] = int(item.get("progress_pct") or 0)
        return item


class BacktestJobManager:
    """管理回测任务提交、状态查询和后台执行。"""

    def __init__(
        self,
        runner: BacktestRunner = run_backtest,
        repository: BacktestTaskRepository | None = None,
        max_workers: int = 2,
    ):
        self.runner = runner
        self.repository = repository or BacktestTaskRepository()
        self.executor = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="backtest")
        self._lock = Lock()
        self._tasks: dict[str, dict] = {}
        self._futures: dict[str, Future] = {}

    def submit(self, params: dict) -> dict:
        task_id = f"bt_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
        task = {
            "task_id": task_id,
            "status": "queued",
            "created_at": _now_text(),
            "started_at": None,
            "finished_at": None,
            "error": "",
            "result": None,
            "params": dict(params),
            "total_count": 0,
            "processed_count": 0,
            "current_code": "",
            "progress_pct": 0,
            "message": "排队中",
        }
        with self._lock:
            self._tasks[task_id] = task
        self.repository.create(task)
        future = self.executor.submit(self._run_task, task_id, dict(params))
        with self._lock:
            self._futures[task_id] = future
        return self.get(task_id)

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return dict(task)
        return self.repository.get(task_id)

    def list_recent(self, limit: int = 20) -> list[dict]:
        return self.repository.list_recent(limit)

    def list_events(self, task_id: str, limit: int = 500) -> list[dict]:
        return self.repository.list_events(task_id, limit)

    def cancel(self, task_id: str) -> dict | None:
        """请求取消任务：排队任务立即取消，运行中任务在下一次进度边界停止。"""
        task = self.get(task_id)
        if task is None:
            return None
        if task.get("status") in TERMINAL_STATUSES:
            return task

        self._update(task_id, status="cancel_requested", message="取消中")
        self.repository.add_event(task_id, "cancel_requested", {"status": "cancel_requested"}, "取消中")

        with self._lock:
            future = self._futures.get(task_id)
        if future is None:
            self._mark_canceled(task_id)
        elif future.cancel():
            self._mark_canceled(task_id)

        return self.get(task_id)

    def wait(self, task_id: str, timeout: float | None = None) -> dict:
        future = None
        with self._lock:
            future = self._futures.get(task_id)
        if future is None:
            raise KeyError(task_id)
        try:
            future.result(timeout=timeout)
        except CancelledError:
            pass
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def _run_task(self, task_id: str, params: dict):
        if not self._mark_running(task_id):
            self._mark_canceled(task_id)
            return
        self.repository.add_event(task_id, "running", {"status": "running"}, "运行中")
        try:
            if self._is_cancel_requested(task_id):
                raise BacktestJobCancelled()
            result = self._call_runner(params, self._progress_callback(task_id))
            if self._is_cancel_requested(task_id):
                raise BacktestJobCancelled()
        except BacktestJobCancelled:
            self._mark_canceled(task_id)
            return
        except Exception as exc:  # noqa: BLE001 - 任务边界需要记录所有异常，不能让线程静默失败。
            self._update(task_id, status="failed", error=str(exc), finished_at=_now_text(), message="失败")
            self.repository.add_event(task_id, "failed", {"error": str(exc)}, str(exc))
            return
        self._update(task_id, status="done", result=result, finished_at=_now_text(), progress_pct=100, message="完成")
        self.repository.add_event(task_id, "done", {"progress_pct": 100}, "完成")

    def _call_runner(self, params: dict, progress_callback):
        signature = inspect.signature(self.runner)
        accepts_progress = "progress_callback" in signature.parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if accepts_progress:
            return self.runner(params, progress_callback=progress_callback)
        return self.runner(params)

    def _progress_callback(self, task_id: str):
        def callback(payload: dict):
            if self._is_cancel_requested(task_id):
                raise BacktestJobCancelled()
            total_count = int(payload.get("total_count") or 0)
            processed_count = int(payload.get("processed_count") or 0)
            progress_pct = int(payload.get("progress_pct") or _progress_pct(processed_count, total_count))
            current_code = str(payload.get("current_code") or "")
            message = str(payload.get("message") or (f"正在回测 {current_code}" if current_code else "运行中"))
            changes = {
                "total_count": total_count,
                "processed_count": processed_count,
                "current_code": current_code,
                "progress_pct": progress_pct,
                "message": message,
            }
            self._update(task_id, **changes)
            self.repository.add_event(task_id, "progress", {**changes, **payload}, message)

        return callback

    def _mark_running(self, task_id: str) -> bool:
        changes = {"status": "running", "started_at": _now_text(), "message": "运行中"}
        with self._lock:
            task = self._tasks.get(task_id)
            if task and task.get("status") in CANCEL_STATUSES:
                return False
            if task:
                task.update(changes)
        if not task:
            stored = self.repository.get(task_id)
            if stored and stored.get("status") in CANCEL_STATUSES:
                return False
        self.repository.update(task_id, **changes)
        return True

    def _mark_canceled(self, task_id: str):
        task = self.get(task_id)
        if task and task.get("status") == "canceled":
            return
        self._update(task_id, status="canceled", finished_at=_now_text(), error="", message="已取消")
        self.repository.add_event(task_id, "canceled", {"status": "canceled"}, "已取消")

    def _is_cancel_requested(self, task_id: str) -> bool:
        task = self.get(task_id)
        return bool(task and task.get("status") in CANCEL_STATUSES)

    def _update(self, task_id: str, **changes):
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.update(changes)
        self.repository.update(task_id, **changes)


backtest_job_manager = BacktestJobManager()

