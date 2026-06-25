# Manual Pool Tracking Intake Bridge Design

> Status: approved follow-up slice after Tracking Agent Loop MVP closeout.

## Goal

Connect the existing manual selection pool page to the existing backend tracking intake API so an operator can move a single-day pool, or selected rows from that pool, into Tracking without leaving the workflow.

## Current Reality

- Backend `POST /api/tracking/batch-from-selection` already accepts `selection_date` and optional `codes`.
- Backend returns `created`, `skipped`, `skipped_codes`, and `failed`; it does not need a new endpoint.
- `ManualSelectionPoolView.vue` already lists manual selections, filters rows, exports CSV, sends rows to backtest, and removes rows.
- `web/frontend` is a nested repository and must be committed before the top-level gitlink is committed.

## In Scope

- Add a frontend API wrapper for `/tracking/batch-from-selection`.
- Add Vitest coverage for the wrapper.
- Add row selection to `/manual-pool`.
- Enable "选中加入跟踪" and "当前列表加入跟踪" only in single-date mode.
- Show created / skipped / failed result feedback, including skipped and failed code lists.
- Provide a visible path to `/tracking` after intake.

## Out Of Scope

- No backend endpoint changes.
- No automatic trading, broker, QMT, or real provider smoke.
- No LLM advice generation.
- No alert center redesign.
- No rule-template editor.
- No range-mode batch intake; range mode requires choosing a single date first.

## Acceptance

- In single-date mode, selected rows call `/api/tracking/batch-from-selection` with `selection_date` and selected `codes`.
- In single-date mode, current filtered rows call the same endpoint with the filtered code list.
- In range mode, intake controls remain disabled and user feedback explains why.
- Result feedback is visible on the page and does not hide skipped/failed rows.
- Existing backtest, export, detail, and remove actions remain available.

## Verification

```powershell
cd web/frontend
npm run test -- src/api/__tests__/trackingApi.spec.ts
npm run build
```

Top-level:

```powershell
git diff --check
```

Backend pytest is not required unless the implementation changes backend contracts.
