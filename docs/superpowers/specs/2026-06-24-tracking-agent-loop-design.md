# Tracking Agent Loop MVP Design

> Status: approved scope for specification. This document locks the next product slice to
> the Tracking Agent Loop MVP and keeps broader broker / QMT / research-platform work out
> of this implementation cycle.
>
> Closeout status (2026-06-25): the Tracking Agent Loop MVP has been merged into the
> current top-level `web` mainline. This document is now the historical product baseline
> and boundary record, not a pending implementation checklist.

## 1. Goal

Build a governable stock tracking loop for the user's daily selected A-share pool:

1. Accept daily selected stocks from manual selection or strategy results.
2. Convert selected stocks into auditable tracking items.
3. Evaluate short-term and long-term rule templates from local historical data.
4. Persist deduplicated alert events.
5. Produce user-facing reminders and buy/sell/hold suggestions.
6. Convert actionable suggestions into `OrderIntent` records that require manual confirmation.

The MVP is not an automatic trading system. It is an evidence-backed tracking assistant that
helps the user avoid missing signals and keeps every recommendation traceable.

## 2. Authority And Repository Context

- Mainline target remains top-level `web`.
- Code and documentation work must happen on isolated `codex/*` branches before merging back.
- `web/frontend` is a nested repository; any frontend implementation must commit the nested
  frontend repository first, then the top-level gitlink.
- Existing unrelated dirty files must not be reverted or included in this feature.
- `agent.md` remains the operating authority for A-share execution boundaries.
- `docs/Tracking/tracking_agent_plan.md` is the current domain design baseline.
- `docs/BACKTEST_OVERVIEW.md` is the current backtest result contract baseline.

## 3. GitHub Alignment Review

High-quality quant and stock-tracking projects converge on layered systems rather than
single all-powerful agents:

| Project | What To Learn | What Not To Copy |
| --- | --- | --- |
| Backtrader | Broker / Sizer / Analyzer separation, event-driven mental model | Do not import GPL production dependency into this codebase |
| Zipline Reloaded | DataPortal, trading calendar, asset lifecycle boundaries | Do not replace current API and result contract |
| RQAlpha | A-share trading rules such as T+1, suspension, limit-up / limit-down, fees | Do not adopt a whole framework before local lab alignment |
| vn.py | Gateway, paper account, risk manager, portfolio manager separation | Do not enable broker auto-trading in the MVP |
| Microsoft Qlib | Research workflow, data processing, model experiment discipline | Do not move ML research into the tracking MVP |
| vectorbt | Parameter scans and portfolio analytics | Do not turn MVP alerts into massive parameter-mining work |
| Signalist / stock-monitor style apps | Watchlists, thresholds, scheduled checks, notification workflows | Do not reduce this project to generic price alerts without strategy evidence |
| OpenAlgo | Self-hosted algo workflow and broker API boundaries | Do not copy a full broker platform before manual confirmation is stable |

The project should absorb the architecture principle: signals, portfolio, alerts, advice,
and execution are separate units with explicit contracts.

## 4. Current Code Reality

The repository already has useful building blocks and, as of the 2026-06-25 closeout,
the MVP loop is implemented on `web`:

- `web/backend/backtest_engine/`: `DataPortal`, `SignalSource`, execution simulators,
  portfolio ledger, analyzer, and `OrderIntent`.
- `web/backend/services/tracking_service.py`: tracking item lifecycle and manual intent
  confirmation / rejection hooks.
- `web/backend/services/tracking_rule_engine.py`: pure rule evaluation for short and
  long-cycle rules.
- `web/backend/services/tracking_evaluation_service.py`: batch evaluation orchestration.
- `web/backend/services/tracking_alert_service.py`: alert persistence, deduplication, and
  dispatch abstraction.
- `web/backend/services/tracking_llm_service.py`: mock / DeepSeek provider boundary with
  deterministic fallback.
- `tests/test_tracking*.py` and `tests/test_backtest*.py`: existing regression anchors.

Implemented closeout facts:

- Manual selection intake and batch tracking intake are present.
- Rule evaluation persists deduplicated `tracking_alert_events`.
- Alert status actions cover acknowledge, ignore, and dispatch.
- LLM advice returns structured `suggested_intent`; `OrderIntent` remains manual-confirm
  or manual-reject only.
- System status includes tracking counts.

The original gap was product orchestration and UI/API completion, not lack of individual
building blocks. That gap is closed for the MVP; follow-up work should be scoped as a new
post-close task.

## 5. MVP Scope

### In Scope

- Daily selected stock ingestion from existing manual selection and strategy-result pathways.
- Batch conversion from selected stocks to active tracking items.
- Rule-based evaluation for active tracking items.
- Alert persistence with deduplication by tracking item, rule, and evaluation date.
- Alert center API and frontend view for pending, dispatched, acknowledged, and ignored alerts.
- LLM or mock advice that explains rule hits and returns stable structured JSON.
- Optional `zettaranc_style` advice profile that adds Zettaranc discipline language and
  technical context while keeping the same `Advice` JSON schema.
