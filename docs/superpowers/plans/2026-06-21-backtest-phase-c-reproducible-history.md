# Backtest Phase C Reproducible History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make asynchronous backtest history reproducible and queryable without making the task list endpoint heavy.

**Architecture:** Reuse existing SQLite-backed `BacktestTaskRepository`. Add manifest/hash fields to `backtest_tasks`, keep full result only on detail reads, and expose events through an optional detail flag.

**Tech Stack:** Python, FastAPI, SQLite, pytest.

---

## File Map

- Modify `web/backend/services/backtest_job_service.py`: manifest helpers, schema columns, repository list/detail behavior.
- Modify `web/backend/services/sqlite_service.py`: app startup schema parity for new columns and indexes.
- Modify `web/backend/routers/backtest.py`: `include_events` query parameter.
- Modify `tests/test_backtest_job_service.py`: repository manifest and list/detail tests.
- Modify `tests/test_backtest_router_async.py`: API contract tests.
- Modify `docs/BACKTEST_OVERVIEW.md`: user-facing Phase C history behavior.

---

### Task 1: Repository Manifest And Lightweight History

**Files:**
- Modify: `web/backend/services/backtest_job_service.py`
- Modify: `tests/test_backtest_job_service.py`

- [ ] **Step 1: Write failing repository tests**

Add these tests to `tests/test_backtest_job_service.py`:

```python
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
```

```python
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
```

```python
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
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m pytest tests/test_backtest_job_service.py::test_backtest_repository_records_reproducible_manifest_hashes tests/test_backtest_job_service.py::test_backtest_repository_list_recent_omits_heavy_result_by_default tests/test_backtest_job_service.py::test_backtest_repository_detail_can_include_events -q
```

Expected: FAIL because manifest fields, summary and include_events are not implemented.

- [ ] **Step 3: Implement repository manifest**

In `web/backend/services/backtest_job_service.py`:

- Import `hashlib`.
- Add `BACKTEST_ENGINE_VERSION = "backtest-engine-v1-phase-c"`.
- Add `_stable_json(value)`, `_hash_json(value)`, `_summary_from_result(result)`.
- Extend schema with `request_hash`, `result_hash`, `engine_version`, `summary_json`.
- Add `_ensure_columns()` that checks `PRAGMA table_info(backtest_tasks)` and `ALTER TABLE` for missing columns.
- In `create()`, calculate request hash from params and write engine version.
- In `update()`, when `result` is present, calculate `result_hash` and `summary_json`.
- Change `get(self, task_id, include_events=False)` to pass flags into `_row_to_task`.
- Change `list_recent(self, limit=20, include_result=False)` to omit result by default.
- Change `_row_to_task(row, include_result=True, include_events=False)`.

- [ ] **Step 4: Run green tests**

Run:

```powershell
python -m pytest tests/test_backtest_job_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/backend/services/backtest_job_service.py tests/test_backtest_job_service.py
git commit -m "feat: add reproducible backtest task manifest"
```

---

### Task 2: Startup Schema And Router Detail Contract

**Files:**
- Modify: `web/backend/services/sqlite_service.py`
- Modify: `web/backend/routers/backtest.py`
- Modify: `tests/test_backtest_router_async.py`

- [ ] **Step 1: Write failing router tests**

Update `FakeBacktestJobManager` in `tests/test_backtest_router_async.py`:

- `get(self, task_id, include_events=False)` accepts the flag and includes events when true.
- `list_recent()` returns an item with `summary`, `request_hash`, `result_hash`, and `result=None`.

Add assertions:

```python
def test_list_backtest_tasks_returns_lightweight_history(monkeypatch):
    monkeypatch.setattr(backtest, "backtest_job_manager", FakeBacktestJobManager())

    response = _client().get("/api/backtest/tasks")

    body = response.json()
    item = body["data"]["items"][0]
    assert item["summary"]["trade_count"] == 1
    assert item["request_hash"] == "reqhash123456789"
    assert item["result"] is None
```

```python
def test_get_backtest_task_can_include_events(monkeypatch):
    monkeypatch.setattr(backtest, "backtest_job_manager", FakeBacktestJobManager())

    response = _client().get("/api/backtest/tasks/bt_test", params={"include_events": "true"})

    body = response.json()
    assert body["data"]["events"][0]["event_type"] == "progress"
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m pytest tests/test_backtest_router_async.py::test_list_backtest_tasks_returns_lightweight_history tests/test_backtest_router_async.py::test_get_backtest_task_can_include_events -q
```

Expected: FAIL until router forwards `include_events` and fake manager contract is updated.

- [ ] **Step 3: Implement router and startup schema**

In `web/backend/routers/backtest.py`:

```python
@router.get("/backtest/tasks/{task_id}")
async def get_backtest_task(task_id: str, include_events: bool = Query(default=False)):
    task = backtest_job_manager.get(task_id, include_events=include_events)
```

In `web/backend/services/sqlite_service.py`:

- Add new columns to `CREATE TABLE IF NOT EXISTS backtest_tasks`.
- After existing backtest indexes, use `PRAGMA table_info(backtest_tasks)` and `ALTER TABLE` for missing columns.
- Add indexes for `request_hash` and `finished_at`.

- [ ] **Step 4: Run green tests**

Run:

```powershell
python -m pytest tests/test_backtest_router_async.py tests/test_backtest_job_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/backend/services/sqlite_service.py web/backend/routers/backtest.py tests/test_backtest_router_async.py
git commit -m "feat: expose reproducible backtest task details"
```

---

### Task 3: Documentation And Regression Closeout

**Files:**
- Modify: `docs/BACKTEST_OVERVIEW.md`

- [ ] **Step 1: Update docs**

Add a short section:

```markdown
## 4. 可复现历史记录（Phase C）

异步回测任务会写入 SQLite `backtest_tasks` 和 `backtest_task_events`。任务创建时记录
`engine_version` 与稳定 `request_hash`；任务完成后记录 `result_hash` 和轻量 `summary`。
`GET /api/backtest/tasks` 默认返回轻量历史列表，不携带完整交易明细；`GET /api/backtest/tasks/{task_id}`
返回完整 result，附加 `include_events=true` 时同时返回事件流。同步 `/api/backtest` 保持兼容，不在本阶段写入历史任务。
```

- [ ] **Step 2: Run full focused regression**

Run:

```powershell
python -m pytest tests/test_trading_calendar.py tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check
```

Expected: all pass, import prints `import-ok`, diff check has no whitespace errors.

- [ ] **Step 3: Commit**

```powershell
git add docs/BACKTEST_OVERVIEW.md
git commit -m "docs: document reproducible backtest history"
```

---

## Final Review

After all tasks:

```powershell
python -m pytest tests/test_trading_calendar.py tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check 41d78cf..HEAD
git status --short --branch
```

Dispatch final code reviewer for `41d78cf..HEAD`.
