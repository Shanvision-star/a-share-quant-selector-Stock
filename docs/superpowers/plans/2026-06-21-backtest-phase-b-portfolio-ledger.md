# Backtest Phase B Portfolio Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the simplified sell-date average equity curve with a minimal account-like portfolio ledger while keeping existing backtest API fields compatible.

**Architecture:** Keep Execution responsible for single-stock simulated trades and OrderIntent generation. Add PortfolioLedger behavior inside `web/backend/backtest_engine/portfolio.py`, then wire Analyzer to return `capital_summary` and `portfolio_events` alongside the existing `summary / trades / equity_curve`.

**Tech Stack:** Python, pytest, existing FastAPI backtest service.

---

## File Map

- Modify `web/backend/backtest_engine/portfolio.py`: add ledger helpers, account constraints, `build_portfolio_ledger()`, and keep `build_equity_curve()` compatible.
- Modify `web/backend/backtest_engine/analyzer.py`: call the ledger once and expose `capital_summary` / `portfolio_events`.
- Modify `tests/test_backtest_engine.py`: add portfolio-level behavior tests.
- Modify `tests/test_backtest_service.py`: add service compatibility smoke for `capital_summary`.
- Modify `docs/BACKTEST_OVERVIEW.md`: document Phase B ledger MVP and mark-to-market boundary.

## Shared Rules

- Do not modify frontend files in Phase B.
- Do not implement broker adapters, manual execution, QMT, or persistence tables.
- Keep `equity_curve[*].equity` present for current frontend compatibility.
- Keep default requests working when `initial_cash` and `max_positions` are not provided.
- Use Chinese comments only for non-obvious business boundaries.

---

### Task 1: Portfolio Ledger Core

**Files:**
- Modify: `web/backend/backtest_engine/portfolio.py`
- Modify: `tests/test_backtest_engine.py`

- [ ] **Step 1: Add failing max-position and cash-ledger tests**

Append these tests to `tests/test_backtest_engine.py`:

```python
def test_portfolio_ledger_rejects_overlapping_trade_when_max_positions_is_one():
    from web.backend.backtest_engine.portfolio import build_portfolio_ledger

    trades = [
        {
            "code": "000001",
            "buy_date": "2026-04-27",
            "sell_date": "2026-04-29",
            "buy_price": 10.0,
            "sell_price": 11.0,
            "return_pct": 10.0,
            "exits": [{"date": "2026-04-29", "price": 11.0, "portion_pct": 100.0, "reason": "holding_days"}],
        },
        {
            "code": "000002",
            "buy_date": "2026-04-28",
            "sell_date": "2026-04-30",
            "buy_price": 20.0,
            "sell_price": 21.0,
            "return_pct": 5.0,
            "exits": [{"date": "2026-04-30", "price": 21.0, "portion_pct": 100.0, "reason": "holding_days"}],
        },
    ]

    ledger = build_portfolio_ledger(
        trades,
        {"initial_cash": 100000, "position_pct": 50, "max_positions": 1, "lot_size": 100},
    )

    assert ledger["capital_summary"]["invested_count"] == 1
    assert ledger["capital_summary"]["rejected_count"] == 1
    assert ledger["capital_summary"]["final_equity"] == 105000.0
    assert ledger["capital_summary"]["final_equity"] == ledger["equity_curve"][-1]["total_equity"]
    assert any(event["event_type"] == "reject" and event["reason"] == "max_positions" for event in ledger["portfolio_events"])
    assert ledger["equity_curve"][-1]["open_positions"] == 0
```

