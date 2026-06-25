# Post-close Loop Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend Post-close Loop Runner that orchestrates tracking sync, rule evaluation, alert dispatch, and run persistence without enabling real trading or real notifier smoke by default.

**Architecture:** Add a focused runner service with dependency injection and a lightweight `tracking_loop_runs` table created by the service. Add a fixed-prefix FastAPI router under `/api/tracking/loops` and register it before the generic tracking router. Keep existing sync, evaluation, and alert services authoritative; the runner only sequences them and records summaries.

**Tech Stack:** Python 3, FastAPI, SQLite, pytest, existing `web/backend/services/*` patterns.

---

## Files

- Create: `web/backend/services/tracking_loop_runner_service.py`
- Create: `web/backend/routers/tracking_loop.py`
- Create: `tests/test_tracking_loop_runner_service.py`
- Create: `tests/test_tracking_loop_router.py`
- Modify: `tests/test_tracking_route_order.py`
- Modify: `web/backend/main.py`
- Modify: `docs/TRACKING_AGENT.md`

No frontend files should change in this P0 slice.

## Task 1: Runner Service

**Files:**
- Create: `tests/test_tracking_loop_runner_service.py`
- Create: `web/backend/services/tracking_loop_runner_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_tracking_loop_runner_service.py` with these behaviors:

```python
"""验证 Post-close Loop Runner 的编排、幂等记录和故障隔离。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

from web.backend.services.tracking_loop_runner_service import TrackingLoopRunnerService


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class _SyncStub:
    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self.calls = []
        self.result = result or {"total_codes": 1, "updated": ["000001"], "skipped": [], "errors": [], "evaluation": {"total": 1}}
        self.exc = exc

    def sync_and_evaluate(self, eval_date=None):
        self.calls.append(eval_date)
        if self.exc:
            raise self.exc
        return self.result


class _EvaluationStub:
    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self.calls = []
        self.result = result or {"evaluated": 1, "alerts_created": 1, "alerts_skipped_dup": 0, "items_with_alerts": ["trk_1"], "errors": []}
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
```

Add tests:

```python
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
        sync_service=_SyncStub(result={"total_codes": 1, "updated": [], "skipped": [], "errors": [{"code": "000001", "error": "fetch failed"}], "evaluation": {"total": 1}}),
        evaluation_service=_EvaluationStub(result={"evaluated": 1, "alerts_created": 0, "alerts_skipped_dup": 0, "items_with_alerts": [], "errors": [{"tracking_id": "trk_1", "error": "bad frame"}]}),
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
```

For the busy case, hold the lock directly to simulate another in-process runner:

```python
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
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m pytest tests/test_tracking_loop_runner_service.py -q
```

Expected: fail with `ModuleNotFoundError` or missing `tracking_loop_runner_service`.

- [ ] **Step 3: Implement runner service**

Create `web/backend/services/tracking_loop_runner_service.py`:

```python
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
from typing import Any, Callable, Optional

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
```

Add methods `_ensure_schema()`, `run_post_close()`, `latest_run()`, `_insert_run()`, `_finish_run()`, `_row_to_dict()`. Keep the public result keys:

```python
{
    "run_id": run_id,
    "loop_type": "post_close",
    "eval_date": eval_date,
    "slot": slot,
    "status": status,
    "trigger": trigger,
    "sync_first": sync_first,
    "per_slot_limit": per_slot_limit,
    "started_at": started_at,
    "completed_at": completed_at,
    "sync": sync_result,
    "evaluation": evaluation_result,
    "dispatch": dispatch_result,
    "error": error_result,
}
```

The implementation must:

- acquire `_run_lock` with `blocking=False`
- return `{"status": "busy", "loop_type": "post_close"}` without writing a row when busy
- insert `running` row before calling dependencies
- call sync only when `sync_first=True`
- skip evaluation and dispatch when sync raises a top-level exception
- set `partial` when sync/evaluation summaries contain non-empty `errors`
- update the row with JSON summaries and completed timestamp

Create module singleton:

```python
tracking_loop_runner_service = TrackingLoopRunnerService(connection_factory=get_connection)
```

- [ ] **Step 4: Run green service tests**

Run:

```powershell
python -m pytest tests/test_tracking_loop_runner_service.py -q
```

