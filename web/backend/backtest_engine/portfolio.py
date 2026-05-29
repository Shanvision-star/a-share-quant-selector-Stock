"""组合收益曲线计算。"""

from __future__ import annotations

from collections import defaultdict


def build_equity_curve(trades: list[dict]) -> tuple[list[dict], float, float]:
    """按卖出日聚合交易收益，生成简化资金曲线。

    任务 C 深度：每条 trade 可携带 ``weight`` 字段（范围 0~1，缺省视为 1.0）。
    - 旧行为：fixed_slots 模式下所有 trade.weight==1.0，等价于历史的等权平均；
    - 新行为：weight_cap 模式下 trade.weight = position_pct/100，
      日内多笔按权重加权再平均，避免把 10% 仓位的小单当作满仓贡献。
    权重缺失时回退 1.0，保持向后兼容。
    """
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
        day_trades = grouped[sell_date]
        # 加权口径：sum(return * weight) / sum(weight)，权重缺省=1.0 → 退化为等权平均
        weight_sum = 0.0
        weighted_return = 0.0
        for trade in day_trades:
            weight = float(trade.get("weight") or 1.0)
            if weight <= 0:
                continue
            weighted_return += (trade["return_pct"] / 100.0) * weight
            weight_sum += weight
        daily_return = (weighted_return / weight_sum) if weight_sum > 0 else 0.0
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
