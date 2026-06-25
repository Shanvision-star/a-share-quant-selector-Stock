# Tracking Loop Operational Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface the latest Post-close Loop Runner status inside `/api/system/status` without triggering runner execution or real external integrations.

**Architecture:** Extend `SystemStatusService` with a read-only SQLite loader for `tracking_loop_runs`. Add the latest loop run and a compact status/message to `tracking.details`; keep tracking non-core so loop partial/error does not alter `overall_status`.

**Tech Stack:** Python 3, SQLite read-only queries, pytest, existing FastAPI status service patterns.

---

## Files

- Modify: `web/backend/services/system_status_service.py`
- Modify: `tests/test_system_status_service.py`
- Modify: `docs/TRACKING_AGENT.md`

No frontend or nested `web/frontend` files should change.

## Task 1: System Status Latest Loop Loader

**Files:**
- Modify: `tests/test_system_status_service.py`
- Modify: `web/backend/services/system_status_service.py`

- [ ] **Step 1: Write failing tests**

Update the test helper in `tests/test_system_status_service.py`:

```python
def build_service(
    *,
    data_status=None,
    strategy_status=None,
    runs=None,
    tracking_items=None,
    alerts=None,
    config=None,
    latest_loop_run=None,
):
    ...
    return SystemStatusService(
        ...
        tracking_loop_run_loader=lambda loop_type="post_close": latest_loop_run,
        config_loader=lambda: config,
    )
```

Add test for a successful latest loop:

```python
def test_system_status_tracking_includes_latest_post_close_loop_run():
    service = build_service(
        latest_loop_run={
            "run_id": "tlr_done",
            "loop_type": "post_close",
            "eval_date": "2026-06-25",
            "slot": "post_close",
            "status": "done",
            "trigger": "api",
            "sync_first": True,
            "per_slot_limit": 8,
            "started_at": "2026-06-25T15:31:00",
            "completed_at": "2026-06-25T15:31:02",
            "sync": {"updated": ["000001"]},
            "evaluation": {"alerts_created": 1},
            "dispatch": {"dispatched": 1},
            "error": None,
        }
    )

    payload = service.build_status()

    details = payload["tracking"]["details"]
    assert details["latest_loop_status"] == "done"
    assert details["latest_loop_message"] == "最近收盘循环完成。"
    assert details["latest_loop_run"]["run_id"] == "tlr_done"
    assert details["latest_loop_run"]["dispatch"]["dispatched"] == 1
```

Add test for partial/error visibility not blocking core readiness:

```python
def test_system_status_tracking_loop_partial_does_not_block_overall_ready():
    service = build_service(
        latest_loop_run={
            "run_id": "tlr_partial",
            "loop_type": "post_close",
            "eval_date": "2026-06-25",
            "slot": "post_close",
            "status": "partial",
            "trigger": "api",
            "sync_first": True,
            "per_slot_limit": 8,
            "started_at": "2026-06-25T15:31:00",
            "completed_at": "2026-06-25T15:31:02",
            "sync": {"errors": [{"code": "000001", "error": "fetch failed"}]},
            "evaluation": {"errors": []},
            "dispatch": {"dispatched": 0},
            "error": {"sync_errors": 1, "evaluation_errors": 0},
        }
    )

    payload = service.build_status()

    assert payload["overall_status"] == "ready"
    assert payload["tracking"]["status"] == "ready"
    assert payload["tracking"]["details"]["latest_loop_status"] == "partial"
    assert "部分完成" in payload["tracking"]["details"]["latest_loop_message"]
```

Add test for default read-only SQLite loader:

```python
def test_default_tracking_loop_loader_is_read_only(monkeypatch, tmp_path):
    db_path = tmp_path / "web_strategy_cache.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE tracking_loop_runs (
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
    conn.execute(
        """
        INSERT INTO tracking_loop_runs (
            run_id, loop_type, eval_date, slot, status, trigger,
            sync_first, per_slot_limit, started_at, completed_at,
            sync_json, evaluation_json, dispatch_json, error_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "tlr_latest",
            "post_close",
            "2026-06-25",
            "post_close",
            "done",
            "api",
            1,
            8,
            "2026-06-25T15:31:00",
            "2026-06-25T15:31:02",
            json.dumps({"updated": ["000001"]}, ensure_ascii=False),
            json.dumps({"alerts_created": 1}, ensure_ascii=False),
            json.dumps({"dispatched": 1}, ensure_ascii=False),
            None,
        ),
    )
    conn.commit()
    conn.close()

    class ForbiddenLoopService:
        def __init__(self, *args, **kwargs):
            raise AssertionError("system status must not construct TrackingLoopRunnerService")

    fake_loop_module = types.SimpleNamespace(
        TrackingLoopRunnerService=ForbiddenLoopService,
        tracking_loop_runner_service=types.SimpleNamespace(
            latest_run=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("system status must not call tracking_loop_runner_service.latest_run")
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "web.backend.services.tracking_loop_runner_service", fake_loop_module)
    monkeypatch.setattr(svc_mod, "WEB_STRATEGY_CACHE_DB_FILE", db_path)

    service = SystemStatusService(
        now_provider=lambda: NOW,
        data_status_loader=lambda: {
            "total_stocks": 5100,
            "latest_date": "2026-06-19",
            "stale_count": 0,
            "checked_count": 40,
            "is_fresh": True,
        },
        strategy_cache_loader=lambda: {
            "status": "ready",
            "requested_date": "2026-06-19",
            "trade_date": "2026-06-19",
            "is_latest": True,
            "total": 120,
            "unique_total": 98,
        },
        tracking_counts_loader=lambda status: 0,
        alerts_loader=lambda ui_status, limit=1000: [],
        config_loader=lambda: {},
    )

    payload = service.build_status()

    details = payload["tracking"]["details"]
    assert details["latest_loop_status"] == "done"
    assert details["latest_loop_run"]["run_id"] == "tlr_latest"
    assert details["latest_loop_run"]["sync"]["updated"] == ["000001"]
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m pytest tests/test_system_status_service.py::test_system_status_tracking_includes_latest_post_close_loop_run tests/test_system_status_service.py::test_system_status_tracking_loop_partial_does_not_block_overall_ready tests/test_system_status_service.py::test_default_tracking_loop_loader_is_read_only -q
```