- Optional Zettaranc strategy or holdings outputs as tracking input sources, as long as they
  pass through the same tracking item, alert, and manual intent contracts.
- `OrderIntent` generation for buy, sell, reduce, hold, or wait suggestions.
- Manual confirmation and rejection of `OrderIntent`.
- System status visibility for tracking readiness, pending alert count, and recent failures.
- Focused backend and frontend tests for the closed loop.

### Out Of Scope

- Automatic broker order submission.
- QMT / miniQMT live trading integration.
- Real-time minute-level trading loop.
- LLM as the source of trading signals.
- Full daily mark-to-market valuation for open positions.
- Importing Backtrader, RQAlpha, Zipline, Qlib, vectorbt, vn.py, or OpenAlgo as production
  dependencies.
- Making Zettaranc the authority for rule outcomes or bypassing tracking alert deduplication.
- ML research pipeline, factor training, or parameter-mining platform.

## 6. Core Contracts

### TrackingItem

Represents one stock under observation.

Required fields:

- `tracking_id`
- `code`
- `name`
- `source`
- `source_date`
- `signal_date`
- `status`
- `params`
- `latest_intent`
- `last_eval_date`
- `next_action`

Status values should remain explicit and should not be inferred from missing fields.

### RuleHit / AlertEvent

Rule evaluation returns structured alert candidates. Persisted alerts must include:

- `tracking_id`
- `rule_id`
- `code`
- `eval_date`
- `priority`
- `category`
- `action_label`
- `message`
- `evidence`
- `dedup_key`
- `ui_status`
- `created_at`

`dedup_key` must be stable and collision-resistant for the MVP:

```text
{tracking_id}|{rule_id}|{eval_date}
```

The rule engine is the authority for `action_label`. LLM output may explain or summarize,
but it must not override the rule-derived action without recording a mismatch event.

### Advice

LLM or mock advice must be strict JSON:

```json
{
  "decision": "cut|reduce|hold|watch|add",
  "confidence": 0.0,
  "rationale": "string",
  "suggested_action": "SELL|REDUCE|HOLD|WAIT|BUY",
  "suggested_intent": {
    "code": "000001",
    "side": "SELL|BUY|HOLD",
    "qty_hint": 0,
    "reason": "string"
  },
  "provider": "mock|deepseek",
  "provider_fallback": false
}
```

Real provider smoke must stay separate from default automated tests. Mock advice remains the
default deterministic path.

### OrderIntent

`OrderIntent` is a manual action candidate, not an order.

Required boundaries:

- It must be traceable to a tracking item and recent alert or rule evidence.
- It must be visible to the user before confirmation.
- It can be confirmed or rejected by the user.
- Confirmation writes an audit event.
- Rejection writes an audit event and does not erase evidence.

### Zettaranc Integration Boundary

Zettaranc is a supported profile and evidence source, not a replacement for the tracking
loop authority.

Allowed integration points:

- `profile="zettaranc_style"` may be passed to the advice service to produce stricter
  discipline-oriented wording while preserving the same `Advice` JSON schema.
- `zettaranc_adapter.prepare_context(code)` may enrich advice with KDJ, MACD, BBI, moving
  averages, RSI, volume ratio, and trend-line context.
- `zettaranc_combo` strategy hits may become one source of daily selected stocks.
- Zettaranc holdings discipline alerts may be mapped into `AlertEvent` records.
- `zettaranc_data_source` should be shown when present, so the user can tell whether advice
  used CLI data, local CSV fallback, or no Zettaranc context.

Required safeguards:

- Zettaranc must not override rule-engine `action_label`.
- Zettaranc must not create broker orders or bypass `OrderIntent` manual confirmation.
- Zettaranc holdings alerts must use tracking alert deduplication before notification.
- Zettaranc provider or adapter failure must degrade to default mock advice and keep
  `provider_fallback` or `zettaranc_data_source="none"` visible.
- Zettaranc-specific files that are still uncommitted or experimental must not be treated as
  MVP-complete dependencies until their own tests and merge status are verified.

## 7. Loop Architecture

```text
Daily selected stocks
  -> manual_selections / strategy results
  -> batch tracking intake
  -> tracking_items
  -> evaluation service
  -> rule engine
  -> tracking_alert_events
  -> alert center / notification dispatch
  -> advice service
  -> OrderIntent
  -> manual confirmation / rejection
  -> tracking_events audit log
```

The loop should be idempotent:

- Running intake twice should not create duplicate active tracking items.
- Running evaluation twice on the same date should not create duplicate alerts.
- Dispatching alerts should not resend already dispatched items.
- Confirming or rejecting an intent should leave a durable event trail.

## 8. Frontend Product Surface

The MVP should expose three work surfaces:

1. Daily Pool / Intake
   - Shows selected stocks for a date.
   - Supports batch "加入跟踪".
   - Shows skipped duplicates and failed rows.

2. Tracking Dashboard
   - Groups active tracking items by status.
   - Shows latest return, last evaluation date, next action, and latest intent.
   - Provides "评估跟踪" action with visible loading and error states.

