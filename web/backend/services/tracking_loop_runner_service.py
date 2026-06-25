"""Post-close Tracking Loop Runner：编排收盘同步、规则评估、告警分发与运行记录。

本服务只做确定性后端编排，不接真实券商、不直接调用真实 LLM，也不绕过
TrackingAlertService 的 notifier 边界。真实钉钉 smoke 必须由独立任务执行。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from typing import Any, Callable

from web.backend.services.sqlite_service import get_connection


TRACKING_LOOP_STATUSES = {"running", "done", "partial", "error"}


def _json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _error_count(summary: Any) -> int:
    if not isinstance(summary, dict):
        return 0
    errors = summary.get("errors")
    if isinstance(errors, list):
        return len(errors)
    return 1 if errors else 0


class TrackingLoopRunnerService:
    """Tracking 收盘循环编排器。"""

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection] = get_connection,
        sync_service=None,
        evaluation_service=None,
        alert_service=None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if sync_service is None:
            from web.backend.services.tracking_sync_service import tracking_sync_service

            sync_service = tracking_sync_service
        if evaluation_service is None:
            from web.backend.services.tracking_evaluation_service import tracking_evaluation_service

            evaluation_service = tracking_evaluation_service
        if alert_service is None:
            from web.backend.services.tracking_alert_service import tracking_alert_service

            alert_service = tracking_alert_service

        self._conn_factory = connection_factory
        self.sync_service = sync_service
        self.evaluation_service = evaluation_service
        self.alert_service = alert_service
        self.clock = clock or datetime.now
        self._run_lock = threading.Lock()
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = self._conn_factory()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_loop_runs (
                run_id TEXT PRIMARY KEY,
                loop_type TEXT NOT NULL,
                eval_date TEXT,
                slot TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger TEXT NOT NULL,
                sync_first INTEGER NOT NULL,
                per_slot_limit INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                sync_json TEXT,
                evaluation_json TEXT,
                dispatch_json TEXT,
                error_json TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracking_loop_runs_type_started ON tracking_loop_runs(loop_type, started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracking_loop_runs_status ON tracking_loop_runs(status)")
        conn.commit()

    def run_post_close(
        self,
        eval_date=None,
        slot: str = "post_close",
        per_slot_limit: int = 8,
        sync_first: bool = True,
        trigger: str = "manual",
    ) -> dict:
        """执行一次收盘后 Tracking Loop；同进程已有运行时返回 busy。"""
        if not self._run_lock.acquire(blocking=False):
            return {"status": "busy", "loop_type": "post_close"}

        run_id = f"tlr_{uuid.uuid4().hex}"
        started_at = self._now_iso()
        completed_at = None
        sync_result = None
        evaluation_result = None
        dispatch_result = None
        error_result = None
        status = "running"
        normalized_limit = int(per_slot_limit)

        try:
            self._insert_run(
                run_id=run_id,
                loop_type="post_close",
                eval_date=eval_date,
                slot=slot,
                status=status,
                trigger=trigger,
                sync_first=sync_first,
                per_slot_limit=normalized_limit,
                started_at=started_at,
            )

            try:
                stage = "sync"
                if sync_first:
                    sync_result = self.sync_service.sync_and_evaluate(eval_date=eval_date)

                stage = "evaluation"
                evaluation_result = self.evaluation_service.evaluate_active_items(eval_date=eval_date)

                stage = "dispatch"
                dispatch_result = self.alert_service.dispatch_pending_alerts(slot, per_slot_limit=normalized_limit)

                error_result = self._summary_error(sync_result, evaluation_result)
                status = "partial" if error_result else "done"
            except Exception as exc:  # noqa: BLE001 - runner 边界必须持久化失败，避免后台异常静默丢失。
                status = "error"
                error_result = {
                    "stage": stage,
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }

            completed_at = self._now_iso()
            self._finish_run(
                run_id=run_id,
                status=status,
                completed_at=completed_at,
                sync_result=sync_result,
                evaluation_result=evaluation_result,
                dispatch_result=dispatch_result,
                error_result=error_result,
            )

            return {
                "run_id": run_id,
                "loop_type": "post_close",
                "eval_date": eval_date,
                "slot": slot,
                "status": status,
                "trigger": trigger,
                "sync_first": bool(sync_first),
                "per_slot_limit": normalized_limit,
                "started_at": started_at,
                "completed_at": completed_at,
                "sync": sync_result,
                "evaluation": evaluation_result,
                "dispatch": dispatch_result,
                "error": error_result,
            }
        finally:
            self._run_lock.release()

    def latest_run(self, loop_type: str = "post_close") -> dict | None:
        """读取最近一次 Tracking Loop 运行摘要。"""
        self._ensure_schema()
        row = self._conn_factory().execute(
            """
            SELECT *
              FROM tracking_loop_runs
             WHERE loop_type = ?
             ORDER BY started_at DESC, rowid DESC
             LIMIT 1
            """,
            (loop_type,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def _insert_run(
        self,
        *,
        run_id: str,
        loop_type: str,
        eval_date,
        slot: str,
        status: str,
        trigger: str,
        sync_first: bool,
        per_slot_limit: int,
        started_at: str,
    ) -> None:
        if status not in TRACKING_LOOP_STATUSES:
            raise ValueError(f"unsupported tracking loop status: {status}")
        conn = self._conn_factory()
        conn.execute(
            """
            INSERT INTO tracking_loop_runs (
                run_id, loop_type, eval_date, slot, status, trigger,
                sync_first, per_slot_limit, started_at, completed_at,
                sync_json, evaluation_json, dispatch_json, error_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL)
            """,
            (
                run_id,
                loop_type,
                eval_date,
                slot,
                status,
                trigger,
                1 if sync_first else 0,
                per_slot_limit,
                started_at,
            ),
        )
        conn.commit()

    def _finish_run(
        self,
        *,
        run_id: str,
        status: str,
        completed_at: str,
        sync_result,
        evaluation_result,
        dispatch_result,
        error_result,
    ) -> None:
        if status not in TRACKING_LOOP_STATUSES:
            raise ValueError(f"unsupported tracking loop status: {status}")
        conn = self._conn_factory()
        conn.execute(
            """
            UPDATE tracking_loop_runs
               SET status = ?,
                   completed_at = ?,
                   sync_json = ?,
                   evaluation_json = ?,
                   dispatch_json = ?,
                   error_json = ?
             WHERE run_id = ?
            """,
            (
                status,
                completed_at,
                _json_dumps(sync_result),
                _json_dumps(evaluation_result),
                _json_dumps(dispatch_result),
                _json_dumps(error_result),
                run_id,
            ),
        )
        conn.commit()

    def _summary_error(self, sync_result, evaluation_result) -> dict | None:
        sync_errors = _error_count(sync_result)
        evaluation_errors = _error_count(evaluation_result)
        if sync_errors == 0 and evaluation_errors == 0:
            return None
        return {
            "sync_errors": sync_errors,
            "evaluation_errors": evaluation_errors,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        item = dict(row)
        return {
            "run_id": item["run_id"],
            "loop_type": item["loop_type"],
            "eval_date": item.get("eval_date"),
            "slot": item["slot"],
            "status": item["status"],
            "trigger": item["trigger"],
            "sync_first": bool(item["sync_first"]),
            "per_slot_limit": int(item["per_slot_limit"]),
            "started_at": item["started_at"],
            "completed_at": item.get("completed_at"),
            "sync": _json_loads(item.get("sync_json")),
            "evaluation": _json_loads(item.get("evaluation_json")),
            "dispatch": _json_loads(item.get("dispatch_json")),
            "error": _json_loads(item.get("error_json")),
        }

    def _now_iso(self) -> str:
        return self.clock().isoformat(timespec="seconds")


tracking_loop_runner_service = TrackingLoopRunnerService(connection_factory=get_connection)
