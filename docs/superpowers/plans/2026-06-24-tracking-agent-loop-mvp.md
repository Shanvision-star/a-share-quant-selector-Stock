# Tracking Agent Loop MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the approved Tracking Agent Loop MVP spec into a usable, auditable loop from selected stocks to alerts, Zettaranc-aware advice, and manually confirmed `OrderIntent` actions.

**Architecture:** Reuse the existing tracking services and Vue tracking page. The backend remains rule-authoritative: rules create alerts, advice explains alerts, and `OrderIntent` remains manual-confirm only. The frontend closes the operator loop by exposing alert status actions, advice profile/data-source state, and the correct suggested intent.

**Tech Stack:** FastAPI, SQLite, pytest, Vue 3, TypeScript, Element Plus, Vitest.

---

## Agentic Loop Prompt

Use this prompt for every implementation subagent:

```text
You are implementing one task from docs/superpowers/plans/2026-06-24-tracking-agent-loop-mvp.md.

Loop until the task is genuinely complete:
1. Read the task text, the approved spec, agent.md, and only the files named by the task.
2. Classify the gap as code, documentation, verification, or product-boundary.
3. Write the smallest failing test that proves the gap.
4. Run the focused test and confirm it fails for the expected reason.
5. Implement the smallest change that passes the test.
6. Run the focused test.
7. Run the task-level regression command.
8. Self-review for spec compliance, no automatic trading, no Zettaranc authority override, no unrelated edits.
9. Commit only the files listed in the task.
10. Report DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED with exact commands run.
```

Controller review loop after each task:

```text
1. Spec reviewer checks the task against docs/superpowers/specs/2026-06-24-tracking-agent-loop-design.md.
2. Code-quality reviewer checks maintainability, minimal diff, tests, and project conventions.
3. If either reviewer finds issues, send the same task back for fixes and re-review.
4. Mark the task complete only after both reviews pass.
```

## Scope Map

**Existing foundation:**

- `web/backend/services/tracking_service.py` already owns tracking items, events, and intent confirmation/rejection.
- `web/backend/services/tracking_rule_engine.py` already evaluates rule hits as pure functions.
- `web/backend/services/tracking_evaluation_service.py` already batch-evaluates active items and persists alerts.
- `web/backend/services/tracking_alert_service.py` already persists, lists, deduplicates, and dispatches alerts.
- `web/backend/services/tracking_llm_service.py` already supports `default` and `zettaranc_style` profiles.
- `web/frontend/src/views/TrackingView.vue` already exposes tracking operations, alerts, advice, and intent buttons.

**Actual MVP gaps:**

- Alerts cannot yet be acknowledged or ignored through stable backend APIs.
- Frontend API types do not expose advice/profile/data-source fields strongly enough.
- `TrackingView.vue` confirms `state.advice?.intent`, but backend advice returns `suggested_intent`.
- Zettaranc profile and data-source state are hidden inside raw JSON instead of visible operator state.
- The loop lacks a focused end-to-end API regression proving evaluate -> alert -> advice -> intent -> confirm/reject.
- System status should expose richer alert status counts without creating service side effects.

---

### Task 1: Alert Status Actions

**Files:**
- Modify: `web/backend/services/tracking_alert_service.py`
- Modify: `web/backend/routers/tracking_alert.py`
- Modify: `tests/test_tracking_alert_service.py`
- Modify: `tests/test_tracking_alert_router.py`

- [ ] **Step 1: Add failing service tests for acknowledge and ignore**

Append these tests to `tests/test_tracking_alert_service.py`:

```python
def test_update_alert_status_acknowledges_existing_alert(service: TrackingAlertService) -> None:
    service.persist_alerts([
        _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10),
    ])
    alert = service.list_alerts()[0]

    updated = service.update_alert_status(alert["alert_id"], "acknowledged")

    assert updated["alert_id"] == alert["alert_id"]
    assert updated["ui_status"] == "acknowledged"
    assert service.list_alerts(ui_status="pending") == []


def test_update_alert_status_rejects_invalid_status(service: TrackingAlertService) -> None:
    service.persist_alerts([
        _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10),
    ])
    alert = service.list_alerts()[0]

    with pytest.raises(ValueError, match="unsupported alert status"):
        service.update_alert_status(alert["alert_id"], "sent")
```

