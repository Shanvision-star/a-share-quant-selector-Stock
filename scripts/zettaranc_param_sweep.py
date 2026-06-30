"""
Zettaranc 参数扫描脚本（优化计划 P1#4）
=========================================

目的：在 j_buy × vol_ratio 网格上跑离线回测，汇总交易数/胜率/盈亏比/最大回撤，
为 config/strategy_params.yaml 选出更均衡的默认阈值。

之所以单独成脚本：复用 run_zettaranc_backtest 的逐笔模拟器与聚合逻辑，
只在内存里换阈值循环，避免污染 output/ 目录（不落 9 份报告）。

CLI 用法：
    python scripts/zettaranc_param_sweep.py --limit 300 --start 2024-01-01 --end 2026-05-28
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_zettaranc_backtest import (  # noqa: E402
    aggregate,
    backtest_one_code,
    load_pool,
)
from strategy.zettaranc_combo import ZettarancComboStrategy  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402

# 扫描网格：阈值由严到宽，覆盖常态与攻击日两端
J_BUY_GRID = [-5.0, 0.0, 5.0]
VOL_RATIO_GRID = [1.3, 1.5, 2.0]


def run_one(codes, csv_mgr, j_buy, vol_ratio, start, end, take_profit, hold_days, fee):
    """单组阈值回测，返回聚合 dict。"""
    strat = ZettarancComboStrategy({"J_BUY": j_buy, "VOL_RATIO_MIN": vol_ratio})
    all_trades = []
    signals = 0
    for code in codes:
        try:
            trades, sig = backtest_one_code(
                code, csv_mgr, strat,
                start_date=start, end_date=end,
                take_profit_pct=take_profit, hold_days_limit=hold_days, fee_pct=fee,
            )
        except Exception:  # noqa: BLE001  单股异常跳过
            continue
        all_trades.extend(trades)
        signals += sig
    stats = aggregate(all_trades)
    stats["signals"] = signals
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Zettaranc 参数扫描")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-05-28")
    ap.add_argument("--pool", default="local_all")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--take-profit", type=float, default=15.0)
    ap.add_argument("--hold-days", type=int, default=20)
    ap.add_argument("--fee", type=float, default=0.05)
    args = ap.parse_args()

    data_dir = ROOT / "data"
    csv_mgr = CSVManager(str(data_dir))
    codes = load_pool(args.pool, data_dir)
    if args.limit > 0:
        codes = codes[: args.limit]
    print(f"[sweep] 股票池 {len(codes)} 只；区间 {args.start} ~ {args.end}")

    rows = []
    for j in J_BUY_GRID:
        for v in VOL_RATIO_GRID:
            stats = run_one(
                codes, csv_mgr, j, v, args.start, args.end,
                args.take_profit, args.hold_days, args.fee,
            )
            rows.append((j, v, stats))
            print(
                f"[sweep] J_BUY={j:>5} VOL>={v:>4} -> "
                f"信号 {stats['signals']:>4} 笔 {stats['total_trades']:>3} "
                f"胜率 {stats['win_rate']:>6.2f}% 盈亏比 {stats['profit_loss_ratio']:>5.2f} "
                f"回撤 {stats['max_drawdown_pct']:>6.2f}%"
            )

    # 输出 Markdown 表，方便贴回优化计划文档
    print("\n=== Markdown 表 ===\n")
    print("| J_BUY | VOL_RATIO | 信号 | 交易 | 胜率% | 盈亏比 | 最大回撤% | 平均持仓 |")
    print("|---|---|---|---|---|---|---|---|")
    for j, v, s in rows:
        print(
            f"| {j} | {v} | {s['signals']} | {s['total_trades']} | "
            f"{s['win_rate']:.2f} | {s['profit_loss_ratio']:.2f} | "
            f"{s['max_drawdown_pct']:.2f} | {s['avg_holding_days']:.2f} |"
        )


if __name__ == "__main__":
    main()