Expected: all service tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add web/backend/services/tracking_loop_runner_service.py tests/test_tracking_loop_runner_service.py
git commit -m "feat: add post-close tracking loop runner"
```

## Task 2: Router And App Registration

**Files:**
- Create: `tests/test_tracking_loop_router.py`
- Create: `web/backend/routers/tracking_loop.py`
- Modify: `tests/test_tracking_route_order.py`
- Modify: `web/backend/main.py`

- [ ] **Step 1: Write failing router tests**

Create `tests/test_tracking_loop_router.py`:

```python
"""验证 Post-close Loop Runner 路由。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.routers import tracking_loop as router_module


class _RunnerStub:
    def __init__(self) -> None:
        self.calls = []

    def run_post_close(self, **kwargs):
        self.calls.append(kwargs)
        return {"run_id": "tlr_test", "loop_type": "post_close", "status": "done", **kwargs}

    def latest_run(self, loop_type="post_close"):
        return {"run_id": "tlr_latest", "loop_type": loop_type, "status": "done"}


def _client(runner: _RunnerStub) -> TestClient:
    app = FastAPI()
    router_module.tracking_loop_runner_service = runner
    app.include_router(router_module.router)
    return TestClient(app)


def test_post_close_run_endpoint_calls_runner_with_payload():
    runner = _RunnerStub()
    client = _client(runner)

    resp = client.post(
        "/api/tracking/loops/post-close/run",
        json={"eval_date": "2026-06-25", "slot": "post_close", "per_slot_limit": 3, "sync_first": False, "trigger": "api"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "done"
    assert runner.calls == [
        {"eval_date": "2026-06-25", "slot": "post_close", "per_slot_limit": 3, "sync_first": False, "trigger": "api"}
    ]


def test_latest_run_endpoint_returns_runner_payload():
    runner = _RunnerStub()
    client = _client(runner)

    resp = client.get("/api/tracking/loops/runs/latest")

    assert resp.status_code == 200
    assert resp.json()["data"]["run_id"] == "tlr_latest"
```

Modify `tests/test_tracking_route_order.py` to include:

```python
"/api/tracking/loops/post-close/run",
```

in the fixed route list that must not be swallowed by `/api/tracking/{tracking_id}`.

- [ ] **Step 2: Run red router tests**

Run:

```powershell
python -m pytest tests/test_tracking_loop_router.py tests/test_tracking_route_order.py -q
```

Expected: fail because `tracking_loop` router does not exist and route order is missing.

- [ ] **Step 3: Implement router and app registration**

Create `web/backend/routers/tracking_loop.py`:

```python
"""Post-close Loop Runner REST 接口。"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from web.backend.services.tracking_loop_runner_service import tracking_loop_runner_service


router = APIRouter(prefix="/api/tracking/loops", tags=["跟踪循环"])


class PostCloseRunRequest(BaseModel):
    eval_date: Optional[str] = None
    slot: str = "post_close"
    per_slot_limit: int = Field(default=8, ge=1, le=100)
    sync_first: bool = True
    trigger: Literal["manual", "cron", "api"] = "api"


@router.post("/post-close/run")
async def run_post_close_loop(payload: Optional[PostCloseRunRequest] = None):
    """触发一次收盘后 Tracking Loop；busy 作为幂等状态返回。"""
    payload = payload or PostCloseRunRequest()
    result = tracking_loop_runner_service.run_post_close(
        eval_date=payload.eval_date,
        slot=payload.slot,
        per_slot_limit=payload.per_slot_limit,
        sync_first=payload.sync_first,
        trigger=payload.trigger,
    )
    return {"success": True, "data": result}


@router.get("/runs/latest")
async def latest_loop_run(loop_type: str = Query(default="post_close")):
    """读取最近一次 Tracking Loop 运行摘要。"""
    return {"success": True, "data": tracking_loop_runner_service.latest_run(loop_type=loop_type)}
```

Modify `web/backend/main.py`:

- import `tracking_loop`
- include `app.include_router(tracking_loop.router)` before `tracking.router`

- [ ] **Step 4: Run green router tests**

Run:

```powershell
python -m pytest tests/test_tracking_loop_router.py tests/test_tracking_route_order.py -q
```

Expected: all router/order tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add web/backend/routers/tracking_loop.py web/backend/main.py tests/test_tracking_loop_router.py tests/test_tracking_route_order.py
git commit -m "feat: expose post-close tracking loop api"
```

## Task 3: Documentation And Regression Closeout

**Files:**
- Modify: `docs/TRACKING_AGENT.md`

- [ ] **Step 1: Update tracking documentation**

In `docs/TRACKING_AGENT.md`, update the Post-close Loop Runner note from a future task to a landed P0 endpoint summary. Include:

```markdown
### Post-close Loop Runner

- `POST /api/tracking/loops/post-close/run` 编排 sync-close、evaluate-rules 和 alerts dispatch。
- 默认 `sync_first=true`、`slot=post_close`、`per_slot_limit=8`。
- Runner 写入 `tracking_loop_runs`，状态为 `done|partial|error`；同进程已有运行时返回 `busy`。
- 缺省 notifier 仍为空实现；真实钉钉 smoke 必须单独执行。
```

- [ ] **Step 2: Run focused backend regression**

Run:

```powershell
python -m pytest tests/test_tracking_loop_runner_service.py tests/test_tracking_loop_router.py tests/test_tracking_route_order.py -q
python -m pytest tests/test_tracking_loop_contract.py tests/test_tracking_alert_service.py tests/test_tracking_alert_router.py tests/test_tracking_evaluation_service.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check HEAD~2..HEAD
```

Expected: all pytest commands pass, import prints `import-ok`, diff check has no output.

- [ ] **Step 3: Commit Task 3**

```powershell
git add docs/TRACKING_AGENT.md
git commit -m "docs: document post-close tracking loop runner"
```

## Final Review

- [ ] Run the full focused verification block:

```powershell
python -m pytest tests/test_tracking_loop_runner_service.py tests/test_tracking_loop_router.py tests/test_tracking_route_order.py tests/test_tracking_loop_contract.py tests/test_tracking_alert_service.py tests/test_tracking_alert_router.py tests/test_tracking_evaluation_service.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check
```

- [ ] Request spec-compliance and code-quality review for commits after `aa9c75e`.
- [ ] Do not merge until Critical/Important review issues are resolved.
