# Tracking Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first standalone single-stock tracking module that connects manual selections/backtest results to persistent tracking records and daily buy/hold/sell suggestions.

**Architecture:** Tracking is separate from backtest. Backtest remains historical simulation; tracking stores current watch/holding state, event history, and generated `OrderIntent` suggestions. Frontend adds lightweight controls to create and evaluate tracking items from the backtest workspace.

**Tech Stack:** FastAPI, SQLite, pytest, Vue 3, TypeScript, Element Plus, Vitest.

---

### Task 1: Backend Tracking Schema And Service

**Files:**
- Create: `web/backend/services/tracking_service.py`
- Modify: `web/backend/services/sqlite_service.py`
- Test: `tests/test_tracking_service.py`

- [ ] Write failing tests for creating a tracking item, listing it, and evaluating a watch item into a holding suggestion.
- [ ] Add `tracking_items` and `tracking_events` tables to SQLite initialization.
- [ ] Implement `TrackingService` with dependency-injected connection factory and daily price loader.
- [ ] Generate event records for create/evaluate actions.
- [ ] Generate `OrderIntent` in evaluation payloads without broker execution.
- [ ] Run `python -m pytest tests/test_tracking_service.py -q`.

### Task 2: Tracking API

**Files:**
- Create: `web/backend/routers/tracking.py`
- Modify: `web/backend/main.py`
- Test: `tests/test_tracking_router.py`

- [ ] Write failing FastAPI tests for create/list/evaluate endpoints.
- [ ] Add router endpoints under `/api/tracking`.
- [ ] Register router in app startup.
- [ ] Run `python -m pytest tests/test_tracking_router.py tests/test_tracking_service.py -q`.

### Task 3: Frontend Tracking Controls

**Files:**
- Modify: `web/frontend/src/api/index.ts`
- Modify: `web/frontend/src/views/BacktestView.vue`
- Test: `web/frontend/src/api/__tests__/trackingApi.spec.ts`

- [ ] Write failing Vitest tests for tracking API calls.
- [ ] Add tracking API client types and functions.
- [ ] Add backtest workspace tracking panel.
- [ ] Add “加入跟踪” buttons for candidate rows and trade rows.
- [ ] Add “评估跟踪” action and latest suggestion display.
- [ ] Run `npm run test -- src/api/__tests__/trackingApi.spec.ts --run`.
- [ ] Run `npm run build`.

### Task 4: Documentation, Verification, Merge

**Files:**
- Create: `docs/Backtesting/tracking_phase1_memory.md`

- [ ] Record implementation summary, state model, verification evidence, and next plan.
- [ ] Run backend tests covering tracking and backtest smoke.
- [ ] Commit frontend subrepo first.
- [ ] Commit root repo including frontend gitlink and docs.
- [ ] Fast-forward merge into `web`.
