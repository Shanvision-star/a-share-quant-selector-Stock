# Tracking Loop Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> when the next task has independent code slices, or superpowers:executing-plans for a
> single-session documentation / verification closeout. Steps use checkbox (`- [ ]`)
> syntax for tracking.

**Goal:** Finish previously merged Tracking Agent Loop work by verifying the current `web`
mainline, correcting stale closeout records, and leaving a reusable loop prompt for future
agents.

**Architecture:** Treat the existing implementation as the authority, not the stale plan.
Classify any remaining work as code, documentation, verification, or product-boundary before
editing. Default to verification and documentation updates unless fresh tests expose a real
code gap.

**Tech Stack:** FastAPI, SQLite, pytest, Vue 3, TypeScript, Vitest, Vite, Markdown.

---

## Reusable Completion Loop Prompt

Use this prompt when the user says to continue or finish a previous Tracking Agent Loop task:

```text
You are completing a previously started Tracking Agent Loop task in the A-share quant
selector repository.

Loop until the task is genuinely complete:
1. Start from the current top-level `web` mainline in an isolated `codex/*` branch or
   worktree. Do not include unrelated dirty files.
2. Read `agent.md`, `docs/TRACKING_AGENT.md`,
   `docs/Tracking/tracking_agent_plan.md`, and the relevant
   `docs/superpowers/plans/*tracking*loop*.md` file.
3. Compare the plan with current code. Classify the remaining gap as exactly one of:
   code gap, documentation gap, verification gap, or product-boundary decision.
4. If it is a code gap, write the smallest failing test first, confirm the red state,
   implement the minimal fix, and rerun the focused tests.
5. If it is a documentation gap, update only authority / closeout docs and include the
   exact fresh verification evidence. Do not present old assumptions as completed facts.
6. If it is a verification gap, run the cheapest focused command first, then broaden only
   when the touched surface justifies it.
7. Keep real LLM, DingTalk, broker, QMT, and live-provider smoke outside default tests.
8. Verify backend tracking, backtest compatibility, import smoke, and frontend nested repo
   tests/build when frontend state is part of the claim.
9. Self-review the diff for rule authority, no automatic trading, no Zettaranc authority
   override, no route-order regression, and no unrelated edits.
10. Commit only the files touched by the current task, then merge back to local `web`
    only after fresh verification passes.
```

## 2026-06-30 Gap Classification

| Check | Result |
| --- | --- |
| Code gap | None found in current focused regression. |
| Documentation gap | Historical closeout docs still said backend / frontend loop verification was not run. |
| Verification gap | Closed with fresh backend tracking, backtest, import-smoke, and frontend nested repo verification. |
| Product-boundary decision | No new scope opened; real provider, DingTalk, broker, QMT, cron, and live minute loop remain out of default MVP closeout. |

## 2026-06-30 Execution Checklist

- [x] Read current plan/spec/docs and compare them with current `web`.
- [x] Verify backend Tracking Agent Loop regression:
      `python -m pytest tests/test_tracking_service.py tests/test_tracking_rule_engine.py tests/test_tracking_evaluation_service.py tests/test_tracking_alert_service.py tests/test_tracking_llm_service.py tests/test_tracking_llm_profile.py tests/test_tracking_intent_actions.py tests/test_tracking_loop_contract.py tests/test_system_status_service.py tests/test_tracking_alert_router.py tests/test_tracking_evaluation_router.py tests/test_tracking_llm_router.py tests/test_tracking_intent_router.py -q`
      -> 84 passed.
- [x] Verify backtest compatibility regression:
      `python -m pytest tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q`
      -> 60 passed.
- [x] Verify app import smoke:
      `python -c "from web.backend.main import app; print('import-ok')"`
      -> import-ok.
- [x] Verify nested frontend API test:
      `npm run test -- src/api/__tests__/trackingApi.spec.ts`
      -> 5 passed.
- [x] Verify nested frontend production build:
      `npm run build`
      -> passed with non-failing Vite chunk-size warnings.

## Remaining Explicit Non-Goals

- No real LLM provider smoke in this loop.
- No real DingTalk dispatch smoke in this loop.
- No broker / QMT / automatic order submission.
- No cron or Windows Task Scheduler activation.
- No live minute-level trading loop.
