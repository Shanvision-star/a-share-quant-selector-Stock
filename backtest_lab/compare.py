"""最小回测样本对比工具。

对比对象：
1. 本项目生产回测引擎。
2. 内置事件驱动参考模型。
3. 可选 backtesting.py 外部框架适配器。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
from typing import Any

import pandas as pd

from backtest_lab.sample_data import (
    SAMPLE_CODE,
    build_sample_candidate,
    build_sample_frame,
    build_sample_params,
)
from web.backend.backtest_engine.data_portal import InMemoryDailyDataPortal
from web.backend.backtest_engine.engine import BacktestEngine
from web.backend.backtest_engine.signal_source import StaticSignalSource


def _round_pct(value: float) -> float:
    return round(float(value), 2)


def _summarize_project_result(result: dict[str, Any]) -> dict[str, Any]:
    trade = (result.get("trades") or [{}])[0]
    return {
        "status": "passed" if result.get("summary", {}).get("trade_count") == 1 else "failed",
        "trade_count": int(result.get("summary", {}).get("trade_count", 0)),
        "buy_date": trade.get("buy_date"),
        "sell_date": trade.get("sell_date"),
        "buy_price": trade.get("buy_price"),
        "sell_price": trade.get("sell_price"),
        "return_pct": trade.get("return_pct", 0.0),
    }


def run_project_engine(frame: pd.DataFrame | None = None) -> dict[str, Any]:
    """运行本项目 BacktestEngine。"""
    frame = build_sample_frame() if frame is None else frame
    candidate = build_sample_candidate()
    engine = BacktestEngine(
        signal_source=StaticSignalSource([candidate]),
        daily_portal=InMemoryDailyDataPortal({candidate.code: frame}),
    )
    return _summarize_project_result(engine.run_daily(build_sample_params()))


def run_reference_event_model(frame: pd.DataFrame | None = None) -> dict[str, Any]:
    """用最小事件模型复现同一交易规则，作为外部框架适配前的基准。"""
    frame = (build_sample_frame() if frame is None else frame).sort_values("date").reset_index(drop=True)
    params = build_sample_params()
    signal_date = pd.to_datetime(build_sample_candidate().signal_date)
    signal_indexes = frame.index[frame["date"] >= signal_date]
    if len(signal_indexes) == 0:
        return {"status": "failed", "trade_count": 0, "reason": "signal_date_not_found"}

    buy_index = int(signal_indexes[0]) + int(params.get("buy_offset_days", 1))
    sell_index = buy_index + int(params.get("holding_days", 1))
    if sell_index >= len(frame):
        return {"status": "failed", "trade_count": 0, "reason": "not_enough_future_bars"}

    buy_row = frame.iloc[buy_index]
    sell_row = frame.iloc[sell_index]
    buy_price = float(buy_row[params.get("buy_price", "close")])
    sell_price = float(sell_row[params.get("sell_price", "close")])
    return {
        "status": "passed",
        "trade_count": 1,
        "buy_date": buy_row["date"].strftime("%Y-%m-%d"),
        "sell_date": sell_row["date"].strftime("%Y-%m-%d"),
        "buy_price": round(buy_price, 3),
        "sell_price": round(sell_price, 3),
        "return_pct": _round_pct((sell_price / buy_price - 1) * 100),
    }


def run_backtesting_py_model(frame: pd.DataFrame | None = None) -> dict[str, Any]:
    """可选运行 backtesting.py；未安装时结构化返回 missing。"""
    try:
        from backtesting import Backtest, Strategy
    except Exception as exc:  # pragma: no cover - 依赖缺失时只报告状态
        return {"status": "missing", "reason": str(exc)}

    frame = (build_sample_frame() if frame is None else frame).sort_values("date").reset_index(drop=True)
    bt_frame = frame.rename(
        columns={
            "date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    ).set_index("Date")
    params = build_sample_params()
    buy_index = int(params.get("buy_offset_days", 1))
    sell_index = buy_index + int(params.get("holding_days", 1))

    class LabStrategy(Strategy):
        """固定信号策略，只用于 lab 小样本。"""

        def init(self):
            pass

        def next(self):
            current_index = len(self.data.Close) - 1
            if current_index == buy_index and not self.position:
                self.buy(size=1)
            elif current_index == sell_index and self.position:
                self.position.close()

    try:
        with contextlib.redirect_stderr(io.StringIO()):
            stats = Backtest(
                bt_frame,
                LabStrategy,
                cash=100_000,
                commission=0,
                trade_on_close=True,
                finalize_trades=True,
            ).run()
        trades = stats.get("_trades")
        if trades is None or trades.empty:
            return {"status": "failed", "trade_count": 0, "reason": "no_trade"}
        trade = trades.iloc[0]
        return {
            "status": "passed",
            "trade_count": int(len(trades)),
            "buy_date": pd.to_datetime(trade["EntryTime"]).strftime("%Y-%m-%d"),
            "sell_date": pd.to_datetime(trade["ExitTime"]).strftime("%Y-%m-%d"),
            "buy_price": round(float(trade["EntryPrice"]), 3),
            "sell_price": round(float(trade["ExitPrice"]), 3),
            "return_pct": _round_pct(float(trade["ReturnPct"]) * 100),
        }
    except Exception as exc:  # pragma: no cover - 外部框架异常不阻断主对比
        return {"status": "failed", "reason": str(exc)}


def build_diffs(project: dict[str, Any], reference: dict[str, Any]) -> list[dict[str, Any]]:
    """比较核心字段差异。"""
    diffs = []
    for key in ("trade_count", "buy_date", "sell_date"):
        if project.get(key) != reference.get(key):
            diffs.append({"field": key, "project": project.get(key), "reference": reference.get(key)})
    if abs(float(project.get("return_pct", 0)) - float(reference.get("return_pct", 0))) > 0.01:
        diffs.append(
            {
                "field": "return_pct",
                "project": project.get("return_pct"),
                "reference": reference.get("return_pct"),
            }
        )
    return diffs


def run_minimal_comparison(include_backtesting_py: bool = True) -> dict[str, Any]:
    """运行 1 只股票、1 个信号、20 日样本对比。"""
    frame = build_sample_frame()
    project = run_project_engine(frame)
    reference = run_reference_event_model(frame)
    result = {
        "sample": {
            "code": SAMPLE_CODE,
            "bar_count": int(len(frame)),
            "signal_date": build_sample_candidate().signal_date,
        },
        "project_engine": project,
        "reference_event_model": reference,
        "diffs": build_diffs(project, reference),
    }
    if include_backtesting_py:
        result["backtesting_py"] = run_backtesting_py_model(frame)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 backtest_lab 最小样本对比")
    parser.add_argument("--no-backtesting-py", action="store_true", help="不运行 backtesting.py 可选适配器")
    args = parser.parse_args(argv)
    print(json.dumps(run_minimal_comparison(not args.no_backtesting_py), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