- [ ] **Step 2: Run service tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_tracking_alert_service.py::test_update_alert_status_acknowledges_existing_alert tests/test_tracking_alert_service.py::test_update_alert_status_rejects_invalid_status -q
```

Expected: fail because `TrackingAlertService.update_alert_status` does not exist.

- [ ] **Step 3: Implement alert status update**

In `web/backend/services/tracking_alert_service.py`, add constants near `DEFAULT_PER_SLOT_LIMIT`:

```python
ALERT_UI_STATUSES = {
    "pending",
    "dispatched",
    "aggregated",
    "acknowledged",
    "ignored",
}
```

Add this method to `TrackingAlertService`:

```python
    def update_alert_status(self, alert_id: int, ui_status: str) -> dict:
        """更新前端处理状态；只允许显式枚举，避免把发送状态和用户处理状态混写。"""
        normalized = str(ui_status or "").strip().lower()
        if normalized not in ALERT_UI_STATUSES:
            raise ValueError(f"unsupported alert status: {ui_status}")
        conn = self._conn_factory()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM tracking_alert_events WHERE alert_id = ?",
                (int(alert_id),),
            ).fetchone()
            if row is None:
                raise KeyError(alert_id)
            conn.execute(
                """
                UPDATE tracking_alert_events
                   SET ui_status = ?
                 WHERE alert_id = ?
                """,
                (normalized, int(alert_id)),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM tracking_alert_events WHERE alert_id = ?",
                (int(alert_id),),
            ).fetchone()
        return self._row_to_dict(updated)
```

- [ ] **Step 4: Run service tests to verify pass**

Run:

```powershell
python -m pytest tests/test_tracking_alert_service.py::test_update_alert_status_acknowledges_existing_alert tests/test_tracking_alert_service.py::test_update_alert_status_rejects_invalid_status -q
```

Expected: 2 passed.

- [ ] **Step 5: Add failing router tests for ack and ignore**

Append these tests to `tests/test_tracking_alert_router.py`:

```python
def test_ack_alert_endpoint_marks_alert_acknowledged(env) -> None:
    client, svc, _ = env
    _seed(svc)
    alert_id = svc.list_alerts(tracking_id="t1")[0]["alert_id"]

    resp = client.post(f"/api/tracking/alerts/{alert_id}/ack")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["ui_status"] == "acknowledged"


def test_ignore_alert_endpoint_marks_alert_ignored(env) -> None:
    client, svc, _ = env
    _seed(svc)
    alert_id = svc.list_alerts(tracking_id="t1")[0]["alert_id"]

    resp = client.post(f"/api/tracking/alerts/{alert_id}/ignore")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["ui_status"] == "ignored"


def test_ack_alert_endpoint_returns_404_for_unknown(env) -> None:
    client, _, _ = env

    resp = client.post("/api/tracking/alerts/999999/ack")

    assert resp.status_code == 404
```

- [ ] **Step 6: Run router tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_tracking_alert_router.py::test_ack_alert_endpoint_marks_alert_acknowledged tests/test_tracking_alert_router.py::test_ignore_alert_endpoint_marks_alert_ignored tests/test_tracking_alert_router.py::test_ack_alert_endpoint_returns_404_for_unknown -q
```

Expected: fail with 404 because endpoints are not registered.

- [ ] **Step 7: Implement router endpoints**

In `web/backend/routers/tracking_alert.py`, change imports:

```python
from fastapi import APIRouter, HTTPException, Query
```

Append below `dispatch_alerts`:

```python
@router.post("/{alert_id}/ack")
async def acknowledge_alert(alert_id: int):
    """标记告警已确认；只改变 UI 处理状态，不触发交易动作。"""
    try:
        item = tracking_alert_service.update_alert_status(alert_id, "acknowledged")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"alert_id 不存在: {alert_id}") from exc
    return {"success": True, "data": item}


@router.post("/{alert_id}/ignore")
async def ignore_alert(alert_id: int):
    """标记告警已忽略；保留事件证据，避免用户操作抹掉历史。"""
    try:
        item = tracking_alert_service.update_alert_status(alert_id, "ignored")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"alert_id 不存在: {alert_id}") from exc
    return {"success": True, "data": item}
```

