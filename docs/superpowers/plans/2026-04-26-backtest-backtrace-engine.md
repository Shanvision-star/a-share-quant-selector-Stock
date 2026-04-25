# Backtest Backtrace Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified backtrace/backtest engine that powers historical single-stock diagnosis, full-market historical signal scans, existing candidate backtests, CLI commands, Web API endpoints, async progress tracking, and SQLite result history.

**Architecture:** Add a focused `utils\backtest_engine\` package for core computation and keep CLI/Web/API layers as thin adapters. The engine reads local CSV data with strict historical cutoffs, executes current `BaseStrategy` instances from `StrategyRegistry`, simulates trades from normalized signals, records diagnostics instead of hiding skipped cases, and persists runs/signals/trades/equity points into the existing `data\web_strategy_cache.db`.

**Tech Stack:** Python 3, pandas, unittest, FastAPI, Pydantic, SQLite, existing `CSVManager`, `StrategyRegistry`, and `strategy_result_repository`.

---

## File Structure

- Create `utils\backtest_engine\__init__.py`: package exports for core engine entry points.
- Create `utils\backtest_engine\models.py`: dataclasses and helpers for diagnostics, signals, trades, summaries, and default params.
- Create `utils\backtest_engine\data_provider.py`: CSV loading, date normalization, strict cutoff, and stock-name lookup.
- Create `utils\backtest_engine\signal_runner.py`: strategy filtering, strategy execution, signal normalization, and per-strategy diagnostics.
- Create `utils\backtest_engine\simulator.py`: trade simulation and equity curve calculation extracted from current Web backtest service behavior.
- Create `utils\backtest_engine\repository.py`: SQLite persistence for backtest runs, signals, trades, equity points, and diagnostics.
- Create `utils\backtest_engine\engine.py`: orchestration functions for single-stock diagnosis, candidate backtest, and full-market scan.
- Create `web\backend\routers\backtrace.py`: new diagnosis and full-market run endpoints.
- Modify `web\backend\routers\backtest.py`: keep request model but delegate to the unified engine.
- Modify `web\backend\services\backtest_service.py`: convert to compatibility wrapper around the engine.
- Modify `web\backend\services\sqlite_service.py`: add backtest result tables and indexes.
- Modify `web\backend\main.py`: register the new backtrace router.
- Modify `main.py`: upgrade `backtrace` command behavior and add all-market historical scan mode.
- Modify `README.md`: document CLI and API behavior at a high level.
- Add tests under `web\backend\tests\`: focused unittest modules for provider, signal runner, simulator, repository, engine, API, and CLI command behavior.

---

### Task 1: Core Models and Data Provider

**Files:**
- Create: `utils\backtest_engine\__init__.py`
- Create: `utils\backtest_engine\models.py`
- Create: `utils\backtest_engine\data_provider.py`
- Test: `web\backend\tests\test_backtest_engine_data_provider.py`

- [ ] **Step 1: Write failing data provider tests**

Create `web\backend\tests\test_backtest_engine_data_provider.py`:

```python
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from utils.backtest_engine.data_provider import HistoricalDataProvider


class HistoricalDataProviderTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        pd.DataFrame(
            [
                {"date": "2026-03-30", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "1000"},
                {"date": "2026-04-01", "open": "11", "high": "12", "low": "10", "close": "11.5", "volume": "1100"},
                {"date": "2026-04-02", "open": "12", "high": "13", "low": "11", "close": "12.5", "volume": "1200"},
            ]
        ).to_csv(self.data_dir / "000001.csv", index=False, encoding="utf-8")
        (self.data_dir / "stock_names.json").write_text('{"000001": "平安银行"}', encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_until_strictly_cuts_future_rows(self):
        provider = HistoricalDataProvider(str(self.data_dir))
        frame, diagnostics = provider.load_until("000001", "2026-04-01")

        self.assertEqual(diagnostics, [])
        self.assertEqual(frame["date"].dt.strftime("%Y-%m-%d").tolist(), ["2026-03-30", "2026-04-01"])
        self.assertEqual(frame.iloc[-1]["close"], 11.5)

    def test_load_until_reports_missing_file(self):
        provider = HistoricalDataProvider(str(self.data_dir))
        frame, diagnostics = provider.load_until("000002", "2026-04-01")

        self.assertTrue(frame.empty)
        self.assertEqual(diagnostics[0]["type"], "missing_data")
        self.assertEqual(diagnostics[0]["code"], "000002")

    def test_load_until_reports_missing_target_date(self):
        provider = HistoricalDataProvider(str(self.data_dir))
        frame, diagnostics = provider.load_until("000001", "2026-03-31")

        self.assertTrue(frame.empty)
        self.assertEqual(diagnostics[0]["type"], "date_not_found")
        self.assertEqual(diagnostics[0]["date"], "2026-03-31")

    def test_stock_name_uses_json_cache(self):
        provider = HistoricalDataProvider(str(self.data_dir))
        self.assertEqual(provider.stock_name("000001"), "平安银行")
        self.assertEqual(provider.stock_name("000002"), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_data_provider -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'utils.backtest_engine'`.

- [ ] **Step 3: Add models module**

Create `utils\backtest_engine\__init__.py`:

```python
"""Unified historical backtrace and backtest engine."""
```

Create `utils\backtest_engine\models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_text() -> str:
    return datetime.now().strftime(DATETIME_FORMAT)


def diagnostic(
    diagnostic_type: str,
    code: str = "",
    date: str = "",
    stage: str = "",
    reason: str = "",
    strategy_name: str = "",
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    item = {
        "type": diagnostic_type,
        "code": code,
        "date": date,
        "stage": stage,
        "reason": reason,
    }
    if strategy_name:
        item["strategy_name"] = strategy_name
    if payload:
        item["payload"] = payload
    return item


def default_summary() -> dict[str, Any]:
    return {
        "candidate_count": 0,
        "signal_count": 0,
        "trade_count": 0,
        "skipped_count": 0,
        "strategy_error_count": 0,
        "win_rate_pct": 0.0,
        "avg_return_pct": 0.0,
        "cumulative_return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "avg_hold_days": 0.0,
        "best_return_pct": 0.0,
        "worst_return_pct": 0.0,
    }


@dataclass
class EngineParams:
    start_date: str
    end_date: str
    source: str = "strategy"
    strategy: str = "all"
    selected_codes: list[str] = field(default_factory=list)
    selected_candidates: list[dict[str, Any]] = field(default_factory=list)
    input_codes: list[str] = field(default_factory=list)
    holding_days: int = 5
    buy_offset_days: int = 1
    buy_price: str = "open"
    sell_price: str = "close"
    fee_rate: float = 0.0003
    slippage_rate: float = 0.0005
    take_profit_pct: float = 0.0
    stop_loss_pct: float = 0.0
    max_positions_per_day: int = 10
    profit_run_enabled: bool = True
    profit_trigger_pct: float = 5.0
    profit_step_pct: float = 10.0
    profit_sell_pct: float = 25.0
    hold_above_short_trend_after_trigger: bool = True
    enable_no_gain_exit: bool = True
    no_gain_days: int = 3
    exit_on_bull_bear_break: bool = True
    exit_on_short_trend_break: bool = True
    short_trend_break_days: int = 2
    exit_on_short_trend_drawdown: bool = True
    short_trend_drawdown_pct: float = 5.0
    save_result: bool = True

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "EngineParams":
        allowed = cls.__dataclass_fields__.keys()
        filtered = {key: values[key] for key in allowed if key in values}
        if "start_date" not in filtered:
            filtered["start_date"] = values.get("date", "")
        if "end_date" not in filtered:
            filtered["end_date"] = values.get("date", filtered["start_date"])
        return cls(**filtered)
```

- [ ] **Step 4: Add the data provider**

Create `utils\backtest_engine\data_provider.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from utils.backtest_engine.models import diagnostic
from utils.csv_manager import CSVManager


class HistoricalDataProvider:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.csv_manager = CSVManager(str(self.data_dir))
        self._stock_names: dict[str, str] | None = None

    def stock_name(self, code: str) -> str:
        if self._stock_names is None:
            names_path = self.data_dir / "stock_names.json"
            if names_path.exists():
                with open(names_path, "r", encoding="utf-8") as file:
                    self._stock_names = json.load(file)
            else:
                self._stock_names = {}
        return self._stock_names.get(code, "")

    def list_all_stocks(self) -> list[str]:
        return self.csv_manager.list_all_stocks()

    def load_full(self, code: str) -> tuple[pd.DataFrame, list[dict]]:
        try:
            frame = self.csv_manager.read_stock(code)
        except FileNotFoundError:
            return pd.DataFrame(), [
                diagnostic("missing_data", code=code, stage="load_full", reason="stock CSV file not found")
            ]
        except Exception as exc:
            return pd.DataFrame(), [
                diagnostic("missing_data", code=code, stage="load_full", reason=str(exc))
            ]
        return self._normalize_frame(code, frame, stage="load_full")

    def load_until(self, code: str, target_date: str) -> tuple[pd.DataFrame, list[dict]]:
        frame, diagnostics = self.load_full(code)
        if diagnostics:
            return frame, diagnostics

        target_ts = pd.to_datetime(target_date)
        matched = frame["date"].dt.strftime("%Y-%m-%d") == target_date
        if not matched.any():
            return pd.DataFrame(), [
                diagnostic(
                    "date_not_found",
                    code=code,
                    date=target_date,
                    stage="load_until",
                    reason="target date does not exist in stock CSV",
                )
            ]
        return frame[frame["date"] <= target_ts].copy().reset_index(drop=True), []

    def _normalize_frame(self, code: str, frame: pd.DataFrame, stage: str) -> tuple[pd.DataFrame, list[dict]]:
        if frame is None or frame.empty:
            return pd.DataFrame(), [
                diagnostic("missing_data", code=code, stage=stage, reason="stock CSV is empty")
            ]
        normalized = frame.copy()
        if "date" not in normalized.columns:
            return pd.DataFrame(), [
                diagnostic("missing_data", code=code, stage=stage, reason="stock CSV has no date column")
            ]
        normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
        for column in ("open", "high", "low", "close"):
            if column not in normalized.columns:
                return pd.DataFrame(), [
                    diagnostic("invalid_price", code=code, stage=stage, reason=f"stock CSV has no {column} column")
                ]
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        normalized = (
            normalized.dropna(subset=["date", "open", "high", "low", "close"])
            .sort_values("date")
            .reset_index(drop=True)
        )
        if normalized.empty:
            return pd.DataFrame(), [
                diagnostic("invalid_price", code=code, stage=stage, reason="no valid OHLC rows after normalization")
            ]
        return normalized, []
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_data_provider -v
```

Expected: PASS all 4 tests.

- [ ] **Step 6: Commit**

```powershell
git add utils\backtest_engine\__init__.py utils\backtest_engine\models.py utils\backtest_engine\data_provider.py web\backend\tests\test_backtest_engine_data_provider.py
git commit -m "feat: add historical data provider" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Strategy Signal Runner

**Files:**
- Create: `utils\backtest_engine\signal_runner.py`
- Test: `web\backend\tests\test_backtest_engine_signal_runner.py`

- [ ] **Step 1: Write failing signal runner tests**

Create `web\backend\tests\test_backtest_engine_signal_runner.py`:

```python
import unittest

import pandas as pd

from strategy.base_strategy import BaseStrategy
from utils.backtest_engine.signal_runner import StrategySignalRunner


class MatchingStrategy(BaseStrategy):
    def __init__(self, params=None):
        super().__init__("MatchingStrategy", params=params)

    def calculate_indicators(self, df):
        result = df.copy()
        result["calculated"] = True
        return result

    def select_stocks(self, df, stock_name=""):
        return [
            {
                "date": df.iloc[-1]["date"].strftime("%Y-%m-%d"),
                "category": "unit",
                "reason": f"matched {stock_name}",
                "similarity_score": 88.5,
                "trigger_price": float(df.iloc[-1]["close"]),
            }
        ]


class ErrorStrategy(BaseStrategy):
    def __init__(self, params=None):
        super().__init__("ErrorStrategy", params=params)

    def calculate_indicators(self, df):
        raise RuntimeError("indicator boom")

    def select_stocks(self, df, stock_name=""):
        return []


class FakeRegistry:
    def get_registered_strategies(self):
        return {
            "MatchingStrategy": MatchingStrategy(),
            "ErrorStrategy": ErrorStrategy(),
        }


class StrategySignalRunnerTest(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-03-30"), "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5},
                {"date": pd.Timestamp("2026-04-01"), "open": 11.0, "high": 12.0, "low": 10.0, "close": 11.5},
            ]
        )

    def test_runs_all_registered_strategies_and_normalizes_signals(self):
        runner = StrategySignalRunner(FakeRegistry())
        signals, diagnostics = runner.run_for_stock("000001", "平安银行", self.frame, "all")

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["code"], "000001")
        self.assertEqual(signals[0]["strategy_name"], "MatchingStrategy")
        self.assertEqual(signals[0]["signal_date"], "2026-04-01")
        self.assertEqual(signals[0]["similarity_score"], 88.5)
        self.assertEqual(diagnostics[0]["type"], "strategy_errors")
        self.assertEqual(diagnostics[0]["strategy_name"], "ErrorStrategy")

    def test_strategy_filter_runs_only_requested_strategy(self):
        runner = StrategySignalRunner(FakeRegistry())
        signals, diagnostics = runner.run_for_stock("000001", "平安银行", self.frame, "MatchingStrategy")

        self.assertEqual(len(signals), 1)
        self.assertEqual(diagnostics, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_signal_runner -v
```

Expected: FAIL with `ModuleNotFoundError` for `utils.backtest_engine.signal_runner`.

- [ ] **Step 3: Implement strategy signal runner**

Create `utils\backtest_engine\signal_runner.py`:

```python
from __future__ import annotations

from typing import Any

import pandas as pd

from strategy.strategy_registry import get_registry
from utils.backtest_engine.models import diagnostic


class StrategySignalRunner:
    def __init__(self, registry=None):
        self.registry = registry or get_registry("config/strategy_params.yaml")

    def run_for_stock(
        self,
        code: str,
        name: str,
        frame: pd.DataFrame,
        strategy_filter: str = "all",
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        signals: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for strategy_name, strategy in self._iter_strategies(strategy_filter):
            try:
                result = strategy.analyze_stock(code, name, frame)
            except Exception as exc:
                diagnostics.append(
                    diagnostic(
                        "strategy_errors",
                        code=code,
                        date=self._last_date(frame),
                        stage="strategy",
                        reason=str(exc),
                        strategy_name=strategy_name,
                    )
                )
                continue
            if not result:
                continue
            for raw_signal in result.get("signals", []):
                signals.append(self._normalize_signal(code, name, strategy_name, raw_signal, frame))
        return signals, diagnostics

    def _iter_strategies(self, strategy_filter: str):
        registered = self.registry.get_registered_strategies()
        if strategy_filter and strategy_filter != "all":
            strategy = registered.get(strategy_filter)
            if strategy is not None:
                yield strategy_filter, strategy
            return
        for strategy_name, strategy in registered.items():
            yield strategy_name, strategy

    def _normalize_signal(
        self,
        code: str,
        name: str,
        strategy_name: str,
        raw_signal: dict[str, Any],
        frame: pd.DataFrame,
    ) -> dict[str, Any]:
        signal_date = str(raw_signal.get("date") or self._last_date(frame))
        close = raw_signal.get("close", raw_signal.get("trigger_price"))
        if close is None and not frame.empty:
            close = float(frame.iloc[-1].get("close", 0.0))
        return {
            "code": code,
            "name": name,
            "strategy_name": strategy_name,
            "strategy_filter": strategy_name,
            "trade_date": self._last_date(frame),
            "signal_date": signal_date,
            "category": str(raw_signal.get("category", "")),
            "trigger_price": raw_signal.get("trigger_price"),
            "close": close,
            "j_value": raw_signal.get("j_value"),
            "similarity_score": raw_signal.get("similarity_score"),
            "reason": str(raw_signal.get("reason", "")),
            "signal": raw_signal,
        }

    def _last_date(self, frame: pd.DataFrame) -> str:
        if frame is None or frame.empty:
            return ""
        value = frame.iloc[-1]["date"]
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_signal_runner -v
```

Expected: PASS all 2 tests.

- [ ] **Step 5: Commit**

```powershell
git add utils\backtest_engine\signal_runner.py web\backend\tests\test_backtest_engine_signal_runner.py
git commit -m "feat: add strategy signal runner" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Trade Simulator

**Files:**
- Create: `utils\backtest_engine\simulator.py`
- Test: `web\backend\tests\test_backtest_engine_simulator.py`

- [ ] **Step 1: Write failing simulator tests**

Create `web\backend\tests\test_backtest_engine_simulator.py`:

```python
import unittest

import pandas as pd

from utils.backtest_engine.models import EngineParams
from utils.backtest_engine.simulator import BacktestSimulator


class BacktestSimulatorTest(unittest.TestCase):
    def make_frame(self):
        return pd.DataFrame(
            [
                {"date": pd.Timestamp("2026-04-01"), "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "short_term_trend": 9.5, "bull_bear_line": 9.0},
                {"date": pd.Timestamp("2026-04-02"), "open": 10.4, "high": 11.5, "low": 10.1, "close": 11.0, "short_term_trend": 9.8, "bull_bear_line": 9.1},
                {"date": pd.Timestamp("2026-04-03"), "open": 11.1, "high": 12.6, "low": 10.9, "close": 12.0, "short_term_trend": 10.0, "bull_bear_line": 9.4},
                {"date": pd.Timestamp("2026-04-07"), "open": 12.1, "high": 12.2, "low": 10.5, "close": 10.6, "short_term_trend": 11.0, "bull_bear_line": 10.0},
            ]
        )

    def test_simulates_trade_with_buy_offset_and_costs(self):
        params = EngineParams.from_dict(
            {
                "start_date": "2026-04-01",
                "end_date": "2026-04-07",
                "holding_days": 2,
                "buy_offset_days": 1,
                "buy_price": "open",
                "sell_price": "close",
                "fee_rate": 0.001,
                "slippage_rate": 0.001,
                "profit_run_enabled": False,
            }
        )
        candidate = {"code": "000001", "name": "平安银行", "strategy_name": "Unit", "signal_date": "2026-04-01", "trade_date": "2026-04-01"}

        trade, diagnostics = BacktestSimulator().simulate(candidate, self.make_frame(), params)

        self.assertEqual(diagnostics, [])
        self.assertEqual(trade["buy_date"], "2026-04-02")
        self.assertEqual(trade["sell_date"], "2026-04-07")
        self.assertEqual(trade["buy_price"], 10.4)
        self.assertEqual(trade["exit_reason"], "holding_days")
        self.assertGreater(trade["return_pct"], 0)

    def test_reports_out_of_range_when_buy_date_missing(self):
        params = EngineParams.from_dict(
            {
                "start_date": "2026-04-01",
                "end_date": "2026-04-01",
                "holding_days": 2,
                "buy_offset_days": 3,
            }
        )
        candidate = {"code": "000001", "name": "平安银行", "strategy_name": "Unit", "signal_date": "2026-04-01", "trade_date": "2026-04-01"}

        trade, diagnostics = BacktestSimulator().simulate(candidate, self.make_frame(), params)

        self.assertIsNone(trade)
        self.assertEqual(diagnostics[0]["type"], "out_of_range")
        self.assertEqual(diagnostics[0]["stage"], "buy")

    def test_builds_equity_curve_and_summary(self):
        trades = [
            {"sell_date": "2026-04-02", "return_pct": 10.0, "hold_days": 1},
            {"sell_date": "2026-04-03", "return_pct": -5.0, "hold_days": 2},
        ]

        curve, summary = BacktestSimulator().summarize(trades, candidate_count=3, signal_count=3, diagnostics=[])

        self.assertEqual(len(curve), 2)
        self.assertEqual(summary["candidate_count"], 3)
        self.assertEqual(summary["trade_count"], 2)
        self.assertEqual(summary["win_rate_pct"], 50.0)
        self.assertEqual(summary["skipped_count"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_simulator -v
```

Expected: FAIL with `ModuleNotFoundError` for `utils.backtest_engine.simulator`.

- [ ] **Step 3: Implement simulator**

Create `utils\backtest_engine\simulator.py` by moving the trade simulation behavior from `web\backend\services\backtest_service.py` into this focused class:

```python
from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

import pandas as pd

from utils.backtest_engine.models import EngineParams, default_summary, diagnostic
from utils.technical import calculate_zhixing_trend


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number


class BacktestSimulator:
    def prepare_price_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        prepared = frame.copy()
        prepared["date"] = pd.to_datetime(prepared["date"])
        for column in ("open", "high", "low", "close"):
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
        prepared = prepared.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        if "short_term_trend" not in prepared.columns or "bull_bear_line" not in prepared.columns:
            trend = calculate_zhixing_trend(prepared)
            prepared["short_term_trend"] = trend["short_term_trend"]
            prepared["bull_bear_line"] = trend["bull_bear_line"]
        return prepared

    def simulate(
        self,
        candidate: dict[str, Any],
        frame: pd.DataFrame,
        params: EngineParams,
    ) -> tuple[Optional[dict[str, Any]], list[dict[str, Any]]]:
        if not candidate.get("code") or not candidate.get("signal_date"):
            return None, [diagnostic("simulation_skipped", stage="candidate", reason="candidate has no code or signal_date")]
        prepared = self.prepare_price_frame(frame)
        if prepared.empty:
            return None, [diagnostic("invalid_price", code=candidate["code"], stage="simulate", reason="empty price frame")]
        signal_index = self._find_signal_index(prepared, candidate["signal_date"])
        if signal_index is None:
            return None, [diagnostic("date_not_found", code=candidate["code"], date=candidate["signal_date"], stage="signal", reason="signal date not found")]
        buy_index = signal_index + int(params.buy_offset_days)
        end_bound_index = self._end_bound_index(prepared, params.end_date)
        if buy_index >= len(prepared) or end_bound_index is None or buy_index > end_bound_index:
            return None, [diagnostic("out_of_range", code=candidate["code"], date=candidate["signal_date"], stage="buy", reason="buy date is outside available backtest range")]
        target_exit_index = min(end_bound_index, buy_index + max(1, int(params.holding_days)))
        buy_row = prepared.iloc[buy_index]
        buy_price = self._pick_price(buy_row, params.buy_price)
        if buy_price <= 0:
            return None, [diagnostic("invalid_price", code=candidate["code"], date=buy_row["date"].strftime("%Y-%m-%d"), stage="buy", reason="buy price is invalid")]

        exits = self._collect_exits(prepared, buy_index, target_exit_index, buy_price, params)
        if not exits:
            return None, [diagnostic("simulation_skipped", code=candidate["code"], stage="exit", reason="no exit could be generated")]

        gross_return = sum((exit_item["price"] / buy_price - 1) * (exit_item["portion_pct"] / 100) for exit_item in exits)
        total_sell_cost = sum((exit_item["portion_pct"] / 100) * (params.fee_rate + params.slippage_rate) for exit_item in exits)
        net_return = gross_return - (params.fee_rate + params.slippage_rate) - total_sell_cost
        sell_date = exits[-1]["date"]
        sell_index = int(prepared.index[prepared["date"] == pd.to_datetime(sell_date)][-1])
        return {
            "code": candidate["code"],
            "name": candidate.get("name", ""),
            "strategy_name": candidate.get("strategy_name", ""),
            "source": candidate.get("source", ""),
            "signal_date": candidate.get("signal_date"),
            "trade_date": candidate.get("trade_date"),
            "buy_date": buy_row["date"].strftime("%Y-%m-%d"),
            "sell_date": sell_date,
            "buy_price": round(buy_price, 3),
            "sell_price": exits[-1]["price"],
            "hold_days": max(1, sell_index - buy_index),
            "gross_return_pct": round(gross_return * 100, 2),
            "return_pct": round(net_return * 100, 2),
            "exit_reason": exits[-1]["reason"],
            "exits": exits,
        }, []

    def summarize(
        self,
        trades: list[dict[str, Any]],
        candidate_count: int,
        signal_count: int,
        diagnostics: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        curve, cumulative_return, max_drawdown = self._build_equity_curve(trades)
        summary = default_summary()
        trade_count = len(trades)
        win_count = sum(1 for trade in trades if trade["return_pct"] > 0)
        summary.update(
            {
                "candidate_count": candidate_count,
                "signal_count": signal_count,
                "trade_count": trade_count,
                "skipped_count": max(candidate_count - trade_count, 0),
                "strategy_error_count": sum(1 for item in diagnostics if item.get("type") == "strategy_errors"),
                "win_rate_pct": round((win_count / trade_count * 100) if trade_count else 0.0, 2),
                "avg_return_pct": round(sum(trade["return_pct"] for trade in trades) / trade_count if trade_count else 0.0, 2),
                "cumulative_return_pct": round(cumulative_return, 2),
                "max_drawdown_pct": round(max_drawdown, 2),
                "avg_hold_days": round(sum(trade["hold_days"] for trade in trades) / trade_count if trade_count else 0.0, 1),
                "best_return_pct": round(max((trade["return_pct"] for trade in trades), default=0.0), 2),
                "worst_return_pct": round(min((trade["return_pct"] for trade in trades), default=0.0), 2),
            }
        )
        return curve, summary

    def _collect_exits(self, frame: pd.DataFrame, buy_index: int, target_exit_index: int, buy_price: float, params: EngineParams) -> list[dict[str, Any]]:
        exits: list[dict[str, Any]] = []
        remaining = 1.0
        runner_triggered = False
        next_profit_ladder_pct = params.profit_trigger_pct + params.profit_step_pct
        short_break_streak = 0
        for index in range(buy_index + 1, target_exit_index + 1):
            row = frame.iloc[index]
            low_price = safe_float(row.get("low"))
            high_price = safe_float(row.get("high"))
            close_price = safe_float(row.get("close"))
            short_line = safe_float(row.get("short_term_trend"))
            bull_bear_line = safe_float(row.get("bull_bear_line"))
            short_break_streak = short_break_streak + 1 if short_line > 0 and close_price < short_line else 0
            if params.stop_loss_pct > 0 and low_price <= buy_price * (1 - params.stop_loss_pct / 100):
                self._append_exit(exits, row, buy_price * (1 - params.stop_loss_pct / 100), remaining, "fixed_stop_loss", params)
                remaining = 0
                break
            if params.enable_no_gain_exit and index - buy_index >= params.no_gain_days and close_price <= buy_price:
                self._append_exit(exits, row, close_price, remaining, "no_gain_exit", params)
                remaining = 0
                break
            if params.exit_on_bull_bear_break and bull_bear_line > 0 and close_price < bull_bear_line:
                self._append_exit(exits, row, close_price, remaining, "bull_bear_break", params)
                remaining = 0
                break
            if params.exit_on_short_trend_drawdown and short_line > 0 and close_price <= short_line * (1 - params.short_trend_drawdown_pct / 100):
                self._append_exit(exits, row, close_price, remaining, "short_trend_drawdown", params)
                remaining = 0
                break
            if params.exit_on_short_trend_break and short_break_streak >= params.short_trend_break_days:
                self._append_exit(exits, row, close_price, remaining, "short_trend_break_days", params)
                remaining = 0
                break
            current_high_pct = (high_price / buy_price - 1) * 100 if buy_price > 0 else 0.0
            if params.profit_run_enabled and params.profit_trigger_pct > 0 and current_high_pct >= params.profit_trigger_pct:
                runner_triggered = True
            if runner_triggered and params.profit_step_pct > 0 and params.profit_sell_pct > 0:
                while remaining > 0 and current_high_pct >= next_profit_ladder_pct:
                    portion = min(remaining, params.profit_sell_pct / 100)
                    self._append_exit(exits, row, buy_price * (1 + next_profit_ladder_pct / 100), portion, f"profit_ladder_{next_profit_ladder_pct:.1f}pct", params)
                    remaining = max(0.0, remaining - portion)
                    next_profit_ladder_pct += params.profit_step_pct
            if runner_triggered and params.hold_above_short_trend_after_trigger and short_line > 0 and close_price < short_line:
                self._append_exit(exits, row, close_price, remaining, "profit_runner_short_trend_break", params)
                remaining = 0
                break
            if not params.profit_run_enabled and params.take_profit_pct > 0 and high_price >= buy_price * (1 + params.take_profit_pct / 100):
                self._append_exit(exits, row, buy_price * (1 + params.take_profit_pct / 100), remaining, "take_profit", params)
                remaining = 0
                break
        if remaining > 0:
            final_row = frame.iloc[target_exit_index]
            self._append_exit(exits, final_row, self._pick_price(final_row, params.sell_price), remaining, "holding_days", params)
        return exits

    def _append_exit(self, exits: list[dict[str, Any]], row, price: float, portion: float, reason: str, params: EngineParams) -> None:
        if portion <= 0 or price <= 0:
            return
        exits.append(
            {
                "date": row["date"].strftime("%Y-%m-%d"),
                "price": round(price, 3),
                "portion_pct": round(portion * 100, 2),
                "reason": reason,
                "exit_reason": reason,
                "fee_slippage_pct": round((params.fee_rate + params.slippage_rate) * 100, 4),
            }
        )

    def _find_signal_index(self, frame: pd.DataFrame, signal_date: str) -> int | None:
        signal_ts = pd.to_datetime(signal_date)
        matched = frame.index[frame["date"] >= signal_ts]
        return int(matched[0]) if len(matched) else None

    def _end_bound_index(self, frame: pd.DataFrame, end_date: str) -> int | None:
        end_ts = pd.to_datetime(end_date)
        matches = frame.index[frame["date"] <= end_ts]
        return int(matches[-1]) if len(matches) else None

    def _pick_price(self, row, field: str) -> float:
        return safe_float(row.get(field), 0.0)

    def _build_equity_curve(self, trades: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float, float]:
        if not trades:
            return [], 0.0, 0.0
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for trade in trades:
            grouped[trade["sell_date"]].append(trade)
        equity = 1.0
        peak = 1.0
        max_drawdown = 0.0
        curve = []
        for sell_date in sorted(grouped):
            daily_return = sum(trade["return_pct"] / 100 for trade in grouped[sell_date]) / len(grouped[sell_date])
            equity *= 1 + daily_return
            peak = max(peak, equity)
            drawdown = (equity / peak - 1) * 100 if peak > 0 else 0.0
            max_drawdown = min(max_drawdown, drawdown)
            curve.append({"date": sell_date, "daily_return_pct": round(daily_return * 100, 2), "equity": round(equity, 4), "drawdown_pct": round(drawdown, 2)})
        return curve, (equity - 1) * 100, max_drawdown
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_simulator -v
```

Expected: PASS all 3 tests.

- [ ] **Step 5: Commit**

```powershell
git add utils\backtest_engine\simulator.py web\backend\tests\test_backtest_engine_simulator.py
git commit -m "feat: add unified trade simulator" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: SQLite Backtest Repository

**Files:**
- Modify: `web\backend\services\sqlite_service.py`
- Create: `utils\backtest_engine\repository.py`
- Test: `web\backend\tests\test_backtest_engine_repository.py`

- [ ] **Step 1: Write failing repository tests**

Create `web\backend\tests\test_backtest_engine_repository.py`:

```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.backtest_engine.repository import BacktestRepository
from web.backend.services import sqlite_service


class BacktestRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        if hasattr(sqlite_service._local, "conn"):
            delattr(sqlite_service._local, "conn")
        self.path_patcher = patch.object(sqlite_service, "DB_PATH", self.db_path)
        self.path_patcher.start()
        sqlite_service.init_database()

    def tearDown(self):
        if hasattr(sqlite_service._local, "conn"):
            sqlite_service._local.conn.close()
            delattr(sqlite_service._local, "conn")
        self.path_patcher.stop()
        self.temp_dir.cleanup()

    def test_saves_and_reads_full_result(self):
        repo = BacktestRepository()
        result = {
            "run_id": "unit-run",
            "params": {"date": "2026-04-01"},
            "summary": {"candidate_count": 1, "signal_count": 1, "trade_count": 1},
            "signals": [{"code": "000001", "name": "平安银行", "strategy_name": "Unit", "trade_date": "2026-04-01", "signal_date": "2026-04-01", "reason": "match", "signal": {"a": 1}}],
            "trades": [{"code": "000001", "name": "平安银行", "strategy_name": "Unit", "buy_date": "2026-04-02", "sell_date": "2026-04-03", "return_pct": 5.5, "exits": [{"date": "2026-04-03"}]}],
            "equity_curve": [{"date": "2026-04-03", "equity": 1.055, "drawdown_pct": 0}],
            "diagnostics": [{"type": "simulation_skipped", "code": "000002", "stage": "buy", "reason": "out"}],
        }

        repo.save_result(result, source="unit", status="completed")
        loaded = repo.get_result("unit-run")

        self.assertEqual(loaded["run_id"], "unit-run")
        self.assertEqual(loaded["summary"]["trade_count"], 1)
        self.assertEqual(loaded["signals"][0]["code"], "000001")
        self.assertEqual(loaded["trades"][0]["return_pct"], 5.5)
        self.assertEqual(loaded["diagnostics"][0]["type"], "simulation_skipped")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_repository -v
```

Expected: FAIL because `BacktestRepository` and result tables do not exist.

- [ ] **Step 3: Add SQLite schema**

Modify `web\backend\services\sqlite_service.py`:

```python
SCHEMA_VERSION = 3
```

Inside `init_database()`, after the `manual_selections` indexes and before app_meta version write, add:

```python
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_runs (
            run_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            params_json TEXT,
            summary_json TEXT,
            diagnostics_json TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_signals (
            signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            trade_date TEXT,
            signal_date TEXT,
            strategy_name TEXT,
            code TEXT NOT NULL,
            name TEXT,
            category TEXT,
            similarity_score REAL,
            reason TEXT,
            signal_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            strategy_name TEXT,
            buy_date TEXT,
            sell_date TEXT,
            buy_price REAL,
            sell_price REAL,
            return_pct REAL,
            gross_return_pct REAL,
            hold_days INTEGER,
            exit_reason TEXT,
            exits_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backtest_equity_points (
            point_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            date TEXT NOT NULL,
            daily_return_pct REAL,
            equity REAL,
            drawdown_pct REAL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_runs_status ON backtest_runs(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_signals_run_id ON backtest_signals(run_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_signals_code ON backtest_signals(code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_signals_date ON backtest_signals(signal_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_id ON backtest_trades(run_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_trades_code ON backtest_trades(code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_equity_run_id ON backtest_equity_points(run_id)")
```

- [ ] **Step 4: Implement repository**

Create `utils\backtest_engine\repository.py`:

```python
from __future__ import annotations

import json
from typing import Any, Optional

from utils.backtest_engine.models import now_text
from web.backend.services.sqlite_service import get_connection


class BacktestRepository:
    def save_result(self, result: dict[str, Any], source: str, status: str = "completed") -> None:
        run_id = result["run_id"]
        conn = get_connection()
        now = now_text()
        conn.execute(
            """INSERT OR REPLACE INTO backtest_runs
               (run_id, source, status, params_json, summary_json, diagnostics_json, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM backtest_runs WHERE run_id = ?), ?), ?)""",
            (
                run_id,
                source,
                status,
                json.dumps(result.get("params", {}), ensure_ascii=False),
                json.dumps(result.get("summary", {}), ensure_ascii=False),
                json.dumps(result.get("diagnostics", []), ensure_ascii=False),
                run_id,
                now,
                now if status in {"completed", "failed"} else None,
            ),
        )
        conn.execute("DELETE FROM backtest_signals WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM backtest_trades WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM backtest_equity_points WHERE run_id = ?", (run_id,))
        self._insert_signals(conn, run_id, result.get("signals", []), now)
        self._insert_trades(conn, run_id, result.get("trades", []), now)
        self._insert_equity_points(conn, run_id, result.get("equity_curve", []))
        conn.commit()

    def get_result(self, run_id: str) -> Optional[dict[str, Any]]:
        conn = get_connection()
        run = conn.execute("SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not run:
            return None
        signals = conn.execute("SELECT * FROM backtest_signals WHERE run_id = ? ORDER BY signal_id ASC", (run_id,)).fetchall()
        trades = conn.execute("SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY trade_id ASC", (run_id,)).fetchall()
        equity = conn.execute("SELECT * FROM backtest_equity_points WHERE run_id = ? ORDER BY date ASC, point_id ASC", (run_id,)).fetchall()
        return {
            "run_id": run["run_id"],
            "source": run["source"],
            "status": run["status"],
            "params": json.loads(run["params_json"] or "{}"),
            "summary": json.loads(run["summary_json"] or "{}"),
            "diagnostics": json.loads(run["diagnostics_json"] or "[]"),
            "signals": [self._decode_signal(row) for row in signals],
            "trades": [self._decode_trade(row) for row in trades],
            "equity_curve": [dict(row) for row in equity],
            "created_at": run["created_at"],
            "completed_at": run["completed_at"],
        }

    def _insert_signals(self, conn, run_id: str, signals: list[dict[str, Any]], now: str) -> None:
        conn.executemany(
            """INSERT INTO backtest_signals
               (run_id, trade_date, signal_date, strategy_name, code, name, category,
                similarity_score, reason, signal_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    item.get("trade_date"),
                    item.get("signal_date"),
                    item.get("strategy_name"),
                    item.get("code", ""),
                    item.get("name", ""),
                    item.get("category", ""),
                    item.get("similarity_score"),
                    item.get("reason", ""),
                    json.dumps(item.get("signal", {}), ensure_ascii=False),
                    now,
                )
                for item in signals
            ],
        )

    def _insert_trades(self, conn, run_id: str, trades: list[dict[str, Any]], now: str) -> None:
        conn.executemany(
            """INSERT INTO backtest_trades
               (run_id, code, name, strategy_name, buy_date, sell_date, buy_price,
                sell_price, return_pct, gross_return_pct, hold_days, exit_reason,
                exits_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    item.get("code", ""),
                    item.get("name", ""),
                    item.get("strategy_name", ""),
                    item.get("buy_date"),
                    item.get("sell_date"),
                    item.get("buy_price"),
                    item.get("sell_price"),
                    item.get("return_pct"),
                    item.get("gross_return_pct"),
                    item.get("hold_days"),
                    item.get("exit_reason"),
                    json.dumps(item.get("exits", []), ensure_ascii=False),
                    now,
                )
                for item in trades
            ],
        )

    def _insert_equity_points(self, conn, run_id: str, points: list[dict[str, Any]]) -> None:
        conn.executemany(
            """INSERT INTO backtest_equity_points
               (run_id, date, daily_return_pct, equity, drawdown_pct)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    run_id,
                    item.get("date"),
                    item.get("daily_return_pct"),
                    item.get("equity"),
                    item.get("drawdown_pct"),
                )
                for item in points
            ],
        )

    def _decode_signal(self, row) -> dict[str, Any]:
        item = dict(row)
        item["signal"] = json.loads(item.pop("signal_json") or "{}")
        return item

    def _decode_trade(self, row) -> dict[str, Any]:
        item = dict(row)
        item["exits"] = json.loads(item.pop("exits_json") or "[]")
        return item
```

- [ ] **Step 5: Run repository test**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_repository -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add web\backend\services\sqlite_service.py utils\backtest_engine\repository.py web\backend\tests\test_backtest_engine_repository.py
git commit -m "feat: persist backtest results" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Engine Orchestration

**Files:**
- Create: `utils\backtest_engine\engine.py`
- Test: `web\backend\tests\test_backtest_engine_orchestration.py`

- [ ] **Step 1: Write failing orchestration tests**

Create `web\backend\tests\test_backtest_engine_orchestration.py`:

```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

from utils.backtest_engine.engine import BacktestEngine


class BacktestEngineOrchestrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        pd.DataFrame(
            [
                {"date": "2026-04-01", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 1000},
                {"date": "2026-04-02", "open": 10.5, "high": 12.0, "low": 10.3, "close": 11.5, "volume": 1100},
                {"date": "2026-04-03", "open": 11.5, "high": 12.5, "low": 11.0, "close": 12.0, "volume": 1200},
            ]
        ).to_csv(self.data_dir / "000001.csv", index=False, encoding="utf-8")
        (self.data_dir / "stock_names.json").write_text('{"000001": "平安银行"}', encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_diagnose_stock_combines_signals_summary_and_diagnostics(self):
        runner = Mock()
        runner.run_for_stock.return_value = (
            [
                {
                    "code": "000001",
                    "name": "平安银行",
                    "strategy_name": "Unit",
                    "strategy_filter": "Unit",
                    "trade_date": "2026-04-01",
                    "signal_date": "2026-04-01",
                    "reason": "match",
                    "signal": {},
                }
            ],
            [],
        )
        engine = BacktestEngine(data_dir=str(self.data_dir), signal_runner=runner, repository=None)

        result = engine.diagnose_stock("000001", "2026-04-01", strategy_filter="all", save_result=False)

        self.assertEqual(result["summary"]["candidate_count"], 1)
        self.assertEqual(result["summary"]["signal_count"], 1)
        self.assertEqual(result["signals"][0]["code"], "000001")
        self.assertEqual(result["diagnostics"], [])

    def test_run_candidate_backtest_uses_input_candidates(self):
        engine = BacktestEngine(data_dir=str(self.data_dir), repository=None)
        result = engine.run_candidate_backtest(
            {
                "start_date": "2026-04-01",
                "end_date": "2026-04-03",
                "selected_candidates": [
                    {"code": "000001", "name": "平安银行", "strategy_name": "Unit", "trade_date": "2026-04-01", "signal_date": "2026-04-01"}
                ],
                "holding_days": 1,
                "buy_offset_days": 1,
                "profit_run_enabled": False,
            },
            save_result=False,
        )

        self.assertEqual(result["summary"]["candidate_count"], 1)
        self.assertEqual(result["summary"]["trade_count"], 1)
        self.assertEqual(result["trades"][0]["buy_date"], "2026-04-02")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_orchestration -v
```

Expected: FAIL because `utils.backtest_engine.engine` does not exist.

- [ ] **Step 3: Implement engine orchestration**

Create `utils\backtest_engine\engine.py`:

```python
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Optional

from utils.backtest_engine.data_provider import HistoricalDataProvider
from utils.backtest_engine.models import EngineParams
from utils.backtest_engine.repository import BacktestRepository
from utils.backtest_engine.signal_runner import StrategySignalRunner
from utils.backtest_engine.simulator import BacktestSimulator


ProgressCallback = Callable[[dict[str, Any]], None]


def generate_run_id(prefix: str = "bt") -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + prefix + "_" + uuid.uuid4().hex[:8]


class BacktestEngine:
    def __init__(
        self,
        data_dir: str = "data",
        data_provider: Optional[HistoricalDataProvider] = None,
        signal_runner: Optional[StrategySignalRunner] = None,
        simulator: Optional[BacktestSimulator] = None,
        repository: Optional[BacktestRepository] = None,
    ):
        self.data_provider = data_provider or HistoricalDataProvider(data_dir)
        self.signal_runner = signal_runner or StrategySignalRunner()
        self.simulator = simulator or BacktestSimulator()
        self.repository = repository if repository is not None else BacktestRepository()

    def diagnose_stock(self, stock_code: str, date: str, strategy_filter: str = "all", save_result: bool = True) -> dict[str, Any]:
        run_id = generate_run_id("diag")
        frame, diagnostics = self.data_provider.load_until(stock_code, date)
        signals = []
        if not diagnostics:
            name = self.data_provider.stock_name(stock_code)
            signals, strategy_diagnostics = self.signal_runner.run_for_stock(stock_code, name, frame, strategy_filter)
            diagnostics.extend(strategy_diagnostics)
        result = {
            "run_id": run_id,
            "params": {"stock_code": stock_code, "date": date, "strategy_filter": strategy_filter, "save_result": save_result},
            "signals": signals,
            "trades": [],
            "equity_curve": [],
            "diagnostics": diagnostics,
            "summary": {
                "candidate_count": 1,
                "signal_count": len(signals),
                "trade_count": 0,
                "skipped_count": 1 if diagnostics else 0,
                "strategy_error_count": sum(1 for item in diagnostics if item.get("type") == "strategy_errors"),
                "win_rate_pct": 0.0,
                "avg_return_pct": 0.0,
                "cumulative_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "avg_hold_days": 0.0,
                "best_return_pct": 0.0,
                "worst_return_pct": 0.0,
            },
        }
        self._save(result, "diagnose", save_result)
        return result

    def run_candidate_backtest(self, params_dict: dict[str, Any], save_result: bool | None = None) -> dict[str, Any]:
        params = EngineParams.from_dict(params_dict)
        if save_result is not None:
            params.save_result = save_result
        run_id = generate_run_id("backtest")
        candidates = self._resolve_candidates(params)
        candidates = self._cap_positions_per_day(candidates, params.max_positions_per_day)
        trades = []
        diagnostics = []
        for candidate in candidates:
            frame, frame_diagnostics = self.data_provider.load_full(candidate["code"])
            if frame_diagnostics:
                diagnostics.extend(frame_diagnostics)
                continue
            trade, trade_diagnostics = self.simulator.simulate(candidate, frame, params)
            if trade:
                trades.append(trade)
            diagnostics.extend(trade_diagnostics)
        trades.sort(key=lambda item: (item["buy_date"], item["code"]))
        equity_curve, summary = self.simulator.summarize(
            trades,
            candidate_count=len(candidates),
            signal_count=len(candidates),
            diagnostics=diagnostics,
        )
        result = {
            "run_id": run_id,
            "params": params_dict,
            "signals": candidates,
            "trades": trades,
            "equity_curve": equity_curve,
            "diagnostics": diagnostics,
            "summary": summary,
        }
        self._save(result, "backtest", params.save_result)
        return result

    def run_full_market_scan(
        self,
        date: str,
        strategy_filter: str = "all",
        stock_pool: Optional[list[str]] = None,
        save_result: bool = True,
        run_id: Optional[str] = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> dict[str, Any]:
        run_id = run_id or generate_run_id("scan")
        codes = stock_pool or self.data_provider.list_all_stocks()
        signals = []
        diagnostics = []
        total = len(codes)
        for index, code in enumerate(codes, start=1):
            frame, frame_diagnostics = self.data_provider.load_until(code, date)
            if frame_diagnostics:
                diagnostics.extend(frame_diagnostics)
            else:
                name = self.data_provider.stock_name(code)
                stock_signals, strategy_diagnostics = self.signal_runner.run_for_stock(code, name, frame, strategy_filter)
                signals.extend(stock_signals)
                diagnostics.extend(strategy_diagnostics)
            if progress_callback:
                progress_callback({"run_id": run_id, "processed": index, "total": total, "matched": len(signals), "code": code})
        result = {
            "run_id": run_id,
            "params": {"date": date, "strategy_filter": strategy_filter, "stock_pool_size": total, "save_result": save_result},
            "signals": signals,
            "trades": [],
            "equity_curve": [],
            "diagnostics": diagnostics,
            "summary": {
                "candidate_count": total,
                "signal_count": len(signals),
                "trade_count": 0,
                "skipped_count": len([item for item in diagnostics if item.get("type") != "strategy_errors"]),
                "strategy_error_count": sum(1 for item in diagnostics if item.get("type") == "strategy_errors"),
                "win_rate_pct": 0.0,
                "avg_return_pct": 0.0,
                "cumulative_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "avg_hold_days": 0.0,
                "best_return_pct": 0.0,
                "worst_return_pct": 0.0,
            },
        }
        self._save(result, "full_market_scan", save_result)
        return result

    def _resolve_candidates(self, params: EngineParams) -> list[dict[str, Any]]:
        if params.selected_candidates:
            return [self._normalize_candidate(item, "strategy") for item in params.selected_candidates if item.get("code")]
        if params.input_codes:
            return [
                {
                    "code": code,
                    "name": self.data_provider.stock_name(code),
                    "strategy_name": "输入个股",
                    "trade_date": params.start_date,
                    "signal_date": params.start_date,
                    "source": "codes",
                }
                for code in params.input_codes
            ]
        return []

    def _normalize_candidate(self, item: dict[str, Any], source: str) -> dict[str, Any]:
        signal_date = item.get("signal_date") or item.get("trade_date")
        return {
            "code": item["code"],
            "name": item.get("name") or self.data_provider.stock_name(item["code"]),
            "strategy_name": item.get("strategy_name", ""),
            "trade_date": item.get("trade_date") or signal_date,
            "signal_date": signal_date,
            "source": source,
            "signal": item,
        }

    def _cap_positions_per_day(self, candidates: list[dict[str, Any]], max_positions: int) -> list[dict[str, Any]]:
        if max_positions <= 0:
            return candidates
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for candidate in candidates:
            grouped[str(candidate.get("trade_date") or candidate.get("signal_date") or "")].append(candidate)
        capped: list[dict[str, Any]] = []
        for trade_date in sorted(grouped):
            capped.extend(sorted(grouped[trade_date], key=lambda item: item.get("code", ""))[:max_positions])
        return capped

    def _save(self, result: dict[str, Any], source: str, save_result: bool) -> None:
        if save_result and self.repository is not None:
            self.repository.save_result(result, source=source, status="completed")
```

- [ ] **Step 4: Run orchestration test**

Run:

```powershell
python -m unittest web.backend.tests.test_backtest_engine_orchestration -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add utils\backtest_engine\engine.py web\backend\tests\test_backtest_engine_orchestration.py
git commit -m "feat: orchestrate unified backtest engine" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Web API Adapters

**Files:**
- Create: `web\backend\routers\backtrace.py`
- Modify: `web\backend\routers\backtest.py`
- Modify: `web\backend\services\backtest_service.py`
- Modify: `web\backend\main.py`
- Test: `web\backend\tests\test_backtrace_api.py`

- [ ] **Step 1: Write failing API tests**

Create `web\backend\tests\test_backtrace_api.py`:

```python
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.backend.main import app


class BacktraceApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_diagnose_validates_stock_code(self):
        response = self.client.post("/api/backtrace/diagnose", json={"stock_code": "abc", "date": "2026-04-01"})
        self.assertEqual(response.status_code, 422)

    def test_diagnose_returns_engine_result(self):
        expected = {"run_id": "diag-1", "signals": [], "diagnostics": [], "summary": {"signal_count": 0}}
        with patch("web.backend.routers.backtrace.BacktestEngine") as engine_cls:
            engine_cls.return_value.diagnose_stock.return_value = expected
            response = self.client.post("/api/backtrace/diagnose", json={"stock_code": "000001", "date": "2026-04-01"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["data"]["run_id"], "diag-1")

    def test_existing_backtest_endpoint_delegates_to_engine_wrapper(self):
        expected = {"run_id": "bt-1", "summary": {"trade_count": 0}, "trades": [], "equity_curve": [], "diagnostics": []}
        payload = {"start_date": "2026-04-01", "end_date": "2026-04-03", "source": "codes", "input_codes": ["000001"], "holding_days": 1, "buy_offset_days": 1, "buy_price": "open", "sell_price": "close", "fee_rate": 0, "slippage_rate": 0, "max_positions_per_day": 10}
        with patch("web.backend.services.backtest_service.run_backtest", return_value=expected):
            response = self.client.post("/api/backtest", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["run_id"], "bt-1")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run API test to verify it fails**

Run:

```powershell
python -m unittest web.backend.tests.test_backtrace_api -v
```

Expected: FAIL because `web.backend.routers.backtrace` is not registered.

- [ ] **Step 3: Add backtrace router**

Create `web\backend\routers\backtrace.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from utils.backtest_engine.engine import BacktestEngine, generate_run_id
from web.backend.services import strategy_result_repository as repo


DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
router = APIRouter(prefix="/api", tags=["回溯"])


class BacktraceDiagnoseRequest(BaseModel):
    stock_code: str = Field(..., pattern=r"^\d{6}$")
    date: str = Field(..., pattern=DATE_PATTERN)
    strategy_filter: str = "all"
    save_result: bool = True


class BacktraceRunRequest(BaseModel):
    date: str = Field(..., pattern=DATE_PATTERN)
    strategy_filter: str = "all"
    stock_pool: list[str] = Field(default_factory=list)
    max_workers: int = Field(default=1, ge=1, le=64)
    save_result: bool = True


@router.post("/backtrace/diagnose")
async def diagnose_backtrace(payload: BacktraceDiagnoseRequest):
    result = BacktestEngine().diagnose_stock(
        payload.stock_code,
        payload.date,
        strategy_filter=payload.strategy_filter,
        save_result=payload.save_result,
    )
    return {"success": True, "data": result}


@router.post("/backtrace/runs")
async def create_backtrace_run(payload: BacktraceRunRequest, background_tasks: BackgroundTasks):
    engine = BacktestEngine()
    run_id = generate_run_id("scan")
    repo.create_run(run_id, "backtrace_scan", payload.date, payload.strategy_filter, len(payload.stock_pool))

    def progress(event):
        progress = int(event["processed"] / max(event["total"], 1) * 100)
        repo.update_run(event["run_id"], processed_count=event["processed"], total_count=event["total"], matched_count=event["matched"], stage="scan")
        repo.insert_event(event["run_id"], "progress", strategy_filter=payload.strategy_filter, progress=progress, message=f"processed {event['code']}", payload=event)

    def worker():
        try:
            result = engine.run_full_market_scan(
                payload.date,
                strategy_filter=payload.strategy_filter,
                stock_pool=payload.stock_pool or None,
                save_result=payload.save_result,
                run_id=run_id,
                progress_callback=progress,
            )
            repo.finish_run(run_id, "completed", "回溯扫描完成", matched_count=result["summary"]["signal_count"], processed_count=result["summary"]["candidate_count"])
        except Exception as exc:
            repo.finish_run(run_id, "failed", str(exc), matched_count=0, processed_count=0)
            raise

    background_tasks.add_task(worker)
    return {"success": True, "data": {"run_id": run_id, "status": "queued"}}


@router.get("/backtrace/runs/{run_id}")
async def get_backtrace_run(run_id: str, event_limit: int = Query(200, ge=1, le=2000)):
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"回溯任务不存在: {run_id}")
    return {"success": True, "data": {"run": run, "events": repo.get_run_events(run_id, event_limit)}}
```

- [ ] **Step 4: Register router in FastAPI**

Modify `web\backend\main.py` imports and registration:

```python
from web.backend.routers import kline, strategy, stock, update, config_api, backtest, backtrace, trajectory, txt_export, manual_selection
```

Add after `app.include_router(backtest.router)`:

```python
app.include_router(backtrace.router)
```

- [ ] **Step 5: Convert Web backtest service to wrapper**

Replace `web\backend\services\backtest_service.py` with:

```python
"""回测服务：兼容旧导入路径，内部委托统一回测引擎。"""
from utils.backtest_engine.engine import BacktestEngine


def run_backtest(params: dict) -> dict:
    return BacktestEngine().run_candidate_backtest(params)
```

- [ ] **Step 6: Run API tests**

Run:

```powershell
python -m unittest web.backend.tests.test_backtrace_api -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add web\backend\routers\backtrace.py web\backend\routers\backtest.py web\backend\services\backtest_service.py web\backend\main.py web\backend\tests\test_backtrace_api.py
git commit -m "feat: add backtrace web api" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 7: CLI Integration

**Files:**
- Modify: `main.py`
- Test: `web\backend\tests\test_backtrace_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `web\backend\tests\test_backtrace_cli.py`:

```python
import io
import unittest
from unittest.mock import patch

import main


class BacktraceCliTest(unittest.TestCase):
    def test_backtrace_single_stock_uses_engine(self):
        result = {"run_id": "diag-1", "summary": {"signal_count": 1}, "signals": [{"strategy_name": "Unit", "code": "000001"}], "diagnostics": []}
        with patch("sys.argv", ["main.py", "backtrace", "--stock-code", "000001", "--date", "2026-04-01"]), \
             patch("main.QuantSystem"), \
             patch("main.get_last_trading_day", return_value="2026-04-01"), \
             patch("main.is_trading_day", return_value=True), \
             patch("utils.backtest_engine.engine.BacktestEngine.diagnose_stock", return_value=result), \
             patch("sys.stdout", new_callable=io.StringIO) as stdout:
            main.main()

        self.assertIn("diag-1", stdout.getvalue())
        self.assertIn("Unit", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
python -m unittest web.backend.tests.test_backtrace_cli -v
```

Expected: FAIL because `main.py` still uses `BacktraceAnalyzer`.

- [ ] **Step 3: Update CLI imports and command behavior**

Modify `main.py`:

```python
from utils.backtest_engine.engine import BacktestEngine
```

Remove:

```python
from utils.backtrace_analyzer import BacktraceAnalyzer
```

Add parser argument:

```python
parser.add_argument('--strategy-filter', type=str, default='all', help='回溯策略过滤，默认all')
```

Replace the `elif args.command == 'backtrace':` block with:

```python
    elif args.command == 'backtrace':
        if not args.date:
            print("⚠️ 请输入回溯日期 (--date)，格式为YYYY-MM-DD")
            return

        engine = BacktestEngine(data_dir="data")
        if args.stock_code:
            result = engine.diagnose_stock(
                args.stock_code,
                args.date,
                strategy_filter=args.strategy_filter,
                save_result=True,
            )
            print(f"回溯 run_id: {result['run_id']}")
            print(f"信号数量: {result['summary'].get('signal_count', 0)}")
            for signal in result.get("signals", []):
                print(f"- {signal.get('strategy_name', '')}: {signal.get('code', '')} {signal.get('name', '')} {signal.get('reason', '')}")
            if result.get("diagnostics"):
                print(f"诊断数量: {len(result['diagnostics'])}")
            return

        result = engine.run_full_market_scan(
            args.date,
            strategy_filter=args.strategy_filter,
            save_result=True,
        )
        print(f"全市场回溯 run_id: {result['run_id']}")
        print(f"扫描股票: {result['summary'].get('candidate_count', 0)}")
        print(f"信号数量: {result['summary'].get('signal_count', 0)}")
        print(f"策略异常: {result['summary'].get('strategy_error_count', 0)}")
        return
```

- [ ] **Step 4: Run CLI test**

Run:

```powershell
python -m unittest web.backend.tests.test_backtrace_cli -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add main.py web\backend\tests\test_backtrace_cli.py
git commit -m "feat: route cli backtrace through unified engine" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 8: Compatibility and Regression Tests

**Files:**
- Test: existing tests under `web\backend\tests\`
- Modify only if test failures reveal a direct regression in files changed by prior tasks.

- [ ] **Step 1: Run focused backtest engine suite**

Run:

```powershell
python -m unittest discover -s web\backend\tests -p "test_backtest_engine*.py" -v
```

Expected: PASS all backtest engine tests.

- [ ] **Step 2: Run backtrace API and CLI tests**

Run:

```powershell
python -m unittest web.backend.tests.test_backtrace_api web.backend.tests.test_backtrace_cli -v
```

Expected: PASS.

- [ ] **Step 3: Run existing backend tests**

Run:

```powershell
python -m unittest discover -s web\backend\tests -p "test_*.py" -v
```

Expected: PASS all tests. If an existing unrelated test fails because of local environment, capture the failure output and do not change unrelated code.

- [ ] **Step 4: Smoke-check CLI help**

Run:

```powershell
python main.py backtrace --help
```

Expected: command help includes `--stock-code`, `--date`, and `--strategy-filter`.

- [ ] **Step 5: Commit any direct regression fixes**

If Step 1, 2, 3, or 4 required fixes in already-touched files, commit them:

```powershell
git add main.py utils\backtest_engine web\backend\routers web\backend\services web\backend\tests
git commit -m "fix: stabilize backtrace engine integration" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

If no fixes were needed, skip this commit.

---

### Task 9: Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README Web/API and CLI documentation**

In `README.md`, add a short subsection near the Web 工作台 or backtest description:

```markdown
### 回溯/回测基础引擎

项目提供统一回溯/回测引擎，CLI 与 Web API 共用同一套历史数据截断、策略信号、交易模拟和结果持久化逻辑。

```bash
# 单股历史诊断：严格只使用目标日期及以前的数据
python main.py backtrace --stock-code 000001 --date 2026-04-01

# 全市场历史扫描：对本地 data/ CSV 股票池按历史日期重跑策略
python main.py backtrace --date 2026-04-01 --strategy-filter all
```

Web API:

- `POST /api/backtrace/diagnose`：单股历史诊断。
- `POST /api/backtrace/runs`：创建全市场历史扫描任务。
- `GET /api/backtrace/runs/{run_id}`：查询任务状态和事件。
- `POST /api/backtest`：候选回测，保持原接口并返回 `run_id`、`diagnostics`、交易明细和资金曲线。

回溯结果保存到 `data/web_strategy_cache.db`，可按 `run_id` 复盘信号、交易、资金曲线和诊断原因。
```

- [ ] **Step 2: Commit docs**

```powershell
git add README.md
git commit -m "docs: document unified backtrace engine" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 10: Final Verification

**Files:**
- No new code unless a prior task left a direct integration failure.

- [ ] **Step 1: Run full focused validation**

Run:

```powershell
python -m unittest discover -s web\backend\tests -p "test_*.py" -v
```

Expected: PASS all backend tests.

- [ ] **Step 2: Run the required CLI smoke command**

Run:

```powershell
python main.py backtrace --stock-code 000001 --date 2026-04-01
```

Expected: command prints a `run_id`, signal count, and diagnostics count if present. It must not print `回溯分析失败` from the old `BacktraceAnalyzer`.

- [ ] **Step 3: Check git status for unintended files**

Run:

```powershell
git --no-pager status --short
```

Expected: only intentional task changes are staged or committed. Existing unrelated local changes can remain, but do not include them in commits.

- [ ] **Step 4: Request code review**

Invoke the `requesting-code-review` skill before declaring implementation complete.

