# Backtest Phase A Execution Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a verifiable Phase A loop for A-share backtest execution correctness: trading-day advancement, buy-side tradeability, sell-side tradeability, and regression proof.

**Architecture:** Keep the existing `DataPortal / SignalSource / Execution / Portfolio / Analyzer` split. Add small trading-calendar helpers in `utils/trading_calendar.py`, then make `DailyExecutionSimulator` use exact A-share trading-day targets and shared sellability helpers without changing the `/api/backtest` response shape.

**Tech Stack:** Python 3, pandas, pytest, existing `web/backend/backtest_engine/*`, existing FastAPI app import smoke.

---

## File Structure

- Modify: `utils/trading_calendar.py`
  - Responsibility: A-share trading-day helpers shared by update, strategy, and backtest flows.
- Modify: `tests/test_trading_calendar.py`
  - Responsibility: deterministic holiday/weekend regression tests.
- Modify: `web/backend/backtest_engine/execution.py`
  - Responsibility: daily execution rules for buy/sell simulation and `OrderIntent` generation.
- Modify: `tests/test_backtest_engine.py`
  - Responsibility: focused backtest-engine behavior tests.
- Optional modify: `docs/BACKTEST_OVERVIEW.md`
  - Responsibility: only update if implementation changes user-visible backtest semantics.

Do not modify:

- `web/frontend/*` in Phase A.
- `web/backend/routers/backtest.py` unless a focused regression proves the API shell is broken.
- Strategy files under `strategy/`.
- `web/backend/backtest_engine/portfolio.py`; full cash ledger belongs to later Phase B.
- QMT, miniQMT, broker adapters, or real trading paths.

## Shared Agent Loop

Use this loop for every task:

```text
Observe: read agent.md, the approved spec, and the exact files for the current task.
Plan: name the allowed files, expected failing test, implementation boundary, and verification command.
Review: confirm the branch is not web and no unrelated dirty files are staged.
Act: write the failing test, run it, implement the smallest code, run focused tests.
Verify: run the task-level pytest and git diff --check.
Reflect: summarize behavior, changed files, verification, and any unverified wider surface.
```

## Task 1: Trading Calendar Helpers

**Files:**

- Modify: `utils/trading_calendar.py`
- Modify: `tests/test_trading_calendar.py`

- [ ] **Step 1: Confirm branch and clean task surface**

Run:

```powershell
git status --short --branch
```

Expected:

```text
## codex/backtest-phase-a-design
```

If unrelated dirty files appear in this worktree, stop and inspect before staging.

- [ ] **Step 2: Write failing calendar tests**

Modify `tests/test_trading_calendar.py` so the import block and tests read:

```python
from datetime import date

from utils.trading_calendar import (
    advance_a_share_trading_days,
    count_a_share_trading_days,
    next_a_share_trading_day,
    previous_a_share_trading_day,
)


def test_may_day_gap_counts_only_real_a_share_trading_days():
    assert count_a_share_trading_days(date(2026, 5, 1), date(2026, 5, 6)) == 1


def test_previous_trading_day_skips_2026_may_day_holiday():
    assert previous_a_share_trading_day(date(2026, 5, 4)) == date(2026, 4, 30)


def test_next_trading_day_skips_2026_may_day_holiday():
    assert next_a_share_trading_day(date(2026, 4, 30)) == date(2026, 5, 6)


def test_advance_trading_days_handles_zero_and_holiday_gap():
    assert advance_a_share_trading_days(date(2026, 4, 30), 0) == date(2026, 4, 30)
    assert advance_a_share_trading_days(date(2026, 4, 30), 1) == date(2026, 5, 6)
    assert advance_a_share_trading_days(date(2026, 4, 30), 2) == date(2026, 5, 7)
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_trading_calendar.py -q
```

Expected: FAIL with an import error for `next_a_share_trading_day` or `advance_a_share_trading_days`.

- [ ] **Step 4: Implement minimal calendar helpers**

Modify `utils/trading_calendar.py` by adding the two functions after `previous_a_share_trading_day`:

