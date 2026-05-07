"""组合收益曲线计算。"""

from __future__ import annotations

from collections import defaultdict


def build_equity_curve(trades: list[dict]) -> tuple[list[dict], float, float]:
    """按卖出日聚合交易收益，生成简化资金曲线。"""
    if not trades:
        return [], 0.0, 0.0
    grouped: dict[str, list[dict]] = defaultdict(list)
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
        curve.append(
            {
                "date": sell_date,
                "daily_return_pct": round(daily_return * 100, 2),
                "equity": round(equity, 4),
                "drawdown_pct": round(drawdown, 2),
            }
        )
    return curve, (equity - 1) * 100, max_drawdown