```python
def test_portfolio_ledger_uses_cash_released_by_non_overlapping_trades():
    from web.backend.backtest_engine.portfolio import build_portfolio_ledger

    trades = [
        {
            "code": "000001",
            "buy_date": "2026-04-27",
            "sell_date": "2026-04-28",
            "buy_price": 10.0,
            "sell_price": 11.0,
            "return_pct": 10.0,
            "exits": [{"date": "2026-04-28", "price": 11.0, "portion_pct": 100.0, "reason": "holding_days"}],
        },
        {
            "code": "000002",
            "buy_date": "2026-04-29",
            "sell_date": "2026-04-30",
            "buy_price": 20.0,
            "sell_price": 18.0,
            "return_pct": -10.0,
            "exits": [{"date": "2026-04-30", "price": 18.0, "portion_pct": 100.0, "reason": "holding_days"}],
        },
    ]

    ledger = build_portfolio_ledger(
        trades,
        {"initial_cash": 100000, "position_pct": 50, "max_positions": 1, "lot_size": 100},
    )

    assert ledger["capital_summary"]["invested_count"] == 2
    assert ledger["capital_summary"]["rejected_count"] == 0
    assert ledger["capital_summary"]["final_equity"] == 100000.0
    assert ledger["capital_summary"]["cumulative_return_pct"] == 0.0
    assert ledger["capital_summary"]["final_equity"] == ledger["equity_curve"][-1]["total_equity"]
    assert ledger["capital_summary"]["final_equity"] == ledger["capital_summary"]["cash"]
    assert [row["date"] for row in ledger["equity_curve"]] == [
        "2026-04-27",
        "2026-04-28",
        "2026-04-29",
        "2026-04-30",
    ]
    assert ledger["equity_curve"][0]["cash"] == 50000.0
    assert ledger["equity_curve"][1]["cash"] == 105000.0
```

- [ ] **Step 2: Run red tests**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_portfolio_ledger_rejects_overlapping_trade_when_max_positions_is_one tests/test_backtest_engine.py::test_portfolio_ledger_uses_cash_released_by_non_overlapping_trades -q
```

Expected: FAIL because `build_portfolio_ledger` does not exist.

- [ ] **Step 3: Implement minimal ledger**

In `web/backend/backtest_engine/portfolio.py`, keep the module docstring and add these public helpers:

```python
DEFAULT_INITIAL_CASH = 100000.0


def build_portfolio_ledger(trades: list[dict], params: dict | None = None) -> dict:
    ...


def build_equity_curve(trades: list[dict], params: dict | None = None) -> tuple[list[dict], float, float]:
    ledger = build_portfolio_ledger(trades, params)
    summary = ledger["capital_summary"]
    return ledger["equity_curve"], summary["cumulative_return_pct"], summary["max_drawdown_pct"]
```

Implementation requirements:

- Parse `initial_cash`, `position_pct`, `max_positions`, `max_weight_per_code`, `lot_size`.
- Sort trades by `(buy_date, code, strategy_name)`.
- Before each buy, process pending sell events with `sell_date <= buy_date`.
- Process sells before buys on the same date.
- Reject a trade with event reason `max_positions` if open positions are at the limit.
- Reject a trade with event reason `cash_shortage` if target quantity cannot be bought.
- For quantity, use `trade["quantity"]` when positive; otherwise calculate `floor(target_cash / buy_price / lot_size) * lot_size`.
- Keep `equity_curve[*].equity` as normalized `total_equity / initial_cash`.
- Keep `capital_summary.final_equity`, `capital_summary.cash + capital_summary.market_value`, and `equity_curve[-1].total_equity` on the same actual account-ledger basis; do not synthesize old return-curve equity for the summary.
- Round money fields to 2 decimals and percentages to 2 decimals.

- [ ] **Step 4: Run green tests**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_portfolio_ledger_rejects_overlapping_trade_when_max_positions_is_one tests/test_backtest_engine.py::test_portfolio_ledger_uses_cash_released_by_non_overlapping_trades -q
```

Expected: PASS.

- [ ] **Step 5: Run portfolio-related regression**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```powershell
git add web/backend/backtest_engine/portfolio.py tests/test_backtest_engine.py
git commit -m "feat: add backtest portfolio ledger"
```

---

### Task 2: Analyzer And Result Contract

**Files:**
- Modify: `web/backend/backtest_engine/analyzer.py`
- Modify: `tests/test_backtest_engine.py`

- [ ] **Step 1: Add failing analyzer contract test**

Append this test to `tests/test_backtest_engine.py`:

```python
def test_daily_engine_returns_capital_summary_and_portfolio_events():
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
            {"date": pd.Timestamp("2026-04-28"), "open": 11.0, "high": 11.2, "low": 10.9, "close": 11.0, "volume": 1000},
        ]
    )
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({"000001": frame}),
    )

    result = engine.run_daily(
        _default_params(initial_cash=100000, position_pct=50, max_positions=1)
    )

    assert result["capital_summary"]["initial_cash"] == 100000.0
    assert result["capital_summary"]["invested_count"] == 1
    assert result["capital_summary"]["final_equity"] == 105000.0
    assert result["summary"]["cumulative_return_pct"] == 5.0
    assert result["summary"]["max_drawdown_pct"] == 0.0
    assert result["portfolio_events"][0]["event_type"] == "buy"
    assert result["portfolio_events"][-1]["event_type"] == "sell"
    assert "equity" in result["equity_curve"][0]
```

- [ ] **Step 2: Run red test**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_daily_engine_returns_capital_summary_and_portfolio_events -q
```

Expected: FAIL because `capital_summary` and `portfolio_events` are not returned by `build_result`.

- [ ] **Step 3: Wire analyzer to ledger**

In `web/backend/backtest_engine/analyzer.py`:

- Replace `from web.backend.backtest_engine.portfolio import build_equity_curve` with `build_portfolio_ledger`.
- Build ledger once:

```python
portfolio = build_portfolio_ledger(trades, params.to_mapping())
equity_curve = portfolio["equity_curve"]
capital_summary = portfolio["capital_summary"]
portfolio_events = portfolio["portfolio_events"]
cumulative_return = capital_summary["cumulative_return_pct"]
max_drawdown = capital_summary["max_drawdown_pct"]
```

- Return `capital_summary` and `portfolio_events` in the final dict.
- Keep all existing summary fields that are not portfolio return/drawdown related.

- [ ] **Step 4: Run green test**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py::test_daily_engine_returns_capital_summary_and_portfolio_events -q
```

Expected: PASS.

- [ ] **Step 5: Run engine regression**

Run:

```powershell
python -m pytest tests/test_backtest_engine.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add web/backend/backtest_engine/analyzer.py tests/test_backtest_engine.py
git commit -m "feat: expose portfolio ledger in backtest results"
```

---

### Task 3: Service Compatibility And Per-Code Cap

**Files:**
- Modify: `tests/test_backtest_service.py`
- Modify: `tests/test_backtest_engine.py`
- Modify: `web/backend/backtest_engine/portfolio.py`

- [ ] **Step 1: Add service compatibility test**

Append this test to `tests/test_backtest_service.py`:

```python
def test_backtest_service_returns_capital_summary_with_default_cash(monkeypatch):
    """旧请求不传 initial_cash 时，Phase B 账本字段也应存在。"""
    monkeypatch.setattr(
        backtest_service.manual_selection_service,
        "list_selections",
        lambda start_date, end_date: [
            {
                "selection_date": "2026-04-24",
                "code": "000001",
                "name": "平安银行",
                "strategy_name": "manual",
                "source_signal_date": "2026-04-24",
                "source_trade_date": "2026-04-24",
            }
        ],
    )
    monkeypatch.setattr(
        backtest_service,
        "_load_price_frame",
        lambda code: pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-24"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-27"), "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.0, "volume": 1000},
                {"date": pd.Timestamp("2026-04-28"), "open": 10.5, "high": 10.8, "low": 10.4, "close": 10.5, "volume": 1000},
            ]
        ),
    )

    result = backtest_service.run_backtest(
        {
            "start_date": "2026-04-24",
            "end_date": "2026-04-24",
            "source": "manual",
            "strategy": "all",
            "selected_codes": [],
            "selected_candidates": [],
            "input_codes": [],
            "holding_days": 1,
            "buy_offset_days": 1,
            "buy_price": "open",
            "sell_price": "close",
            "fee_rate": 0,
            "slippage_rate": 0,
            "take_profit_pct": 0,
            "stop_loss_pct": 0,
            "max_positions_per_day": 20,
            "codes_fallback_to_start_date": False,
            "profit_run_enabled": False,
            "enable_no_gain_exit": False,
            "exit_on_bull_bear_break": False,
            "exit_on_short_trend_break": False,
            "exit_on_short_trend_drawdown": False,
        }
    )

    assert result["capital_summary"]["initial_cash"] == 100000.0
    assert result["capital_summary"]["invested_count"] == 1
    assert result["capital_summary"]["trade_count"] == 1
    assert result["equity_curve"][-1]["total_equity"] > 100000.0
```

