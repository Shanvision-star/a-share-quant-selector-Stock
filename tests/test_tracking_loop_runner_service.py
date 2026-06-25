"""验证 Post-close Loop Runner 的编排、幂等记录和故障隔离。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from web.backend.services.tracking_loop_runner_service import TrackingLoopRunnerService


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class _SyncStub:
    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self.calls = []
        self.result = result or {
            "total_codes": 1,
            "updated": ["000001"],
            "skipped": [],
            "errors": [],
            "evaluation": {"total": 1},
        }
        self.exc = exc

    def sync_and_evaluate(self, eval_date=None):
        self.calls.append(eval_date)
        if self.exc:
            raise self.exc
        return self.result


class _EvaluationStub:
    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self.calls = []
        self.result = result or {
            "evaluated": 1,
            "alerts_created": 1,
            "alerts_skipped_dup": 0,
            "items_with_alerts": ["trk_1"],
            "errors": [],
        }
        self.exc = exc

    def evaluate_active_items(self, eval_date=None):
        self.calls.append(eval_date)
        if self.exc:
            raise self.exc
        return self.result


class _AlertStub:
    def __init__(self, result=None) -> None:
        self.calls = []
        self.result = result or {"dispatched": 1, "deferred": 0, "aggregated": 0}

    def dispatch_pending_alerts(self, slot, per_slot_limit=8):
        self.calls.append((slot, per_slot_limit))
        return self.result


def test_post_close_runner_records_done_run_and_calls_steps_in_order():
    conn = _memory_conn()
    sync = _SyncStub()
    evaluation = _EvaluationStub()
    alerts = _AlertStub()
    service = TrackingLoopRunnerService(
        connection_factory=lambda: conn,
        sync_service=sync,
        evaluation_service=evaluation,
        alert_service=alerts,
        clock=lambda: datetime(2026, 6, 25, 15, 31, 0),
    )

    result = service.run_post_close(eval_date="2026-06-25", slot="post_close", per_slot_limit=3, trigger="api")

    assert result["status"] == "done"
    assert result["loop_type"] == "post_close"
    assert result["eval_date"] == "2026-06-25"
    assert result["sync"]["updated"] == ["000001"]
    assert result["evaluation"]["alerts_created"] == 1
    assert result["dispatch"]["dispatched"] == 1
    assert sync.calls == ["2026-06-25"]
    assert evaluation.calls == ["2026-06-25"]
    assert alerts.calls == [("post_close", 3)]
    assert service.latest_run()["run_id"] == result["run_id"]


def test_post_close_runner_marks_partial_when_step_summaries_contain_errors():
    conn = _memory_conn()
    service = TrackingLoopRunnerService(
        connection_factory=lambda: conn,
        sync_service=_SyncStub(
            result={
                "total_codes": 1,
                "updated": [],
                "skipped": [],
                "errors": [{"code": "000001", "error": "fetch failed"}],
                "evaluation": {"total": 1},
            }
        ),
        evaluation_service=_EvaluationStub(
            result={
                "evaluated": 1,
                "alerts_created": 0,
                "alerts_skipped_dup": 0,
                "items_with_alerts": [],
                "errors": [{"tracking_id": "trk_1", "error": "bad frame"}],
            }
        ),
        alert_service=_AlertStub(result={"dispatched": 0, "deferred": 0, "aggregated": 0}),
        clock=lambda: datetime(2026, 6, 25, 15, 31, 0),
    )

    result = service.run_post_close(eval_date="2026-06-25")

    assert result["status"] == "partial"
    assert result["error"]["sync_errors"] == 1
    assert result["error"]["evaluation_errors"] == 1


def test_post_close_runner_records_error_and_skips_later_steps_on_top_level_failure():
    conn = _memory_conn()
    alerts = _AlertStub()
    service = TrackingLoopRunnerService(
        connection_factory=lambda: conn,
        sync_service=_SyncStub(exc=RuntimeError("sync exploded")),
        evaluation_service=_EvaluationStub(),
        alert_service=alerts,
        clock=lambda: datetime(2026, 6, 25, 15, 31, 0),
    )

    result = service.run_post_close(eval_date="2026-06-25")

    assert result["status"] == "error"
    assert "sync exploded" in result["error"]["message"]
    assert alerts.calls == []
    assert service.latest_run()["status"] == "error"


def test_post_close_runner_returns_busy_when_single_flight_lock_is_held():
    conn = _memory_conn()
    service = TrackingLoopRunnerService(
        connection_factory=lambda: conn,
        sync_service=_SyncStub(),
        evaluation_service=_EvaluationStub(),
        alert_service=_AlertStub(),
    )

    assert service._run_lock.acquire(blocking=False) is True
    try:
        result = service.run_post_close(eval_date="2026-06-25")
    finally:
        service._run_lock.release()

    assert result["status"] == "busy"
    assert service.latest_run() is None