- [ ] **Step 8: Run task regression**

Run:

```powershell
python -m pytest tests/test_tracking_alert_service.py tests/test_tracking_alert_router.py -q
python -c "from web.backend.main import app; print('import-ok')"
```

Expected: all alert tests pass and import prints `import-ok`.

- [ ] **Step 9: Commit Task 1**

Run:

```powershell
git add web/backend/services/tracking_alert_service.py web/backend/routers/tracking_alert.py tests/test_tracking_alert_service.py tests/test_tracking_alert_router.py
git commit -m "feat: add tracking alert status actions"
```

---

### Task 2: Advice And Intent Loop Contract

**Files:**
- Modify: `tests/test_tracking_llm_router.py`
- Modify: `tests/test_tracking_intent_actions.py`
- Modify: `web/backend/services/tracking_service.py`
- Modify: `web/backend/routers/tracking_llm.py`

- [ ] **Step 1: Add failing router test proving `zettaranc_style` passes through visible state**

Append to `tests/test_tracking_llm_router.py`:

```python
def test_llm_advice_endpoint_preserves_zettaranc_profile_and_data_source(client) -> None:
    resp = client.post(
        "/api/tracking/T-known/llm-advice",
        json={"profile": "zettaranc_style"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["profile"] == "zettaranc_style"
```

Then update `_StubLLM.propose_action` in the same test file to include realistic fields:

```python
                "suggested_intent": {"code": item["code"], "side": "SELL", "qty_hint": 100, "reason": "test"},
                "provider": "mock",
                "provider_fallback": False,
                "profile": profile or "default",
                "zettaranc_data_source": "local_csv" if profile == "zettaranc_style" else None,
```

Expected behavior after implementation: the endpoint returns these fields without dropping them.

- [ ] **Step 2: Run router test to verify current behavior**

Run:

```powershell
python -m pytest tests/test_tracking_llm_router.py::test_llm_advice_endpoint_preserves_zettaranc_profile_and_data_source -q
```

Expected: pass if pass-through already works. If it fails, fix only the route pass-through and no other behavior.

- [ ] **Step 3: Add failing service test for suggested intent confirmation audit**

Append to `tests/test_tracking_intent_actions.py`:

```python
def test_confirm_intent_accepts_suggested_intent_shape() -> None:
    conn = _memory_connection()
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_loader)
    item = service.create_item(
        {
            "code": "000559",
            "name": "万向钱潮",
            "strategy_name": "manual",
            "source": "manual",
            "source_date": "2026-05-01",
            "signal_date": "2026-04-30",
        }
    )
    suggested = {"code": "000559", "side": "SELL", "qty_hint": 100, "reason": "rule_break"}

    updated = service.confirm_intent(item["tracking_id"], suggested)
    events = service.list_events(item["tracking_id"])

    assert updated["latest_intent"] == suggested
    assert events[-1]["event_type"] == "intent_confirmed"
    assert events[-1]["payload"]["intent"] == suggested
```

- [ ] **Step 4: Run focused service test**

Run:

```powershell
python -m pytest tests/test_tracking_intent_actions.py::test_confirm_intent_accepts_suggested_intent_shape -q
```

Expected: pass if current service already supports suggested-intent shape. If it fails, update `TrackingService.confirm_intent()` so explicit `intent` dictionaries are stored unchanged in `latest_intent_json` and written unchanged to `tracking_events.payload_json`.

- [ ] **Step 5: Add explicit LLM route schema guard**

In `web/backend/routers/tracking_llm.py`, keep `profile` pass-through and add a small response normalization after advice generation:

```python
    advice.setdefault("provider", "mock")
    advice.setdefault("provider_fallback", False)
    advice.setdefault("profile", profile or "default")
    advice["tracking_id"] = tracking_id
```

Do not change `suggested_intent` into `intent`; the frontend must consume `suggested_intent`.

