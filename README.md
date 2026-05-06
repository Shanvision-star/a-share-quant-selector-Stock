# A-share Quant Frontend

Vue 3 + TypeScript + Vite front end for the A-share quant selector.

## Scripts

```bash
npm install
npm run dev
npm test -- --run
npm run build
```

## Local API

The development server proxies API requests to the FastAPI backend. Keep the backend running on `http://127.0.0.1:8001` when using the local Vite app.

## Main Pages

- `StrategyResultsView.vue`: strategy result browsing, grouped strategy lists, TXT export, and K-line prefetch.
- `StockDetail.vue`: interactive K-line chart with main and sub indicators.
- `ManualSelectionPoolView.vue`: manual pool review and backtest entry.
- `BacktestView.vue`: signal-date-based backtesting for strategy results, manual selections, and typed stock codes.
- `UpdateView.vue`: daily data update and strategy rebuild workflow.
