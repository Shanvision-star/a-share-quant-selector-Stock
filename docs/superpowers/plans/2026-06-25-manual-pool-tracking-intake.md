# Manual Pool Tracking Intake Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the missing frontend bridge from the manual selection pool to existing tracking intake.

**Architecture:** Keep the backend unchanged and reuse `POST /api/tracking/batch-from-selection`. Add a typed frontend API wrapper and a small operator workflow in `ManualSelectionPoolView.vue` with visible result feedback.

**Tech Stack:** Vue 3, TypeScript, Element Plus, Vitest, nested frontend git repository.

---

## Loop Prompt For Worker

```text
Loop until this task is genuinely complete:
1. Read this plan, the design spec, agent.md, and only the files named by the task.
2. Confirm this is frontend/API-wrapper work, not backend work.
3. Add the smallest failing Vitest check for the API wrapper.
4. Implement the smallest API wrapper.
5. Add the ManualSelectionPoolView UI bridge using existing Element Plus patterns.
6. Run the focused frontend test.
7. Run frontend build.
8. Self-review for no automatic trading, no backend contract drift, no unrelated Zettaranc edits.
9. Commit inside nested web/frontend first.
10. Report changed files and exact verification commands.
```

## Files

- Modify: `web/frontend/src/api/index.ts`
- Modify: `web/frontend/src/api/__tests__/trackingApi.spec.ts`
- Modify: `web/frontend/src/views/ManualSelectionPoolView.vue`

No backend files should change.

## Task 1: API Wrapper

- [ ] Add `TrackingBatchFromSelectionPayload` and `TrackingBatchFromSelectionResult` in `web/frontend/src/api/index.ts`.
- [ ] Export `batchCreateTrackingFromSelection(payload)` that posts to `/tracking/batch-from-selection`.
- [ ] Add a Vitest case in `web/frontend/src/api/__tests__/trackingApi.spec.ts` proving the endpoint path and payload shape.
- [ ] Run `npm run test -- src/api/__tests__/trackingApi.spec.ts`.

Expected wrapper shape:

```ts
export interface TrackingBatchFromSelectionPayload {
  selection_date: string
  codes?: string[]
}

export interface TrackingBatchFromSelectionResult {
  created: number
  skipped: number
  skipped_codes: string[]
  failed: string[]
  evaluation?: Record<string, any>
  evaluation_error?: string
}

export const batchCreateTrackingFromSelection = (payload: TrackingBatchFromSelectionPayload) =>
  api.post<{ success: boolean; data: TrackingBatchFromSelectionResult }>(
    '/tracking/batch-from-selection',
    payload,
  )
```

## Task 2: Manual Pool UI Bridge

- [ ] In `ManualSelectionPoolView.vue`, import the new API wrapper and `Plus` icon.
- [ ] Add row selection state and a selection column.
- [ ] Disable intake controls when `selectedDate` is empty.
- [ ] Implement `joinSelectedToTracking()` using selected visible rows.
- [ ] Implement `joinCurrentListToTracking()` using current filtered rows.
- [ ] Show an inline summary with created / skipped / failed counts and code lists.
- [ ] Add a "查看跟踪" action that routes to `/tracking`.
- [ ] Preserve existing refresh, export, backtest, detail, and remove actions.

## Task 3: Verification And Commit

- [ ] Run in `web/frontend`: `npm run test -- src/api/__tests__/trackingApi.spec.ts`.
- [ ] Run in `web/frontend`: `npm run build`.
- [ ] Run in top-level worktree: `git diff --check`.
- [ ] Commit nested frontend changes first:

```powershell
cd web/frontend
git add src/api/index.ts src/api/__tests__/trackingApi.spec.ts src/views/ManualSelectionPoolView.vue
git commit -m "feat: bridge manual pool to tracking intake"
```

- [ ] Commit top-level docs and gitlink after nested commit:

```powershell
git add docs/superpowers/specs/2026-06-25-manual-pool-tracking-intake-design.md docs/superpowers/plans/2026-06-25-manual-pool-tracking-intake.md web/frontend
git commit -m "feat: document manual pool tracking intake"
```