- [ ] **Step 6: Run task regression**

Run:

```powershell
python -m pytest tests/test_tracking_llm_service.py tests/test_tracking_llm_profile.py tests/test_tracking_llm_router.py tests/test_tracking_intent_actions.py tests/test_tracking_intent_router.py -q
python -c "from web.backend.main import app; print('import-ok')"
```

Expected: all listed tests pass and import prints `import-ok`.

- [ ] **Step 7: Commit Task 2**

Run:

```powershell
git add web/backend/services/tracking_service.py web/backend/routers/tracking_llm.py tests/test_tracking_llm_router.py tests/test_tracking_intent_actions.py
git commit -m "feat: harden tracking advice intent contract"
```

---

### Task 3: Frontend Tracking Loop UX

**Files:**
- Modify: `web/frontend/src/api/index.ts`
- Modify: `web/frontend/src/api/__tests__/trackingApi.spec.ts`
- Modify: `web/frontend/src/views/TrackingView.vue`

- [ ] **Step 1: Add failing API tests for alert actions and LLM profile**

Append these tests inside `describe('tracking API', ...)` in `web/frontend/src/api/__tests__/trackingApi.spec.ts`:

```ts
  it('marks tracking alerts acknowledged and ignored', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: {} } } as any)

    await acknowledgeTrackingAlert(12)
    await ignoreTrackingAlert(13)

    expect(postSpy).toHaveBeenCalledWith('/tracking/alerts/12/ack')
    expect(postSpy).toHaveBeenCalledWith('/tracking/alerts/13/ignore')
  })

  it('requests zettaranc profile advice', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({ data: { success: true, data: {} } } as any)

    await getTrackingLLMAdvice('trk_test', 'zettaranc_style')

    expect(postSpy).toHaveBeenCalledWith(
      '/tracking/trk_test/llm-advice',
      { profile: 'zettaranc_style' },
    )
  })
```

Update the import list at the top of the file:

```ts
  acknowledgeTrackingAlert,
  ignoreTrackingAlert,
  getTrackingLLMAdvice,
```

- [ ] **Step 2: Run API tests to verify they fail**

Run in `web/frontend`:

```powershell
npm run test -- src/api/__tests__/trackingApi.spec.ts
```

Expected: fail because `acknowledgeTrackingAlert` and `ignoreTrackingAlert` are not exported.

- [ ] **Step 3: Implement frontend API functions and stronger types**

In `web/frontend/src/api/index.ts`, update `TrackingAlertItem`:

```ts
export interface TrackingAlertItem {
  alert_id?: number
  tracking_id: string
  code?: string
  name?: string
  eval_date?: string
  priority?: number
  rule_id?: string
  message?: string
  ui_status?: string
  action_label?: string
  category?: string
  evidence?: Record<string, any> | null
  evidence_json?: string
}
```

Add:

```ts
export const acknowledgeTrackingAlert = (alertId: number) =>
  api.post(`/tracking/alerts/${encodeURIComponent(String(alertId))}/ack`)

export const ignoreTrackingAlert = (alertId: number) =>
  api.post(`/tracking/alerts/${encodeURIComponent(String(alertId))}/ignore`)

export interface TrackingAdvice {
  tracking_id?: string
  decision: string
  confidence: number
  rationale: string
  suggested_action: string
  suggested_intent?: Record<string, any>
  provider?: string
  provider_fallback?: boolean
  provider_error?: string
  profile?: LlmProfile | string
  zettaranc_data_source?: string
  alerts_summary?: Record<string, any>
  analysis?: Record<string, string[]>
}
```

Keep `getTrackingLLMAdvice()` unchanged except for return type if useful:

```ts
export const getTrackingLLMAdvice = (trackingId: string, profile?: LlmProfile) =>
  api.post<{ success: boolean; data: TrackingAdvice }>(
    `/tracking/${encodeURIComponent(trackingId)}/llm-advice`,
    profile ? { profile } : {},
  )
```

- [ ] **Step 4: Run API tests to verify pass**

Run:

```powershell
npm run test -- src/api/__tests__/trackingApi.spec.ts
```

Expected: tracking API tests pass.