```python
def next_a_share_trading_day(day: date_cls) -> date_cls:
    """Return the first A-share trading day after day."""
    cursor = day + timedelta(days=1)
    while not is_a_share_trading_day(cursor):
        cursor += timedelta(days=1)
    return cursor


def advance_a_share_trading_days(day: date_cls, days: int) -> date_cls:
    """Advance by real A-share trading days.

    days=0 keeps a valid trading day unchanged. If the input day is closed,
    it is normalized to the previous trading day before advancing.
    """
    cursor = day if is_a_share_trading_day(day) else previous_a_share_trading_day(day)
    if days <= 0:
        return cursor
    for _ in range(days):
        cursor = next_a_share_trading_day(cursor)
    return cursor
```

- [ ] **Step 5: Run focused calendar tests**

Run:

```powershell
python -m pytest tests/test_trading_calendar.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add utils/trading_calendar.py tests/test_trading_calendar.py
git commit -m "feat: add a-share trading day advancement helpers"
```

Expected: a commit containing only the calendar helper and calendar tests.

## Task 2: Buy Date Uses Exact A-Share Trading Target

**Files:**

- Modify: `web/backend/backtest_engine/execution.py`
- Modify: `tests/test_backtest_engine.py`

- [ ] **Step 1: Write failing missing-target-bar test**

Append this test after `test_daily_engine_uses_future_price_window_after_same_day_signal` in `tests/test_backtest_engine.py`:

```python
def test_daily_engine_does_not_buy_when_calendar_target_bar_is_missing():
    """买入目标交易日缺行情时跳过，不能顺延到后续行情行假装成交。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2026-04-30",
        signal_date="2026-04-30",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-30"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-05-07"), "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1000},
            {"date": pd.Timestamp("2026-05-08"), "open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(start_date="2026-04-30", end_date="2026-04-30"))

    assert result["summary"]["trade_count"] == 0
    assert result["summary"]["skipped_count"] == 1
```

Existing behavior is expected to buy on `2026-05-07` because it uses row offset instead of exact trading-date target.

- [ ] **Step 2: Write passing-regression holiday target test**

Append this test after the missing-target-bar test:

```python
def test_daily_engine_buys_on_next_real_trading_day_after_holiday_gap():
    """买入延后一天应跳过五一假期，落到 2026-05-06。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2026-04-30",
        signal_date="2026-04-30",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-30"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-05-06"), "open": 10.2, "high": 10.4, "low": 10.1, "close": 10.3, "volume": 1000},
            {"date": pd.Timestamp("2026-05-07"), "open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(start_date="2026-04-30", end_date="2026-04-30"))

    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["buy_date"] == "2026-05-06"
    assert result["trades"][0]["sell_date"] == "2026-05-07"
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_daily_engine_does_not_buy_when_calendar_target_bar_is_missing tests/test_backtest_engine.py::test_daily_engine_buys_on_next_real_trading_day_after_holiday_gap -q
```

Expected: the missing-target-bar test FAILS with `trade_count == 1`; the holiday target test may already pass.

- [ ] **Step 4: Import calendar helper into execution**

Modify the imports near the top of `web/backend/backtest_engine/execution.py`:

```python
import pandas as pd

from utils.trading_calendar import advance_a_share_trading_days
from web.backend.backtest_engine.data_portal import DailyDataPortal, MinuteDataPortal
from web.backend.backtest_engine.models import BacktestParams, MinuteBar, OrderIntent, SignalCandidate
```

- [ ] **Step 5: Add exact-date helpers**

Add these helpers after `_find_signal_index`:

```python
def _find_exact_date_index(frame: pd.DataFrame, target_day) -> Optional[int]:
    matched = frame.index[frame["date"].dt.date == target_day]
    if len(matched) == 0:
        return None
    return int(matched[0])


def _find_buy_index(frame: pd.DataFrame, signal_date: str, buy_offset_days: int) -> Optional[int]:
    signal_day = pd.to_datetime(signal_date).date()
    buy_day = advance_a_share_trading_days(signal_day, max(0, buy_offset_days))
    return _find_exact_date_index(frame, buy_day)
```

- [ ] **Step 6: Replace row-offset buy calculation**

In `DailyExecutionSimulator.simulate_trade`, replace:

