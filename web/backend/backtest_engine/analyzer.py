"""回测结果分析与摘要。"""

from __future__ import annotations

from web.backend.backtest_engine.models import BacktestParams, OrderIntent, SignalCandidate
from web.backend.backtest_engine.portfolio import build_portfolio_ledger


def build_result(
    *,
    params: BacktestParams,
    candidates: list[SignalCandidate],
    trades: list[dict],
    skipped: int,
    order_intents: list[OrderIntent],
    runtime: dict | None = None,
) -> dict:
    """生成兼容旧 API 的回测响应结构，并附加 order_intents。"""
    runtime = runtime or {}
    trades = sorted(trades, key=lambda item: (item["buy_date"], item["code"]))
    portfolio = build_portfolio_ledger(trades, params.to_mapping())
    equity_curve = portfolio["equity_curve"]
    capital_summary = portfolio["capital_summary"]
    portfolio_events = portfolio["portfolio_events"]
    cumulative_return = capital_summary["cumulative_return_pct"]
    max_drawdown = capital_summary["max_drawdown_pct"]
    win_count = sum(1 for trade in trades if trade["return_pct"] > 0)
    trade_count = len(trades)
    avg_return = sum(trade["return_pct"] for trade in trades) / trade_count if trade_count else 0.0
    avg_hold_days = sum(trade["hold_days"] for trade in trades) / trade_count if trade_count else 0.0

    summary = {
        "candidate_count": len(candidates),
        "raw_candidate_count": int(runtime.get("raw_candidate_count", len(candidates))),
        "candidate_limit_applied": bool(runtime.get("candidate_limit_applied", False)),
        "runtime_stopped_early": bool(runtime.get("stopped_early", False)),
        "runtime_processed_count": int(runtime.get("processed_count", len(candidates))),
        "runtime_elapsed_seconds": runtime.get("elapsed_seconds", 0.0),
        "runtime_warning_count": len(runtime.get("warnings") or []),
        "trade_count": trade_count,
        "skipped_count": skipped,
        "win_rate_pct": round((win_count / trade_count * 100) if trade_count else 0.0, 2),
        "avg_return_pct": round(avg_return, 2),
        "cumulative_return_pct": round(cumulative_return, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "avg_hold_days": round(avg_hold_days, 1),
        "best_return_pct": round(max((trade["return_pct"] for trade in trades), default=0.0), 2),
        "worst_return_pct": round(min((trade["return_pct"] for trade in trades), default=0.0), 2),
        # 任务 C：把组合模式 / 融合模式 / 优先级模式透出到摘要，便于前端展示与回归审计
        "portfolio_mode": str(runtime.get("portfolio_mode") or params.get("portfolio_mode") or "fixed_slots"),
        "signal_merge_mode": str(runtime.get("signal_merge_mode") or params.get("signal_merge_mode") or "single"),
        "signal_priority_mode": str(runtime.get("signal_priority_mode") or params.get("signal_priority_mode") or "n/a"),
        "position_pct": float(params.get("position_pct") or 0),
        "max_weight_per_code": float(params.get("max_weight_per_code") or 0),
    }

    return {
        "params": params.to_mapping(),
        "summary": summary,
        "trades": trades,
        "equity_curve": equity_curve,
        "capital_summary": capital_summary,
        "portfolio_events": portfolio_events,
        "order_intents": [intent.to_mapping() for intent in order_intents],
        "runtime": runtime,
    }