- [ ] **Step 5: Update TrackingView intent and alert handling**

In `web/frontend/src/views/TrackingView.vue`, update imports:

```ts
  acknowledgeTrackingAlert,
  ignoreTrackingAlert,
  type TrackingAdvice,
```

Change `RowState`:

```ts
interface RowState {
  alerts: TrackingAlertItem[]
  advice: TrackingAdvice | null
  alertsLoading: boolean
  adviceLoading: boolean
  actionLoading: boolean
  profile: 'default' | 'zettaranc_style'
}
```

Add alert actions:

```ts
async function markAlert(row: TrackingItem, alert: TrackingAlertItem, action: 'ack' | 'ignore') {
  if (!alert.alert_id) return
  const state = ensureRowState(row.tracking_id)
  state.actionLoading = true
  try {
    if (action === 'ack') {
      await acknowledgeTrackingAlert(alert.alert_id)
      ElMessage.success('已确认告警')
    } else {
      await ignoreTrackingAlert(alert.alert_id)
      ElMessage.success('已忽略告警')
    }
    const resp = await listTrackingAlerts({ tracking_id: row.tracking_id, limit: 50 })
    state.alerts = resp.data?.data?.items ?? []
  } catch (e: any) {
    ElMessage.error(`更新告警状态失败：${e?.message || e}`)
  } finally {
    state.actionLoading = false
  }
}
```

Fix `confirmIntent`:

```ts
  const intent = state.advice?.suggested_intent ?? row.latest_intent ?? null
```

Add visible advice badges near the advice JSON block:

```vue
<div v-if="rowStateMap[row.tracking_id]?.advice" class="advice-meta">
  <el-tag size="small">{{ rowStateMap[row.tracking_id]!.advice?.profile || 'default' }}</el-tag>
  <el-tag
    v-if="rowStateMap[row.tracking_id]!.advice?.provider_fallback"
    type="warning"
    size="small"
  >
    provider fallback
  </el-tag>
  <el-tag
    v-if="rowStateMap[row.tracking_id]!.advice?.zettaranc_data_source"
    type="info"
    size="small"
  >
    Zettaranc: {{ rowStateMap[row.tracking_id]!.advice?.zettaranc_data_source }}
  </el-tag>
</div>
```

Add alert row action buttons inside the alert table:

```vue
<el-table-column label="处理" width="150">
  <template #default="{ row: a }">
    <el-button size="small" link type="primary" @click="markAlert(row, a, 'ack')">
      已确认
    </el-button>
    <el-button size="small" link type="info" @click="markAlert(row, a, 'ignore')">
      忽略
    </el-button>
  </template>
</el-table-column>
```

Add styles:

```css
.advice-meta {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}
```

- [ ] **Step 6: Run frontend regression**

Run in `web/frontend`:

```powershell
npm run test -- src/api/__tests__/trackingApi.spec.ts
npm run build
```

Expected: tests pass; build passes. If Vite only reports chunk-size warnings, record them as warnings, not failures.

- [ ] **Step 7: Commit Task 3 in nested frontend repo first**

Run in `web/frontend`:

```powershell
git status --short
git add src/api/index.ts src/api/__tests__/trackingApi.spec.ts src/views/TrackingView.vue
git commit -m "feat: close tracking alert action loop"
```

Then run in top-level repo:

```powershell
git add web/frontend
git commit -m "feat: update frontend tracking loop"
```

---

### Task 4: System Status And End-To-End Loop Regression

**Files:**
- Modify: `web/backend/services/system_status_service.py`
- Modify: `tests/test_system_status_service.py`
- Create: `tests/test_tracking_loop_contract.py`
- Modify: `docs/Tracking/tracking_agent_plan.md`
- Modify: `docs/superpowers/specs/2026-06-24-tracking-agent-loop-design.md`

- [ ] **Step 1: Add failing system status test for alert status counts**

Append to `tests/test_system_status_service.py`:

```python
def test_system_status_tracking_reports_alert_status_breakdown():
    service = build_service(
        tracking_items={
            "watch_buy": [{"tracking_id": "trk_1"}],
            "holding": [],
            "partial_sold": [],
        },
        alerts=[
            {"alert_id": 1, "ui_status": "pending", "priority": 10},
            {"alert_id": 2, "ui_status": "pending", "priority": 20},
        ],
    )

    payload = service.build_status()

    details = payload["tracking"]["details"]
    assert details["pending_alert_count"] == 2
    assert details["alert_status_counts"]["pending"] == 2
```

- [ ] **Step 2: Run focused system status test**

Run:

```powershell
python -m pytest tests/test_system_status_service.py::test_system_status_tracking_reports_alert_status_breakdown -q
```

Expected: fail because `alert_status_counts` is not present.

- [ ] **Step 3: Implement read-only alert status breakdown**

In `web/backend/services/system_status_service.py`, inside `_tracking_block`, calculate a breakdown from the already loaded pending alerts:

```python
        alert_status_counts = {"pending": len(pending_alerts)}
```

Then include it in `details`:

```python
                "alert_status_counts": alert_status_counts,
```

Do not instantiate `TrackingAlertService` and do not call write-capable helpers.

- [ ] **Step 4: Add end-to-end backend loop contract test**

Create `tests/test_tracking_loop_contract.py`:

```python
"""验证 Tracking Agent Loop MVP 的后端闭环合同。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pandas as pd

from web.backend.services.tracking_alert_service import TrackingAlertService
from web.backend.services.tracking_evaluation_service import TrackingEvaluationService
from web.backend.services.tracking_llm_service import TrackingLLMService
from web.backend.services.tracking_service import TrackingService


def _memory_connection():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _breakdown_frame() -> pd.DataFrame:
    start = datetime(2026, 1, 1)
    dates = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(200)]
    closes = [round(10.0 + i * 0.1, 2) for i in range(200)]
    closes[-3:] = [5.0, 4.5, 4.0]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * 200,
        }
    )


class _TemplateService:
    def build_engine_inputs(self) -> dict:
        return {"params_overrides": {}, "enabled_rules": None}


def test_tracking_loop_evaluate_alert_advice_confirm_and_ignore(monkeypatch) -> None:
    from web.backend.services import tracking_llm_service as llm_mod

    monkeypatch.setattr(llm_mod, "load_llm_config", lambda: {"provider": "mock"})
    monkeypatch.setattr(
        llm_mod.zettaranc_adapter,
        "prepare_context",
        lambda code, days=60: {"source": "local_csv", "text": "FAKE", "error": None},
    )

    conn = _memory_connection()
    tracking = TrackingService(connection_factory=lambda: conn, daily_loader=lambda code: _breakdown_frame())
    alerts = TrackingAlertService(connection_factory=lambda: conn)
    evaluator = TrackingEvaluationService(
        tracking_service=tracking,
        template_service=_TemplateService(),
        alert_service=alerts,
        frame_loader=lambda code: _breakdown_frame(),
    )
    llm = TrackingLLMService()

    item = tracking.create_item(
        {
            "code": "000559",
            "name": "万向钱潮",
            "strategy_name": "manual",
            "source": "manual",
            "source_date": "2026-05-01",
            "signal_date": "2026-01-10",
        }
    )

    summary = evaluator.evaluate_active_items(eval_date="2026-07-19")
    alert = alerts.list_alerts(tracking_id=item["tracking_id"])[0]
    advice = llm.propose_action(item, [alert], profile="zettaranc_style")
    confirmed = tracking.confirm_intent(item["tracking_id"], advice["suggested_intent"])
    ignored = alerts.update_alert_status(alert["alert_id"], "ignored")
    events = tracking.list_events(item["tracking_id"])

    assert summary["alerts_created"] >= 1
    assert advice["profile"] == "zettaranc_style"
    assert advice["zettaranc_data_source"] == "local_csv"
    assert confirmed["latest_intent"] == advice["suggested_intent"]
    assert ignored["ui_status"] == "ignored"
    assert events[-1]["event_type"] == "intent_confirmed"
```

- [ ] **Step 5: Run backend loop regression**

Run:

