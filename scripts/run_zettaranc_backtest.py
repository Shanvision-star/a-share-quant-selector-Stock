"""
Zettaranc 组合策略离线回测脚本
==================================

目标：用 ZettarancComboStrategy 在本地 CSV 历史上跑一遍，输出
胜率、盈亏比、最大回撤、平均持仓天数、命中分布与按月统计，
供决定后续 ②持仓看板/③盘中扫描 是否值得继续投入。

设计要点：
  1) 不依赖 web 后端，也不调用 backtest_engine（避免被引擎的 ST/涨停拦截
     干扰 zettaranc 规则本身的实证），用一个自带的逐笔模拟器替代。
  2) 出场规则（v1）：止盈 +15% / 止损 跌破买入日最低 / 时间止损 20 日。
  3) 数据全部走本地 ``data/{prefix}/{code}.csv``；CSV 缺失或不足
     ``MIN_HISTORY`` 自动跳过并在报告里计数。
  4) 输出落到 ``output/zettaranc_backtest_<ts>.json`` 与 ``.md``。

CLI 用法：
    python scripts/run_zettaranc_backtest.py \
        --start 2024-01-01 --end 2026-05-28 \
        --pool local_all --limit 200
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy.zettaranc_combo import MIN_HISTORY, ZettarancComboStrategy  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402


# 离线回测的默认阈值集中到 config/strategy_params.yaml 的 ZettarancComboStrategy 节，
# 与在线扫描共用同一份配置，避免口径漂移（优化计划 P1#3）。下列硬编码仅作兜底。
_YAML_FALLBACK = {
    "J_BUY": 0.0,
    "VOL_RATIO_MIN": 1.3,
    "take_profit_pct": 15.0,
    "hold_days_limit": 20,
    "fee_pct": 0.05,
}


def load_zettaranc_defaults() -> dict:
    """读取 yaml 中 ZettarancComboStrategy 默认值；缺失字段用硬编码兜底。"""
    cfg_path = ROOT / "config" / "strategy_params.yaml"
    defaults = dict(_YAML_FALLBACK)
    try:
        import yaml  # 局部导入：脚本独立运行时才需要 PyYAML

        with cfg_path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        section = data.get("ZettarancComboStrategy", {}) or {}
        for key in defaults:
            if key in section and section[key] is not None:
                defaults[key] = section[key]
    except Exception as exc:  # noqa: BLE001  配置读取失败不应阻断回测
        print(f"[zettaranc-bt] [WARN] 读取 yaml 默认值失败，改用兜底：{exc}")
    return defaults


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    """单笔交易记录。"""
    code: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str          # take_profit / stop_loss / time_stop / end_of_data
    holding_days: int
    pnl_pct: float            # (exit - entry) / entry, 已扣除手续费
    category: str             # 命中分类（bowl_center 等）


@dataclass
class BacktestReport:
    """聚合报告结构。"""
    config: dict
    total_signals: int = 0
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    profit_loss_ratio: float = 0.0      # |平均盈利 / 平均亏损|
    avg_holding_days: float = 0.0
    max_drawdown_pct: float = 0.0
    exit_reason_counts: dict = field(default_factory=dict)
    category_counts: dict = field(default_factory=dict)
    monthly_pnl: dict = field(default_factory=dict)
    skipped_codes: int = 0
    trades: list[Trade] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 股票池来源
# ---------------------------------------------------------------------------
def list_local_codes(data_dir: Path) -> list[str]:
    """扫描 ``data/<prefix>/<code>.csv`` 目录，返回所有股票代码。

    只返回 6 位数字代码，过滤 README/缓存等噪声文件。
    """
    codes: set[str] = set()
    for sub in data_dir.iterdir():
        if not sub.is_dir():
            continue
        for csv_path in sub.glob("*.csv"):
            stem = csv_path.stem
            if stem.isdigit() and len(stem) == 6:
                codes.add(stem)
    return sorted(codes)


def load_pool(pool_spec: str, data_dir: Path) -> list[str]:
    """根据 ``--pool`` 参数解析股票池。"""
    if pool_spec.startswith("file:"):
        path = Path(pool_spec[len("file:"):])
        if not path.is_absolute():
            path = ROOT / path
        return [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    if pool_spec == "local_all":
        return list_local_codes(data_dir)
    raise ValueError(f"未知 pool: {pool_spec}（仅支持 local_all 或 file:xxx）")


# ---------------------------------------------------------------------------
# 单笔交易模拟（出场规则 X1 止损 + X4 止盈 + X2 连续2日破BBI + X3 时间止损）
# ---------------------------------------------------------------------------
def simulate_trade(
    df_asc: pd.DataFrame,
    entry_idx: int,
    *,
    take_profit_pct: float,
    hold_days_limit: int,
    fee_pct: float,
    category: str,
) -> Trade | None:
    """从 ``entry_idx``（信号日索引，正序）开始模拟一笔交易。

    买入：信号次日开盘价；
    卖出：逐日检查 X1 止损 / X4 止盈 / X2 连续2日破BBI / X3 时间止损，取最早触发。
    收益率口径：``(exit - entry) / entry * (1 - 2*fee_pct)``。
    """
    code = df_asc["code"].iloc[0] if "code" in df_asc.columns else ""

    next_idx = entry_idx + 1
    if next_idx >= len(df_asc):
        return None  # 没有次日数据，跳过

    entry_row = df_asc.iloc[entry_idx]
    entry_next = df_asc.iloc[next_idx]
    entry_price = float(entry_next["open"])
    if entry_price <= 0:
        return None

    stop_loss = float(entry_row["low"])  # X1：跌破买入日最低
    take_profit_price = entry_price * (1 + take_profit_pct / 100.0)

    exit_idx = None
    exit_price = None
    exit_reason = None
    bbi_break_streak = 0  # X2：连续收盘破 BBI 的天数计数
    for i in range(next_idx, min(len(df_asc), next_idx + hold_days_limit + 1)):
        row = df_asc.iloc[i]
        # 跌破止损：当日最低 < stop_loss → 以 stop_loss 触发（保守）
        if float(row["low"]) <= stop_loss:
            exit_idx = i
            exit_price = stop_loss
            exit_reason = "stop_loss"
            break
        # 触及止盈：当日最高 >= take_profit_price → 以 take_profit_price 触发
        if float(row["high"]) >= take_profit_price:
            exit_idx = i
            exit_price = take_profit_price
            exit_reason = "take_profit"
            break
        # X2 连续 2 日收盘破 BBI：收盘价 < 当日 BBI 累计两根 → 次根收盘离场。
        # BBI 为 NaN（数据不足）时不计入破位，避免误触发。
        bbi_val = row.get("bbi")
        if bbi_val is not None and not pd.isna(bbi_val) and float(row["close"]) < float(bbi_val):
            bbi_break_streak += 1
            if bbi_break_streak >= 2:
                exit_idx = i
                exit_price = float(row["close"])
                exit_reason = "break_bbi"
                break
        else:
            bbi_break_streak = 0

    if exit_idx is None:
        # 时间止损：用最后一根可见 K 线的收盘价
        last_visible = min(len(df_asc) - 1, next_idx + hold_days_limit)
        exit_idx = last_visible
        exit_price = float(df_asc.iloc[exit_idx]["close"])
        exit_reason = "time_stop" if last_visible == next_idx + hold_days_limit else "end_of_data"

    holding_days = exit_idx - next_idx
    raw_pct = (exit_price - entry_price) / entry_price * 100.0
    # 双边手续费扣减：fee_pct 已是"百分点"口径（如 0.05 即 0.05%/万分之5），
    # 买入+卖出共两次，直接减 2*fee_pct 个百分点。
    # 修复历史 bug：此前误写为 2*fee_pct*100，把单边费率放大了 100 倍
    # （每笔往返扣 10 个百分点而非 0.1），导致盈亏比/胜率严重失真。
    pnl_pct = raw_pct - 2 * fee_pct

    return Trade(
        code=str(code),
        entry_date=str(entry_next["date"])[:10],
        entry_price=round(entry_price, 4),
        exit_date=str(df_asc.iloc[exit_idx]["date"])[:10],
        exit_price=round(float(exit_price), 4),
        exit_reason=exit_reason,
        holding_days=int(holding_days),
        pnl_pct=round(pnl_pct, 4),
        category=category,
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def backtest_one_code(
    code: str,
    csv_mgr: CSVManager,
    strat: ZettarancComboStrategy,
    *,
    start_date: str,
    end_date: str,
    take_profit_pct: float,
    hold_days_limit: int,
    fee_pct: float,
) -> tuple[list[Trade], int]:
    """对单只股票跑回测，返回 (trades, signal_count)。"""
    df = csv_mgr.read_stock(code)
    if df.empty or len(df) < MIN_HISTORY:
        return [], 0
    if "date" not in df.columns:
        return [], 0

    # CSV 是倒序（新→旧），策略指标层默认就吃倒序；这里我们额外保留正序版本
    # 供成交模拟用。两份共用 close/high/low/open/date，互不污染。
    df = df.copy()
    df["date"] = df["date"].astype(str).str[:10]
    indicators_df = strat.calculate_indicators(df)

    # 枚举历史信号
    history_signals = strat.scan_history(
        indicators_df, start_date=start_date, end_date=end_date,
    )
    if not history_signals:
        return [], 0

    # 准备正序 df 用于成交模拟
    df_asc = df.sort_values("date").reset_index(drop=True)
    df_asc["code"] = code
    # 把策略层已算好的 BBI 按日期映射回正序序列，供 X2 出场使用。
    # 复用 indicators_df 的 bbi 列，避免在两处重复实现导致口径不一致。
    bbi_by_date = dict(zip(indicators_df["date"].astype(str).str[:10], indicators_df["bbi"]))
    df_asc["bbi"] = df_asc["date"].map(bbi_by_date)
    date_to_idx = {row_date: idx for idx, row_date in enumerate(df_asc["date"].tolist())}

    trades: list[Trade] = []
    # 同一只股票若已持仓，跳过新信号（简化：单股仅持一仓）
    last_exit_idx = -1
    for sig in history_signals:
        sig_date = sig["signal_date"]
        if sig_date not in date_to_idx:
            continue
        entry_idx = date_to_idx[sig_date]
        if entry_idx <= last_exit_idx:
            continue
        trade = simulate_trade(
            df_asc,
            entry_idx,
            take_profit_pct=take_profit_pct,
            hold_days_limit=hold_days_limit,
            fee_pct=fee_pct,
            category=sig.get("category", ""),
        )
        if trade is None:
            continue
        trades.append(trade)
        # 找到出场日索引以便单股下一次进场判定
        last_exit_idx = date_to_idx.get(trade.exit_date, entry_idx)

    return trades, len(history_signals)


def aggregate(trades: list[Trade]) -> dict:
    """聚合统计指标。"""
    if not trades:
        return {
            "total_trades": 0, "win_count": 0, "loss_count": 0,
            "win_rate": 0.0, "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
            "profit_loss_ratio": 0.0, "avg_holding_days": 0.0,
            "max_drawdown_pct": 0.0,
            "exit_reason_counts": {}, "category_counts": {}, "monthly_pnl": {},
        }
    wins = [t.pnl_pct for t in trades if t.pnl_pct > 0]
    losses = [t.pnl_pct for t in trades if t.pnl_pct <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    holding = sum(t.holding_days for t in trades) / len(trades)

    # 简易最大回撤：把所有交易按入场日排序，构建累计净值，看 peak-to-trough
    ordered = sorted(trades, key=lambda t: t.entry_date)
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for t in ordered:
        equity *= 1 + t.pnl_pct / 100.0
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100.0
        max_dd = max(max_dd, dd)

    exit_counts: dict = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
    cat_counts: dict = {}
    for t in trades:
        cat_counts[t.category or "unknown"] = cat_counts.get(t.category or "unknown", 0) + 1
    monthly: dict = {}
    for t in trades:
        month = t.entry_date[:7]
        monthly[month] = round(monthly.get(month, 0.0) + t.pnl_pct, 4)

    return {
        "total_trades": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100.0, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_loss_ratio": round(ratio, 2),
        "avg_holding_days": round(holding, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "exit_reason_counts": exit_counts,
        "category_counts": cat_counts,
        "monthly_pnl": monthly,
    }


def render_markdown(report: BacktestReport, top_n: int = 20) -> str:
    """把 BacktestReport 渲染为可读 Markdown，便于直接看。"""
    cfg = report.config
    md = [
        "# Zettaranc 回测报告",
        "",
        f"- 区间：`{cfg.get('start')}` ~ `{cfg.get('end')}`",
        f"- 股票池：`{cfg.get('pool')}`（实际跑了 {cfg.get('codes_run')} 只，跳过 {report.skipped_codes} 只）",
        f"- 止盈：+{cfg.get('take_profit_pct')}%，时间止损：{cfg.get('hold_days_limit')} 日，手续费：{cfg.get('fee_pct')}% 双边",
        "",
        "## 关键指标",
        "",
        f"- 总信号数：**{report.total_signals}**",
        f"- 总交易数：**{report.total_trades}**",
        f"- 胜率：**{report.win_rate:.2f}%**（赢 {report.win_count} / 输 {report.loss_count}）",
        f"- 平均盈利：**{report.avg_win_pct:.2f}%** / 平均亏损：**{report.avg_loss_pct:.2f}%**",
        f"- 盈亏比：**{report.profit_loss_ratio:.2f}**",
        f"- 平均持仓：**{report.avg_holding_days:.2f}** 日",
        f"- 最大回撤（净值口径）：**{report.max_drawdown_pct:.2f}%**",
        "",
        "## 出场原因分布",
        "",
    ]
    for reason, cnt in sorted(report.exit_reason_counts.items(), key=lambda x: -x[1]):
        md.append(f"- {reason}: {cnt}")
    md += ["", "## 命中分类分布", ""]
    for cat, cnt in sorted(report.category_counts.items(), key=lambda x: -x[1]):
        md.append(f"- {cat}: {cnt}")
    md += ["", "## 月度收益（累加，单位 %）", ""]
    for month in sorted(report.monthly_pnl):
        md.append(f"- {month}: {report.monthly_pnl[month]:+.2f}")
    md += ["", f"## 最近 {top_n} 笔交易（按入场日倒序）", "", "| 入场日 | 代码 | 入场价 | 出场日 | 出场价 | 持仓天 | 收益% | 出场原因 | 分类 |", "|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(report.trades, key=lambda x: x.entry_date, reverse=True)[:top_n]:
        md.append(
            f"| {t.entry_date} | {t.code} | {t.entry_price:.2f} | {t.exit_date} | "
            f"{t.exit_price:.2f} | {t.holding_days} | {t.pnl_pct:+.2f} | {t.exit_reason} | {t.category} |"
        )
    return "\n".join(md) + "\n"


def run(args: argparse.Namespace) -> Path:
    data_dir = ROOT / "data"
    output_dir = ROOT / "output"
    output_dir.mkdir(exist_ok=True)

    csv_mgr = CSVManager(str(data_dir))
    # 默认阈值统一从 yaml 取，CLI 显式传入则覆盖（None 表示未指定）。
    yaml_defaults = load_zettaranc_defaults()
    j_buy = args.j_buy if args.j_buy is not None else float(yaml_defaults["J_BUY"])
    vol_ratio = args.vol_ratio if args.vol_ratio is not None else float(yaml_defaults["VOL_RATIO_MIN"])
    take_profit = args.take_profit if args.take_profit is not None else float(yaml_defaults["take_profit_pct"])
    hold_days = args.hold_days if args.hold_days is not None else int(yaml_defaults["hold_days_limit"])
    fee = args.fee if args.fee is not None else float(yaml_defaults["fee_pct"])
    # 阈值始终显式传入策略，确保在线/回测口径一致。
    strat_params = {"J_BUY": j_buy, "VOL_RATIO_MIN": vol_ratio}
    strat = ZettarancComboStrategy(strat_params)
    codes = load_pool(args.pool, data_dir)
    if args.limit > 0:
        codes = codes[: args.limit]

    print(f"[zettaranc-bt] 待跑股票：{len(codes)} 只；区间 {args.start} ~ {args.end}")
    print(f"[zettaranc-bt] 阈值：J_BUY={j_buy} VOL_RATIO_MIN={vol_ratio} 止盈={take_profit}% 持仓上限={hold_days}日 手续费={fee}%")

    all_trades: list[Trade] = []
    total_signals = 0
    skipped = 0
    for i, code in enumerate(codes, 1):
        if i % 50 == 0:
            print(f"  进度 {i}/{len(codes)}")
        try:
            trades, sig_count = backtest_one_code(
                code, csv_mgr, strat,
                start_date=args.start, end_date=args.end,
                take_profit_pct=take_profit, hold_days_limit=hold_days,
                fee_pct=fee,
            )
        except Exception as exc:  # noqa: BLE001  防御性：单股错误不应中断整体
            print(f"  [WARN] {code} 回测异常：{exc}")
            skipped += 1
            continue
        if sig_count == 0:
            skipped += 1
            continue
        all_trades.extend(trades)
        total_signals += sig_count

    stats = aggregate(all_trades)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = BacktestReport(
        config={
            "start": args.start,
            "end": args.end,
            "pool": args.pool,
            "codes_run": len(codes),
            "take_profit_pct": take_profit,
            "hold_days_limit": hold_days,
            "fee_pct": fee,
            "j_buy": j_buy,
            "vol_ratio_min": vol_ratio,
        },
        total_signals=total_signals,
        total_trades=stats["total_trades"],
        win_count=stats["win_count"],
        loss_count=stats["loss_count"],
        win_rate=stats["win_rate"],
        avg_win_pct=stats["avg_win_pct"],
        avg_loss_pct=stats["avg_loss_pct"],
        profit_loss_ratio=stats["profit_loss_ratio"],
        avg_holding_days=stats["avg_holding_days"],
        max_drawdown_pct=stats["max_drawdown_pct"],
        exit_reason_counts=stats["exit_reason_counts"],
        category_counts=stats["category_counts"],
        monthly_pnl=stats["monthly_pnl"],
        skipped_codes=skipped,
        trades=all_trades,
    )

    json_path = output_dir / f"zettaranc_backtest_{ts}.json"
    md_path = output_dir / f"zettaranc_backtest_{ts}.md"
    json_payload = {
        **{k: v for k, v in report.__dict__.items() if k != "trades"},
        "trades": [t.__dict__ for t in report.trades],
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    # 同时刷新 latest 软指针（前端可只读 latest，不用扫目录）
    latest_path = output_dir / "zettaranc_backtest_latest.json"
    latest_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[zettaranc-bt] 完成。报告：{md_path.name}  数据：{json_path.name}")
    print(
        f"  胜率 {report.win_rate:.2f}% | 盈亏比 {report.profit_loss_ratio:.2f} | "
        f"最大回撤 {report.max_drawdown_pct:.2f}% | 总笔数 {report.total_trades}"
    )
    return json_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Zettaranc 组合策略离线回测")
    parser.add_argument("--start", default="2024-01-01", help="起始信号日（含）")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"), help="结束信号日（含）")
    parser.add_argument("--pool", default="local_all", help="local_all 或 file:scripts/xxx.txt")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 只（0 表示不限）")
    parser.add_argument("--take-profit", type=float, default=None, help="止盈百分比（默认取 yaml）")
    parser.add_argument("--hold-days", type=int, default=None, help="时间止损天数（默认取 yaml）")
    parser.add_argument("--fee", type=float, default=None, help="单边手续费百分比（默认取 yaml，万分之5）")
    parser.add_argument("--j-buy", type=float, default=None, help="覆盖 J 入场阈值（默认取 yaml）")
    parser.add_argument("--vol-ratio", type=float, default=None, help="覆盖量比下限（默认取 yaml）")
    return parser


if __name__ == "__main__":
    args = build_arg_parser().parse_args()
    run(args)