```python
        buy_index = signal_index + int(params.get("buy_offset_days", 1))
        if buy_index >= len(frame):
            return None
```

with:

```python
        buy_index = _find_buy_index(frame, candidate.signal_date, int(params.get("buy_offset_days", 1)))
        if buy_index is None:
            return None
```

Keep the existing `signal_index` lookup because it still proves the signal is within available historical context.

- [ ] **Step 7: Run focused buy-date tests**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_daily_engine_does_not_buy_when_calendar_target_bar_is_missing tests/test_backtest_engine.py::test_daily_engine_buys_on_next_real_trading_day_after_holiday_gap -q
```

Expected:

```text
2 passed
```

- [ ] **Step 8: Run existing engine tests**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py -q
```

Expected: all tests in `tests/test_backtest_engine.py` pass. If a fixture without `volume` now fails in later tasks, update only that fixture with explicit `volume: 1000`.

- [ ] **Step 9: Commit Task 2**

Run:

```powershell
git add web/backend/backtest_engine/execution.py tests/test_backtest_engine.py
git commit -m "fix: align daily buy offset with a-share trading calendar"
```

Expected: a commit containing execution buy-date logic and focused tests only.

## Task 3: Buy-Side Tradeability Requires Explicit Positive Volume

**Files:**

- Modify: `web/backend/backtest_engine/execution.py`
- Modify: `tests/test_backtest_engine.py`

- [ ] **Step 1: Write failing buy-side volume test**

Append this test after `test_daily_engine_blocks_st_and_limit_up_buy_and_rounds_lot_quantity`:

```python
def test_daily_engine_requires_positive_volume_on_buy_day():
    """买入日没有明确正成交量时视为不可交易，避免停牌或坏数据被成交。"""
    candidates = [
        SignalCandidate(
            code="000001",
            name="平安银行",
            strategy_name="manual",
            trade_date="2026-04-24",
            signal_date="2026-04-24",
            source="manual",
        ),
        SignalCandidate(
            code="000002",
            name="无成交量示例",
            strategy_name="manual",
            trade_date="2026-04-24",
            signal_date="2026-04-24",
            source="manual",
        ),
    ]
    frames = {
        "000001": pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 10.2, "high": 10.5, "low": 10.1, "close": 10.4, "volume": 1000},
            ]
        ),
        "000002": pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 8.0, "high": 8.2, "low": 7.9, "close": 8.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 8.1, "high": 8.3, "low": 8.0, "close": 8.2},
                {"date": pd.Timestamp("2026-04-28"), "open": 8.2, "high": 8.5, "low": 8.1, "close": 8.4, "volume": 1000},
            ]
        ),
    }
    engine = BacktestEngine(
        signal_source=StaticSignalSource(candidates),
        daily_portal=InMemoryDailyDataPortal(frames),
    )

    result = engine.run_daily(_default_params())

    assert result["summary"]["trade_count"] == 1
    assert result["summary"]["skipped_count"] == 1
    assert result["trades"][0]["code"] == "000001"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_daily_engine_requires_positive_volume_on_buy_day -q
```

Expected: FAIL because `_is_tradeable_row` currently treats missing `volume` as `1.0`.

- [ ] **Step 3: Make volume requirement explicit**

Replace `_is_tradeable_row` in `web/backend/backtest_engine/execution.py` with:

```python
def _is_tradeable_row(row) -> bool:
    # A 股停牌或坏数据常表现为成交量缺失/为 0；没有明确正成交量时不能模拟成交。
    volume = _safe_float(row.get("volume"), 0.0)
    prices = [_safe_float(row.get(field), 0.0) for field in ("open", "high", "low", "close")]
    return volume > 0 and all(price > 0 for price in prices)
```

- [ ] **Step 4: Add volume to existing positive fixtures if needed**

If `tests/test_backtest_engine.py` now fails only because a positive-trade fixture omitted `volume`, add `"volume": 1000` to the buy and sell rows in that fixture. Do not change expected returns or dates.

The common positive fixture pattern should look like:

```python
{"date": pd.Timestamp("2026-04-27"), "open": 10.1, "high": 10.3, "low": 10.0, "close": 10.2, "volume": 1000}
```