```powershell
python -m pytest tests/test_tracking_loop_contract.py tests/test_system_status_service.py tests/test_tracking_alert_service.py tests/test_tracking_evaluation_service.py tests/test_tracking_llm_profile.py tests/test_tracking_intent_actions.py -q
python -c "from web.backend.main import app; print('import-ok')"
```

Expected: all tests pass and import prints `import-ok`.

- [ ] **Step 6: Update docs**

In `docs/Tracking/tracking_agent_plan.md`, add a short "MVP loop execution contract" section:

```markdown
## MVP Loop Execution Contract

Tracking Agent Loop MVP 以规则引擎为权威，Zettaranc 只作为建议 profile 与技术上下文来源。
闭环顺序固定为：人工选股池或策略结果 → tracking_items → evaluate-rules →
tracking_alert_events → LLM/mock advice → OrderIntent → 人工确认或否决 →
tracking_events。

约束：

- `zettaranc_style` 不能覆盖规则引擎的 `action_label`。
- `suggested_intent` 必须进入人工确认，不能触发自动下单。
- 告警处理状态只允许 pending / dispatched / aggregated / acknowledged / ignored。
- 默认测试使用 mock provider；真实 provider smoke 必须单独执行和记录。
```

In `docs/superpowers/specs/2026-06-24-tracking-agent-loop-design.md`, add one line to the self-review section after the ambiguity check:

```markdown
- Execution plan sync: `docs/superpowers/plans/2026-06-24-tracking-agent-loop-mvp.md` implements this spec through four task slices.
```

- [ ] **Step 7: Run docs and full focused regression**

Run:

```powershell
git diff --check
python -m pytest tests/test_tracking_service.py tests/test_tracking_rule_engine.py tests/test_tracking_evaluation_service.py tests/test_tracking_alert_service.py tests/test_tracking_llm_service.py tests/test_tracking_llm_profile.py tests/test_tracking_intent_actions.py tests/test_tracking_loop_contract.py tests/test_system_status_service.py -q
python -c "from web.backend.main import app; print('import-ok')"
```

Expected: no whitespace errors, all tests pass, import prints `import-ok`.

- [ ] **Step 8: Commit Task 4**

Run:

```powershell
git add web/backend/services/system_status_service.py tests/test_system_status_service.py tests/test_tracking_loop_contract.py docs/Tracking/tracking_agent_plan.md docs/superpowers/specs/2026-06-24-tracking-agent-loop-design.md
git commit -m "feat: document and verify tracking loop contract"
```

---

## Final Verification

Run from the top-level repository:

```powershell
python -m pytest tests/test_tracking_service.py tests/test_tracking_rule_engine.py tests/test_tracking_evaluation_service.py tests/test_tracking_alert_service.py tests/test_tracking_llm_service.py tests/test_tracking_llm_profile.py tests/test_tracking_intent_actions.py tests/test_tracking_loop_contract.py tests/test_system_status_service.py tests/test_tracking_alert_router.py tests/test_tracking_evaluation_router.py tests/test_tracking_llm_router.py tests/test_tracking_intent_router.py -q
python -m pytest tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -c "from web.backend.main import app; print('import-ok')"
```

Run from `web/frontend` if Task 3 touched frontend:

```powershell
npm run test -- src/api/__tests__/trackingApi.spec.ts
npm run build
```

Then run from the top-level repository:

```powershell
git diff --check HEAD~4..HEAD
```

Expected:

- Backend focused tracking tests pass.
- Backtest regression tests pass.
- Import smoke prints `import-ok`.
- Frontend tracking API test passes.
- Frontend build passes or only reports non-failing Vite chunk-size warnings.
- Diff check reports no whitespace errors.

## Plan Self-Review

- Spec coverage: Tasks cover alert actions, Zettaranc advice visibility, intent confirmation, frontend operator loop, system status, and end-to-end regression.
- Placeholder scan: no unassigned placeholders remain.
- Type consistency: backend uses `suggested_intent`; frontend consumes `suggested_intent`; alert status values are `pending`, `dispatched`, `aggregated`, `acknowledged`, and `ignored`.
- Scope guard: automatic trading, QMT, broker adapters, full mark-to-market, and imported quant frameworks stay outside this plan.
