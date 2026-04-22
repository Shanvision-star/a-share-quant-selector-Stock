# Project Guidelines

## Scope
- This repository is an A-share quantitative stock selector built around Python data processing, strategy scanning, FastAPI services, and a Vue 3 web workbench.
- Prefer extending the existing pipeline instead of creating a parallel architecture. The current flow is: market data fetch -> CSV/JSON cache in `data/` -> strategy scan in `strategy/` -> export/notification/web presentation.
- Use the current code as the source of truth when planning docs and implementation differ, then update docs if behavior changes.

## Key Entry Points
- CLI entry and command routing live in `main.py`.
- Quant orchestration and end-to-end workflow live in `quant_system.py`.
- Core data update and cache logic live in `utils/akshare_fetcher.py` and `utils/csv_manager.py`.
- Strategy abstraction and auto-registration live in `strategy/base_strategy.py` and `strategy/strategy_registry.py`.
- Web code is split into `web/backend/` and `web/frontend/`.
- Backtrace and backtest related work should start from `main.py`, `quant_system.py`, and `utils/backtrace_analyzer.py`.

## Strategy Development
- New stock-picking strategies must inherit from `BaseStrategy` and live under `strategy/`.
- Keep reusable indicator and signal logic shareable across daily scan, web views, and backtrace/backtest features instead of embedding one-off logic in scripts.
- If a strategy needs runtime tuning, put its parameters in `config/strategy_params.yaml` instead of hardcoding them in multiple places.
- New strategies must remain compatible with `StrategyRegistry.auto_register_from_directory()` and the existing `QuantSystem` execution flow.
- Preserve the existing result shapes consumed by CLI commands, exports, DingTalk notifications, and the web UI.
- If a strategy is an adapter or wrapper, expose it as a `BaseStrategy` subclass that can be auto-registered.

## Backtrace, Backtest, and Quant Features
- Reuse the existing CSV market data and strategy pipeline before introducing a new storage layer or a second execution engine.
- Keep date handling explicit and compatible with the existing `YYYY-MM-DD` command and API conventions.
- When implementing backtrace or backtest functionality, align it with the current `BaseStrategy` and `StrategyRegistry` API instead of inventing a separate strategy interface.
- `utils/backtrace_analyzer.py` should be treated carefully because it may lag behind the current strategy registry implementation; reconcile it with the live registry and strategy base classes before building new features on top of it.
- Prefer adding reusable quant analysis code in stable modules, not only in ad hoc verification scripts.

## Data and Update Rules
- `data/` CSV files and JSON cache files are the current source of truth; do not redesign storage around a database unless the task explicitly requires it.
- Preserve incremental update behavior, cache refresh logic, and concurrency safeguards in `utils/akshare_fetcher.py`.
- When changing update progress, SSE payloads, or update APIs, keep backend emission and frontend consumption in sync.
- Be careful with low-level startup and registry logs on Windows. Prefer ASCII-safe console output in paths where encoding errors could break execution.

## Web and API Changes
- Keep FastAPI changes in `web/backend/` aligned with the Vue frontend in `web/frontend/`.
- Reuse existing routes, stores, and payload structures when possible instead of adding duplicate endpoints or duplicate state flows.
- Preserve the current update flow and strategy result pages unless the task explicitly asks for a larger redesign.

## Validation
- Use the smallest relevant validation for the changed area first.
- Common Python checks in this repo include `python main.py run --help`, `python main.py run --b1-match --max-stocks 20`, and `python main.py backtrace --stock-code 000001 --date 2026-04-01`.
- Common web checks in this repo include `cd web && npm run backend` and `cd web && npm run dev`.
- If there is no automated test for the touched area, add or describe a narrow reproducible verification step instead of relying only on broad manual testing.

## Docs
- Update `README.md` and the relevant files under `docs/` when commands, strategy behavior, web flows, or operational assumptions change.
- Prefer linking or extending existing docs instead of creating overlapping new documentation files unless the topic is genuinely new.