- [ ] **Step 5: Run buy-side focused tests**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_daily_engine_blocks_st_and_limit_up_buy_and_rounds_lot_quantity tests/test_backtest_engine.py::test_daily_engine_requires_positive_volume_on_buy_day -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Run engine tests**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py -q
```

Expected: all tests in `tests/test_backtest_engine.py` pass.

- [ ] **Step 7: Commit Task 3**

Run:

```powershell
git add web/backend/backtest_engine/execution.py tests/test_backtest_engine.py
git commit -m "fix: require positive volume for daily execution trades"
```

Expected: a commit containing only buy-side tradeability tightening and fixture updates required by the stricter rule.

## Task 4: Sell-Side Tradeability Applies to Early Exits

**Files:**

- Modify: `web/backend/backtest_engine/execution.py`
- Modify: `tests/test_backtest_engine.py`

- [ ] **Step 1: Write failing delayed stop-loss test**

Append this test after `test_daily_engine_skips_when_no_t_plus_one_sell_day`:

```python
def test_daily_engine_delays_stop_loss_exit_when_limit_down_locked():
    """止损触发日跌停锁死时，应顺延到下一可卖日，不能按止损价虚假成交。"""
    candidate = SignalCandidate(
        code="000001",
        name="平安银行",
        strategy_name="manual",
        trade_date="2026-04-24",
        signal_date="2026-04-24",
        source="manual",
    )
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-28"), "open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "volume": 1000},
            {"date": pd.Timestamp("2026-04-29"), "open": 9.1, "high": 9.4, "low": 9.0, "close": 9.2, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(_default_params(holding_days=2, stop_loss_pct=5))

    assert result["summary"]["trade_count"] == 1
    assert result["trades"][0]["sell_date"] == "2026-04-29"
    assert result["trades"][0]["sell_price"] == 9.2
    assert result["trades"][0]["exit_reason"] == "fixed_stop_loss"
```

Existing behavior is expected to sell on `2026-04-28` at `9.5`, which is impossible during a locked limit-down day.

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_daily_engine_delays_stop_loss_exit_when_limit_down_locked -q
```

Expected: FAIL with `sell_date == "2026-04-28"` or `sell_price == 9.5`.

- [ ] **Step 3: Add sellable exit resolver**

Add this helper after `_find_sellable_index` in `web/backend/backtest_engine/execution.py`:

```python
def _resolve_sellable_exit(
    frame: pd.DataFrame,
    trigger_index: int,
    end_index: int,
    candidate: SignalCandidate,
    requested_price: float,
    sell_price_field: str,
) -> Optional[tuple[int, object, float]]:
    sell_index = _find_sellable_index(frame, trigger_index, end_index, candidate)
    if sell_index is None:
        return None
    sell_row = frame.iloc[sell_index]
    if sell_index == trigger_index:
        sell_price = requested_price
    else:
        sell_price = _pick_price(sell_row, sell_price_field)
    if sell_price <= 0:
        return None
    return sell_index, sell_row, sell_price


def _append_sellable_exit(
    exits: list[dict],
    frame: pd.DataFrame,
    trigger_index: int,
    end_index: int,
    candidate: SignalCandidate,
    requested_price: float,
    portion: float,
    reason: str,
    remaining_before: float,
    fee_rate: float,
    slippage_rate: float,
    sell_price_field: str,
) -> tuple[float, Optional[int]]:
    resolved = _resolve_sellable_exit(
        frame,
        trigger_index,
        end_index,
        candidate,
        requested_price,
        sell_price_field,
    )
    if resolved is None:
        return remaining_before, None
    sell_index, sell_row, sell_price = resolved
    remaining_after = _append_exit(
        exits,
        sell_row,
        sell_price,
        portion,
        reason,
        remaining_before,
        fee_rate,
        slippage_rate,
    )
    return remaining_after, sell_index
```

- [ ] **Step 4: Use resolver for fixed stop-loss**

Replace the fixed stop-loss block in `DailyExecutionSimulator.simulate_trade` with:

```python
            if stop_loss_pct > 0 and low_price <= buy_price * (1 - stop_loss_pct / 100):
                remaining, sell_index = _append_sellable_exit(
                    exits,
                    frame,
                    index,
                    end_bound_index,
                    candidate,
                    buy_price * (1 - stop_loss_pct / 100),
                    remaining,
                    "fixed_stop_loss",
                    remaining,
                    fee_rate,
                    slippage_rate,
                    sell_price_field,
                )
                if sell_index is None:
                    return None
                break
```

- [ ] **Step 5: Use resolver for other full-exit paths**

Replace each direct `_append_exit(...); break` full-exit block inside the daily loop with the same pattern, changing only `requested_price`, `portion`, and `reason`.

For no-gain exit:

```python
            if bool(params.get("enable_no_gain_exit", True)) and index - buy_index >= no_gain_days and close_price <= buy_price:
                remaining, sell_index = _append_sellable_exit(
                    exits,
                    frame,
                    index,
                    end_bound_index,
                    candidate,
                    close_price,
                    remaining,
                    "no_gain_exit",
                    remaining,
                    fee_rate,
                    slippage_rate,
                    sell_price_field,
                )
                if sell_index is None:
                    return None
                break
```

For bull-bear break:

```python
            if bool(params.get("exit_on_bull_bear_break", True)) and bull_bear_line > 0 and close_price < bull_bear_line:
                remaining, sell_index = _append_sellable_exit(
                    exits,
                    frame,
                    index,
                    end_bound_index,
                    candidate,
                    close_price,
                    remaining,
                    "bull_bear_break",
                    remaining,
                    fee_rate,
                    slippage_rate,
                    sell_price_field,
                )
                if sell_index is None:
                    return None
                break
```

For short-trend drawdown:

```python
            if bool(params.get("exit_on_short_trend_drawdown", True)) and short_line > 0 and close_price <= short_line * (1 - short_drawdown_pct / 100):
                remaining, sell_index = _append_sellable_exit(
                    exits,
                    frame,
                    index,
                    end_bound_index,
                    candidate,
                    close_price,
                    remaining,
                    "short_trend_drawdown",
                    remaining,
                    fee_rate,
                    slippage_rate,
                    sell_price_field,
                )
                if sell_index is None:
                    return None
                break
```

For short-trend break days:

```python
            if bool(params.get("exit_on_short_trend_break", True)) and short_break_streak >= short_break_days:
                remaining, sell_index = _append_sellable_exit(
                    exits,
                    frame,
                    index,
                    end_bound_index,
                    candidate,
                    close_price,
                    remaining,
                    "short_trend_break_days",
                    remaining,
                    fee_rate,
                    slippage_rate,
                    sell_price_field,
                )
                if sell_index is None:
                    return None
                break
```

For profit-runner short-trend break:

```python
            if runner_triggered and bool(params.get("hold_above_short_trend_after_trigger", True)) and short_line > 0 and close_price < short_line:
                remaining, sell_index = _append_sellable_exit(
                    exits,
                    frame,
                    index,
                    end_bound_index,
                    candidate,
                    close_price,
                    remaining,
                    "profit_runner_short_trend_break",
                    remaining,
                    fee_rate,
                    slippage_rate,
                    sell_price_field,
                )
                if sell_index is None:
                    return None
                break
```

For legacy take-profit:

```python
            if not profit_run_enabled and legacy_take_profit_pct > 0 and high_price >= buy_price * (1 + legacy_take_profit_pct / 100):
                remaining, sell_index = _append_sellable_exit(
                    exits,
                    frame,
                    index,
                    end_bound_index,
                    candidate,
                    buy_price * (1 + legacy_take_profit_pct / 100),
                    remaining,
                    "take_profit",
                    remaining,
                    fee_rate,
                    slippage_rate,
                    sell_price_field,
                )
                if sell_index is None:
                    return None
                break
```

- [ ] **Step 6: Keep Profit Runner ladder sellable on trigger day**

Inside the `while remaining > 0 and current_high_pct >= next_profit_ladder_pct:` block, replace the ladder `_append_exit` call with:

```python
                    remaining, sell_index = _append_sellable_exit(
                        exits,
                        frame,
                        index,
                        end_bound_index,
                        candidate,
                        exit_price,
                        portion,
                        f"profit_ladder_{next_profit_ladder_pct:.1f}pct",
                        remaining,
                        fee_rate,
                        slippage_rate,
                        sell_price_field,
                    )
                    if sell_index is None:
                        return None
```

If `sell_index > index`, append the action using the delayed sell date from `exits[-1]["date"]`, then break out of the ladder loop to avoid adding more partial exits before the delayed sale date:

```python
                    profit_actions.append(
                        {
                            "date": exits[-1]["date"],
                            "action": "sell_partial",
                            "profit_pct": round(next_profit_ladder_pct, 2),
                            "sell_pct": round(portion * 100, 2),
                            "remaining_pct": round(remaining * 100, 2),
                        }
                    )
                    next_profit_ladder_pct += profit_step_pct
                    if sell_index > index:
                        break
```

Do not change the existing `hold_core` behavior.

- [ ] **Step 7: Run delayed stop-loss test**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_daily_engine_delays_stop_loss_exit_when_limit_down_locked -q
```

Expected:

```text
1 passed
```

- [ ] **Step 8: Run engine tests**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py -q
```

Expected: all tests in `tests/test_backtest_engine.py` pass, including profit-runner tests.

- [ ] **Step 9: Commit Task 4**

Run:

```powershell
git add web/backend/backtest_engine/execution.py tests/test_backtest_engine.py
git commit -m "fix: apply sellability checks to daily early exits"
```

Expected: a commit containing sell-side execution helper changes and focused tests.

## Task 5: Phase A Regression Gate

**Files:**

- Modify: `docs/BACKTEST_OVERVIEW.md` only if behavior notes need a visible user-facing explanation.
- Do not modify frontend files.

- [ ] **Step 1: Run focused calendar and engine tests**

Run:

```powershell
python -m pytest tests/test_trading_calendar.py tests/test_backtest_engine.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run service/router regression tests**

Run:

```powershell
python -m pytest tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
```

Expected: all selected tests pass. If a test fails because stricter execution reduces `trade_count`, inspect whether the old expected value relied on impossible trading; update the expectation only with a short Chinese comment explaining the A-share boundary.

- [ ] **Step 3: Run import smoke**

Run:

```powershell
python -c "from web.backend.main import app; print('import-ok')"
```

Expected:

```text
import-ok
```

- [ ] **Step 4: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output.

- [ ] **Step 5: Decide whether docs need sync**

If no public semantics changed beyond stricter execution correctness, leave docs unchanged and record `No docs sync needed: API shape unchanged`.

If docs need sync, add this concise note under `docs/BACKTEST_OVERVIEW.md` section `3. 单股退出规则（已固化）`:

```markdown
执行层会先检查 A 股可交易边界：买入日必须有明确正成交量且不是涨停锁死；卖出日必须满足 T+1、非停牌、非跌停锁死。若退出触发日不可卖，日线回测会顺延到模拟窗口内的下一可卖交易日；窗口内无可卖日时该候选跳过。
```

- [ ] **Step 6: Commit Task 5 if docs changed**

If `docs/BACKTEST_OVERVIEW.md` changed, run:

```powershell
git add docs/BACKTEST_OVERVIEW.md
git commit -m "docs: clarify a-share backtest execution boundaries"
```

If docs did not change, do not create an empty commit.

- [ ] **Step 7: Final implementation audit**

Run:

```powershell
git log --oneline --decorate -5
git status --short --branch
```

Expected:

```text
## codex/backtest-phase-a-design
```

with no uncommitted changes unless a final code review is still in progress.

## Plan Self-Review

- Spec coverage:
  - Trading-day advancement is covered by Task 1 and Task 2.
  - Buy-side ST/涨停/停牌/100 股手数 boundary is covered by existing tests plus Task 3.
  - Sell-side T+1/跌停/停牌 boundary is covered by existing tests plus Task 4.
  - API compatibility and import smoke are covered by Task 5.
- Scope:
  - No frontend, Portfolio ledger, persistence tables, QMT, or strategy logic changes are included.
- Verification:
  - Cheapest checks run first: single tests, then engine file, then service/router regression, then import smoke.
  - Real provider smoke is not part of this plan.