- [ ] **Step 2: Add per-code cap test**

Append this test to `tests/test_backtest_engine.py`:

```python
def test_portfolio_ledger_rejects_trade_above_per_code_weight_cap():
    from web.backend.backtest_engine.portfolio import build_portfolio_ledger

    trades = [
        {
            "code": "000001",
            "buy_date": "2026-04-27",
            "sell_date": "2026-04-28",
            "buy_price": 10.0,
            "sell_price": 11.0,
            "return_pct": 10.0,
            "weight": 0.5,
            "exits": [{"date": "2026-04-28", "price": 11.0, "portion_pct": 100.0, "reason": "holding_days"}],
        }
    ]

    ledger = build_portfolio_ledger(
        trades,
        {"initial_cash": 100000, "position_pct": 50, "max_positions": 5, "max_weight_per_code": 20},
    )

    assert ledger["capital_summary"]["invested_count"] == 0
    assert ledger["capital_summary"]["rejected_count"] == 1
    assert ledger["capital_summary"]["final_equity"] == 100000.0
    assert ledger["portfolio_events"][0]["reason"] == "max_weight_per_code"
```

- [ ] **Step 3: Run red tests**

Run:

```powershell
python -m pytest tests/test_backtest_service.py::test_backtest_service_returns_capital_summary_with_default_cash tests/test_backtest_engine.py::test_portfolio_ledger_rejects_trade_above_per_code_weight_cap -q
```

Expected: service test may pass if Task 2 already wired defaults; per-code cap should fail until rejection reason is implemented exactly.

- [ ] **Step 4: Implement compatibility and cap behavior**

In `portfolio.py`:

- Default `initial_cash` to `100000.0`.
- Default `max_positions` from `params["max_positions"]`, then `params["max_positions_per_day"]`, then `20`.
- If `max_weight_per_code > 0` and a trade target weight is greater than the cap, reject with reason `max_weight_per_code`.
- Keep `trade_count` as raw input trade count and `invested_count` as accepted count.

- [ ] **Step 5: Run green tests**

Run:

```powershell
python -m pytest tests/test_backtest_service.py tests/test_backtest_engine.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add web/backend/backtest_engine/portfolio.py tests/test_backtest_engine.py tests/test_backtest_service.py
git commit -m "fix: keep portfolio ledger compatible with service defaults"
```

---

### Task 4: Documentation And Regression Closeout

**Files:**
- Modify: `docs/BACKTEST_OVERVIEW.md`

- [ ] **Step 1: Update backtest overview**

Add this section after “组合策略模式” and before “可复现历史记录”:

```markdown
## 5. 组合资金账本（Phase B）

Phase B 将回测资金曲线从“按卖出日平均收益”升级为最小组合账本。账本从现有
`trades` 推导买入占用、卖出回款、现金、持仓市值、逐日权益、最大回撤和组合事件。
当前 MVP 不做持仓期间每日行情估值；`market_value` 以成本或已知退出事件推进，完整
mark-to-market 估值留给后续 DataPortal 估值层。

结果会继续保留 `summary / trades / equity_curve`，并新增 `capital_summary` 与
`portfolio_events`。`OrderIntent` 仍然只是下单意图，不会触发模拟盘或真实券商。
```

Renumber following sections:

- `可复现历史记录（Phase C）` becomes section 6.
- `OrderIntent 与跟踪联动` becomes section 7.
- `相关文档` becomes section 8.

- [ ] **Step 2: Run focused regression**

Run:

```powershell
python -m pytest tests/test_trading_calendar.py tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check 0115aa1..HEAD
git status --short --branch
```

Expected: all tests pass, import prints `import-ok`, diff check has no output.

- [ ] **Step 3: Commit docs**

```powershell
git add docs/BACKTEST_OVERVIEW.md
git commit -m "docs: document phase b portfolio ledger"
```

---

## Final Review

After all tasks:

```powershell
python -m pytest tests/test_trading_calendar.py tests/test_backtest_engine.py tests/test_backtest_service.py tests/test_backtest_job_service.py tests/test_backtest_router_async.py -q
python -c "from web.backend.main import app; print('import-ok')"
git diff --check 0115aa1..HEAD
git status --short --branch
```

Dispatch final code reviewer for `0115aa1..HEAD`.