Expected: fail because `SystemStatusService.__init__` does not accept `tracking_loop_run_loader` and `tracking.details` has no latest loop fields.

- [ ] **Step 3: Implement read-only loader and details fields**

In `web/backend/services/system_status_service.py` add:

```python
def _safe_json_loads(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None
```

Add default loader:

```python
def _default_tracking_loop_run_loader(loop_type: str = "post_close") -> dict | None:
    rows = _read_only_db_rows(
        """
        SELECT *
        FROM tracking_loop_runs
        WHERE loop_type = ?
        ORDER BY started_at DESC, rowid DESC
        LIMIT 1
        """,
        (loop_type,),
    )
    if not rows:
        return None
    row = rows[0]
    return {
        "run_id": row.get("run_id"),
        "loop_type": row.get("loop_type"),
        "eval_date": row.get("eval_date"),
        "slot": row.get("slot"),
        "status": row.get("status"),
        "trigger": row.get("trigger"),
        "sync_first": bool(row.get("sync_first")),
        "per_slot_limit": int(row.get("per_slot_limit") or 0),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "sync": _safe_json_loads(row.get("sync_json")),
        "evaluation": _safe_json_loads(row.get("evaluation_json")),
        "dispatch": _safe_json_loads(row.get("dispatch_json")),
        "error": _safe_json_loads(row.get("error_json")),
    }
```

Extend `SystemStatusService.__init__` with:

```python
tracking_loop_run_loader: Callable[[str], dict | None] = _default_tracking_loop_run_loader,
```

and assign `self.tracking_loop_run_loader`.

Add helper:

```python
def _tracking_loop_message(self, latest_run: dict | None) -> tuple[str, str]:
    if not latest_run:
        return "missing", "尚未执行过收盘循环。"
    status = str(latest_run.get("status") or "missing")
    if status == "done":
        return status, "最近收盘循环完成。"
    if status == "partial":
        return status, "最近收盘循环部分完成，请查看 sync/evaluation error 摘要。"
    if status == "error":
        return status, "最近收盘循环失败，请查看 error.stage/message。"
    if status == "running":
        return status, "收盘循环正在运行。"
    return status, f"最近收盘循环状态: {status}"
```

In `_tracking_block()` call:

```python
latest_loop_run = self.tracking_loop_run_loader("post_close")
latest_loop_status, latest_loop_message = self._tracking_loop_message(latest_loop_run)
```

Add these keys to `details`:

```python
"latest_loop_run": latest_loop_run,
"latest_loop_status": latest_loop_status,
"latest_loop_message": latest_loop_message,
```

- [ ] **Step 4: Run green tests**

Run:

```powershell
python -m pytest tests/test_system_status_service.py -q
```

Expected: all system status tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add web/backend/services/system_status_service.py tests/test_system_status_service.py
git commit -m "feat: surface tracking loop status"
```

## Task 2: Documentation And Focused Regression

**Files:**
- Modify: `docs/TRACKING_AGENT.md`

- [ ] **Step 1: Update documentation**

Add a short note under the System Status or Post-close Loop Runner section:

```markdown
- `/api/system/status` 的 `tracking.details.latest_loop_run` 只读展示最近一次 `tracking_loop_runs`，不会触发 runner。
- `latest_loop_status=partial|error` 只提示 Tracking 运维风险，不改变 data/strategy 的 overall_status。
```

- [ ] **Step 2: Run focused regression**

Run:

```powershell
python -m pytest tests/test_system_status_service.py tests/test_tracking_loop_runner_service.py tests/test_tracking_loop_router.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check
```

Expected: pytest passes, import prints `import-ok`, diff check has no output.

- [ ] **Step 3: Commit Task 2**

```powershell
git add docs/TRACKING_AGENT.md
git commit -m "docs: document tracking loop status visibility"
```

## Final Review

- [ ] Run final verification:

```powershell
python -m pytest tests/test_system_status_service.py tests/test_tracking_loop_runner_service.py tests/test_tracking_loop_router.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check
```

- [ ] Review that no frontend files changed.
- [ ] Review that system status uses read-only SQLite and does not import `tracking_loop_runner_service`.