3. Alert Center
   - Lists pending / dispatched / acknowledged / ignored alerts.
   - Shows rule name, priority, message, evidence, advice profile, Zettaranc data source,
     provider fallback state, and suggested intent.
   - Allows acknowledge, ignore, confirm intent, and reject intent.

User-visible text must avoid "自动买入", "自动卖出", "AI 荐股", and "保证收益".

## 9. Scheduling And Notifications

The MVP should keep scheduling simple:

- Manual button is required.
- Optional crontab / Windows Task Scheduler template is allowed.
- No APScheduler or long-running scheduler is required in this slice.
- Notification dispatch should call the same backend API as manual dispatch.
- The default notifier can remain mock/null unless DingTalk credentials are already configured.

Slots:

- `pre_open`: pre-market review of prior close alerts.
- `midday`: optional manual dispatch only.
- `post_close`: after data update and rule evaluation.

## 10. Error Handling And Observability

Failures must be explicit:

- Data unavailable: item evaluation is skipped and counted.
- Bad CSV or missing columns: one item fails without blocking the batch.
- Duplicate alert: counted as skipped duplicate, not an error.
- LLM provider failure: fallback to mock and mark `provider_fallback=true`.
- Notification failure: keep alert pending or failed; do not lose the alert.
- User rejection: write event and preserve latest evidence.

System status should summarize:

- active tracking item count
- pending alert count
- last evaluation result
- provider fallback count if available
- recent errors

## 11. Testing Strategy

Use the cheapest verification first.

Backend focused tests:

- tracking intake does not duplicate active items
- rule evaluation creates expected alert candidates
- alert persistence deduplicates by `dedup_key`
- batch evaluation continues after one item failure
- LLM provider failure falls back to mock
- Zettaranc profile keeps the same advice schema and degrades cleanly when its adapter fails
- intent confirm / reject writes audit events
- API returns stable response shape

Frontend focused tests:

- alert center renders pending alerts
- action buttons show permission and state feedback
- provider fallback indicator is visible
- Zettaranc profile and data-source indicators are visible when returned by the API
- confirm / reject flows call expected APIs

Regression set before merge:

```powershell
python -m pytest tests/test_tracking_service.py tests/test_tracking_rule_engine.py tests/test_tracking_evaluation_service.py tests/test_tracking_alert_service.py tests/test_tracking_llm_service.py -q
python -m pytest tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -c "from web.backend.main import app; print('import-ok')"
```

Frontend commands depend on the touched files in `web/frontend`; if UI is changed, run the
existing nested frontend test/build commands and record any Vite warnings separately from
failures.

## 12. Implementation Phases

### Phase 1: Backend Loop Contract

Close backend gaps for intake, evaluation, alerts, advice, and intent audit.

Acceptance:

- One command or API call can evaluate active tracking items and persist alerts.
- Advice remains deterministic under mock provider.
- `OrderIntent` confirmation and rejection are auditable.

### Phase 2: Frontend Alert And Tracking UX

Expose the loop in the existing Vue frontend without redesigning the whole app.

Acceptance:

- User can see selected stocks, add them to tracking, evaluate, inspect alerts, and act on intents.
- Permission and fallback states are visible.
- No text implies automatic trading.

### Phase 3: Notification And Status Center Integration

Wire manual dispatch and system status visibility.

Acceptance:

- Pending alerts can be dispatched idempotently.
- System status shows whether tracking is healthy.
- Notification failure does not block alert center usage.

## 13. Product Boundaries For Future Specs

These are future specs, not part of this MVP:

- Full mark-to-market valuation for open tracking holdings.
- SimBroker / ManualBroker account ledger.
- QMT readonly adapter.
- Real broker order gateway.
- Live minute data loop.
- ML factor research and Qlib-style experiment management.
- vectorbt-style parameter sweep UI.

If any of these becomes necessary, update the authority document and create a separate
spec before implementation.

## 14. Post-close Follow-up Boundaries

These are allowed follow-up task names, not completed facts:

- Manual Pool -> Tracking Intake Bridge: improve operator feedback around selected rows,
  duplicate intake, failed rows, and date selection. Do not rebuild the existing
  `/api/manual-selections/*` or `/api/tracking/batch-from-selection` contracts.
- Post-close Loop Runner: design an explicit after-close evaluation / dispatch runner.
  Keep mock provider tests as the default and record real provider smoke separately.

Not verified in this documentation-only closeout: backend pytest, frontend build, nested
frontend repository status, real provider smoke, and DingTalk real dispatch.

## 15. Self-Review

- Placeholder scan: no `TBD` or unassigned implementation requirement remains.
- Internal consistency: MVP stays rule-authoritative, advice-explanatory, and manual-confirmed.
- Scope check: one implementation plan can deliver backend loop, frontend surfaces, and status
  integration in three phases.
- Ambiguity check: automatic trading, QMT, imported frameworks, Zettaranc authority override,
  and real provider smoke are explicitly out of scope.
- Execution plan sync: `docs/superpowers/plans/2026-06-24-tracking-agent-loop-mvp.md`
  is now a historical implementation plan for the merged MVP.
