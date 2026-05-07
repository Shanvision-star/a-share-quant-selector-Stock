"""回测结果分析与摘要。"""

from __future__ import annotations

from web.backend.backtest_engine.models import BacktestParams, OrderIntent, SignalCandidate
from web.backend.backtest_engine.portfolio import build_equity_curve


def build_result(
    *,
    params: BacktestParams,
    candidates: list[SignalCandidate],
    trades: list[dict],
    skipped: int,
    order_intents: list[OrderIntent],
) -> dict:
    """生成兼容旧 API 的回测响应结构，并附加 order_intents。"""
    trades = sorted(trades, key=lambda item: (item["buy_date"], item["code"]))
    equity_curve, cumulative_return, max_drawdown = build_equity_curve(trades)
    win_count = sum(1 for trade in trades if trade["return_pct"] > 0)
    trade_count = len(trades)
    avg_return = sum(trade["return_pct"] for trade in trades) / trade_count if trade_count else 0.0
    avg_hold_days = sum(trade["hold_days"] for trade in trades) / trade_count if trade_count else 0.0

    return {
        "params": params.to_mapping(),
        "summary": {
            "candidate_count": len(candidates),
            "trade_count": trade_count,
            "skipped_count": skipped,
            "win_rate_pct": round((win_count / trade_count * 100) if trade_count else 0.0, 2),
            "avg_return_pct": round(avg_return, 2),
            "cumulative_return_pct": round(cumulative_return, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "avg_hold_days": round(avg_hold_days, 1),
            "best_return_pct": round(max((trade["return_pct"] for trade in trades), default=0.0), 2),
            "worst_return_pct": round(min((trade["return_pct"] for trade in trades), default=0.0), 2),
        },
        "trades": trades,
        "equity_curve": equity_curve,
        "order_intents": [intent.to_mapping() for intent in order_intents],
    }
