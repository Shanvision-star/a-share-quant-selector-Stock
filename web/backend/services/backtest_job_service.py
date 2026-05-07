"""回测异步任务服务。

当前阶段使用进程内任务表和线程池，把长回测从 HTTP 请求生命周期中拆出去。
后续如果需要跨进程恢复，再替换为 SQLite/Redis 持久化队列。
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Callable
from uuid import uuid4

from web.backend.services.backtest_service import run_backtest


BacktestRunner = Callable[[dict], dict]


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class BacktestJobManager:
    """管理回测任务提交、状态查询和后台执行。"""

    def __init__(self, runner: BacktestRunner = run_backtest, max_workers: int = 2):
        self.runner = runner
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
        }
        with self._lock:
            self._tasks[task_id] = task
        future = self.executor.submit(self._run_task, task_id, dict(params))
        with self._lock:
            self._futures[task_id] = future
        return self.get(task_id)

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def wait(self, task_id: str, timeout: float | None = None) -> dict:
        future = None
        with self._lock:
            future = self._futures.get(task_id)
        if future is None:
            raise KeyError(task_id)
        future.result(timeout=timeout)
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return task

    def _run_task(self, task_id: str, params: dict):
        self._update(task_id, status="running", started_at=_now_text())
        try:
            result = self.runner(params)
        except Exception as exc:  # noqa: BLE001 - 任务边界需要记录所有异常，不能让线程静默失败。
            self._update(task_id, status="failed", error=str(exc), finished_at=_now_text())
            return
        self._update(task_id, status="done", result=result, finished_at=_now_text())

    def _update(self, task_id: str, **changes):
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.update(changes)


backtest_job_manager = BacktestJobManager()

