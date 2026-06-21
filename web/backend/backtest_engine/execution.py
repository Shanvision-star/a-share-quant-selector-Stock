"""执行模拟器。

执行层只做两件事：生成 OrderIntent，并在本地行情上模拟成交结果。
这里不连接 QMT，也不调用任何真实下单接口。
"""

from __future__ import annotations

from collections import defaultdict
import time
from typing import Optional

import pandas as pd

from utils.trading_calendar import advance_a_share_trading_days
from web.backend.backtest_engine.data_portal import DailyDataPortal, MinuteDataPortal
from web.backend.backtest_engine.models import BacktestParams, MinuteBar, OrderIntent, SignalCandidate


def _new_execution_runtime() -> dict:
    return {
        "processed_count": 0,
        "elapsed_seconds": 0.0,
        "stopped_early": False,
        "warnings": [],
    }


def _runtime_budget_seconds(params: BacktestParams) -> float:
    return max(0.0, _safe_float(params.get("max_runtime_seconds"), 0.0))


def _budget_exhausted(started_at: float, budget_seconds: float, processed_count: int) -> bool:
    return budget_seconds > 0 and processed_count > 0 and (time.perf_counter() - started_at) >= budget_seconds


def _safe_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _round_lot_quantity(quantity: int, lot_size: int = 100) -> int:
    if quantity <= 0 or lot_size <= 0:
        return max(0, quantity)
    return (quantity // lot_size) * lot_size


def _clamp_pct(value, default: float = 0.0) -> float:
    return max(0.0, min(100.0, _safe_float(value, default)))


def _find_signal_index(frame: pd.DataFrame, signal_date: str) -> Optional[int]:
    signal_ts = pd.to_datetime(signal_date)
    matched = frame.index[frame["date"] >= signal_ts]
    if len(matched) == 0:
        return None
    return int(matched[0])


def _find_exact_date_index(frame: pd.DataFrame, target_day) -> Optional[int]:
    matched = frame.index[frame["date"].dt.date == target_day]
    if len(matched) == 0:
        return None
    return int(matched[0])


def _find_buy_index(frame: pd.DataFrame, signal_date: str, buy_offset_days: int) -> Optional[int]:
    signal_day = pd.to_datetime(signal_date).date()
    buy_day = advance_a_share_trading_days(signal_day, buy_offset_days)
    return _find_exact_date_index(frame, buy_day)


def _pick_price(row, field: str) -> float:
    return _safe_float(row.get(field), 0.0)


def _is_st_stock(candidate: SignalCandidate) -> bool:
    text = f"{candidate.name}{candidate.strategy_name}".upper()
    return "ST" in text or "退" in text


def _is_tradeable_row(row) -> bool:
    # A 股停牌或坏数据常表现为成交量缺失/为 0；没有明确正成交量时不能模拟成交。
    volume = _safe_float(row.get("volume"), 0.0)
    prices = [_safe_float(row.get(field), 0.0) for field in ("open", "high", "low", "close")]
    return volume > 0 and all(price > 0 for price in prices)


def _previous_close(frame: pd.DataFrame, index: int) -> float:
    row = frame.iloc[index]
    prev_close = _safe_float(row.get("prev_close"), 0.0)
    if prev_close > 0:
        return prev_close
    if index <= 0:
        return 0.0
    return _safe_float(frame.iloc[index - 1].get("close"), 0.0)


def _limit_pct(candidate: SignalCandidate) -> float:
    if _is_st_stock(candidate):
        return 0.05
    if candidate.code.startswith(("300", "301", "688")):
        return 0.20
    return 0.10


def _is_limit_up_locked(row, prev_close: float, limit_pct: float) -> bool:
    if prev_close <= 0:
        return False
    limit_price = round(prev_close * (1 + limit_pct), 2)
    low_price = _safe_float(row.get("low"), 0.0)
    open_price = _safe_float(row.get("open"), 0.0)
    return low_price >= limit_price * 0.999 and open_price >= limit_price * 0.999


def _is_limit_down_locked(row, prev_close: float, limit_pct: float) -> bool:
    if prev_close <= 0:
        return False
    limit_price = round(prev_close * (1 - limit_pct), 2)
    high_price = _safe_float(row.get("high"), 0.0)
    open_price = _safe_float(row.get("open"), 0.0)
    return high_price <= limit_price * 1.001 and open_price <= limit_price * 1.001


def _find_sellable_index(frame: pd.DataFrame, start_index: int, end_index: int, candidate: SignalCandidate) -> Optional[int]:
    for index in range(start_index, end_index + 1):
        row = frame.iloc[index]
        if not _is_tradeable_row(row):
            continue
        prev_close = _previous_close(frame, index)
        if _is_limit_down_locked(row, prev_close, _limit_pct(candidate)):
            continue
        return index
    return None


def _resolve_minute_sell_date(
    bars: list[MinuteBar],
    buy_date,
    holding_days: int,
):
    """按交易日序列解析分钟级卖出日，强制 T+1 以后才允许卖出。"""
    dates = sorted({bar.ts.date() for bar in bars})
    if buy_date not in dates:
        return None
    buy_index = dates.index(buy_date)
    target_index = buy_index + max(1, holding_days)
    if target_index >= len(dates):
        return None
    return dates[target_index]


def _append_exit(
    exits: list[dict],
    row,
    price: float,
    portion: float,
    reason: str,
    remaining_before: float,
    fee_rate: float,
    slippage_rate: float,
):
    portion = max(0.0, min(portion, remaining_before))
    if portion <= 0 or price <= 0:
        return remaining_before
    exits.append(
        {
            "date": row["date"].strftime("%Y-%m-%d"),
            "price": round(price, 3),
            "portion_pct": round(portion * 100, 2),
            "reason": reason,
            "exit_reason": reason,
            "fee_slippage_pct": round((fee_rate + slippage_rate) * 100, 4),
        }
    )
    return max(0.0, remaining_before - portion)


class DailyExecutionSimulator:
    """日线执行模拟器，承接旧 backtest_service 的交易逻辑。"""

    def __init__(self, daily_portal: DailyDataPortal):
        self.daily_portal = daily_portal

    def run(
        self,
        candidates: list[SignalCandidate],
        params: BacktestParams,
        progress_callback=None,
    ) -> tuple[list[dict], int, list[OrderIntent], dict]:
        trades: list[dict] = []
        intents: list[OrderIntent] = []
        skipped = 0
        runtime = _new_execution_runtime()
        started_at = time.perf_counter()
        budget_seconds = _runtime_budget_seconds(params)
        for candidate in candidates:
            if _budget_exhausted(started_at, budget_seconds, runtime["processed_count"]):
                remaining_count = len(candidates) - runtime["processed_count"]
                skipped += remaining_count
                runtime["stopped_early"] = True
                runtime["warnings"].append(
                    f"回测运行预算 {budget_seconds:.2f} 秒已耗尽，剩余 {remaining_count} 个候选未处理"
                )
                break
            runtime["processed_count"] += 1
            simulated = self.simulate_trade(candidate, params)
            if simulated:
                trade, intent = simulated
                trades.append(trade)
                intents.append(intent)
            else:
                skipped += 1
            if progress_callback:
                progress_callback(
                    {
                        "total_count": len(candidates),
                        "processed_count": runtime["processed_count"],
                        "current_code": candidate.code,
                        "trade_count": len(trades),
                        "skipped_count": skipped,
                    }
                )
        runtime["elapsed_seconds"] = round(time.perf_counter() - started_at, 4)
        return trades, skipped, intents, runtime

    def simulate_trade(
        self,
        candidate: SignalCandidate,
        params: BacktestParams,
    ) -> Optional[tuple[dict, OrderIntent]]:
        if not candidate.code or not candidate.signal_date:
            return None

        frame = self.daily_portal.get_daily_frame(candidate.code)
        if frame.empty:
            return None

        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date").reset_index(drop=True)
        signal_index = _find_signal_index(frame, candidate.signal_date)
        if signal_index is None:
            return None

        buy_index = _find_buy_index(frame, candidate.signal_date, int(params.get("buy_offset_days", 1)))
        if buy_index is None or buy_index < signal_index:
            return None

        simulation_end_date = (
            params.get("simulation_end_date")
            or params.get("price_end_date")
            or params.get("backtest_end_date")
        )
        if simulation_end_date:
            end_ts = pd.to_datetime(simulation_end_date)
            end_matches = frame.index[frame["date"] <= end_ts]
            if len(end_matches) == 0:
                return None
            end_bound_index = int(end_matches[-1])
        else:
            end_bound_index = len(frame) - 1
        if buy_index >= end_bound_index:
            return None

        holding_days = max(1, int(params.get("holding_days", 5)))
        target_exit_index = min(end_bound_index, buy_index + holding_days)
        buy_row = frame.iloc[buy_index]
        buy_price_field = str(params.get("buy_price", "open"))
        buy_price = _pick_price(buy_row, buy_price_field)
        if buy_price <= 0:
            return None
        if _is_st_stock(candidate) and not bool(params.get("allow_st_buy", False)):
            return None
        if not _is_tradeable_row(buy_row):
            return None
        prev_close = _previous_close(frame, buy_index)
        if _is_limit_up_locked(buy_row, prev_close, _limit_pct(candidate)):
            return None

        legacy_take_profit_pct = _safe_float(params.get("take_profit_pct"), 0.0)
        stop_loss_pct = _safe_float(params.get("stop_loss_pct"), 0.0)
        sell_price_field = str(params.get("sell_price", "close"))
        fee_rate = _safe_float(params.get("fee_rate"), 0.0003)
        slippage_rate = _safe_float(params.get("slippage_rate"), 0.0005)
        profit_run_enabled = bool(params.get("profit_run_enabled", True))
        profit_trigger_pct = _safe_float(params.get("profit_trigger_pct"), 5.0)
        profit_step_pct = max(0.0, _safe_float(params.get("profit_step_pct"), 10.0))
        profit_sell_pct = max(0.0, min(100.0, _safe_float(params.get("profit_sell_pct"), 25.0)))
        profit_keep_pct = _clamp_pct(params.get("profit_keep_pct"), 0.0)
        profit_keep_fraction = profit_keep_pct / 100
        no_gain_days = max(1, int(params.get("no_gain_days", 3)))
        short_break_days = max(1, int(params.get("short_trend_break_days", 2)))
        short_drawdown_pct = _safe_float(params.get("short_trend_drawdown_pct"), 5.0)

        remaining = 1.0
        exits: list[dict] = []
        profit_actions: list[dict] = []
        runner_triggered = False
        next_profit_ladder_pct = profit_trigger_pct + profit_step_pct
        short_break_streak = 0
        hold_core_recorded = False

        for index in range(buy_index + 1, target_exit_index + 1):
            row = frame.iloc[index]
            low_price = _safe_float(row.get("low"), 0.0)
            high_price = _safe_float(row.get("high"), 0.0)
            close_price = _safe_float(row.get("close"), 0.0)
            short_line = _safe_float(row.get("short_term_trend"), 0.0)
            bull_bear_line = _safe_float(row.get("bull_bear_line"), 0.0)

            if short_line > 0 and close_price < short_line:
                short_break_streak += 1
            else:
                short_break_streak = 0

            if stop_loss_pct > 0 and low_price <= buy_price * (1 - stop_loss_pct / 100):
                remaining = _append_exit(
                    exits,
                    row,
                    buy_price * (1 - stop_loss_pct / 100),
                    remaining,
                    "fixed_stop_loss",
                    remaining,
                    fee_rate,
                    slippage_rate,
                )
                break

            if bool(params.get("enable_no_gain_exit", True)) and index - buy_index >= no_gain_days and close_price <= buy_price:
                remaining = _append_exit(exits, row, close_price, remaining, "no_gain_exit", remaining, fee_rate, slippage_rate)
                break

            if bool(params.get("exit_on_bull_bear_break", True)) and bull_bear_line > 0 and close_price < bull_bear_line:
                remaining = _append_exit(exits, row, close_price, remaining, "bull_bear_break", remaining, fee_rate, slippage_rate)
                break

            if bool(params.get("exit_on_short_trend_drawdown", True)) and short_line > 0 and close_price <= short_line * (1 - short_drawdown_pct / 100):
                remaining = _append_exit(exits, row, close_price, remaining, "short_trend_drawdown", remaining, fee_rate, slippage_rate)
                break

            if bool(params.get("exit_on_short_trend_break", True)) and short_break_streak >= short_break_days:
                remaining = _append_exit(exits, row, close_price, remaining, "short_trend_break_days", remaining, fee_rate, slippage_rate)
                break

            current_high_pct = (high_price / buy_price - 1) * 100 if buy_price > 0 else 0.0
            if profit_run_enabled and profit_trigger_pct > 0 and current_high_pct >= profit_trigger_pct:
                runner_triggered = True
                if not profit_actions:
                    profit_actions.append(
                        {
                            "date": row["date"].strftime("%Y-%m-%d"),
                            "action": "enter_runner",
                            "profit_pct": round(current_high_pct, 2),
                            "remaining_pct": round(remaining * 100, 2),
                        }
                    )

            if runner_triggered and profit_step_pct > 0 and profit_sell_pct > 0:
                while remaining > 0 and current_high_pct >= next_profit_ladder_pct:
                    sellable_portion = max(0.0, remaining - profit_keep_fraction)
                    if sellable_portion <= 0:
                        if not hold_core_recorded:
                            profit_actions.append(
                                {
                                    "date": row["date"].strftime("%Y-%m-%d"),
                                    "action": "hold_core",
                                    "profit_pct": round(current_high_pct, 2),
                                    "remaining_pct": round(remaining * 100, 2),
                                    "keep_pct": round(profit_keep_pct, 2),
                                }
                            )
                            hold_core_recorded = True
                        next_profit_ladder_pct += profit_step_pct
                        continue
                    exit_price = buy_price * (1 + next_profit_ladder_pct / 100)
                    portion = min(remaining, sellable_portion, profit_sell_pct / 100)
                    remaining = _append_exit(
                        exits,
                        row,
                        exit_price,
                        portion,
                        f"profit_ladder_{next_profit_ladder_pct:.1f}pct",
                        remaining,
                        fee_rate,
                        slippage_rate,
                    )
                    profit_actions.append(
                        {
                            "date": row["date"].strftime("%Y-%m-%d"),
                            "action": "sell_partial",
                            "profit_pct": round(next_profit_ladder_pct, 2),
                            "sell_pct": round(portion * 100, 2),
                            "remaining_pct": round(remaining * 100, 2),
                        }
                    )
                    next_profit_ladder_pct += profit_step_pct

            if runner_triggered and bool(params.get("hold_above_short_trend_after_trigger", True)) and short_line > 0 and close_price < short_line:
                remaining = _append_exit(exits, row, close_price, remaining, "profit_runner_short_trend_break", remaining, fee_rate, slippage_rate)
                break

            if not profit_run_enabled and legacy_take_profit_pct > 0 and high_price >= buy_price * (1 + legacy_take_profit_pct / 100):
                remaining = _append_exit(
                    exits,
                    row,
                    buy_price * (1 + legacy_take_profit_pct / 100),
                    remaining,
                    "take_profit",
                    remaining,
                    fee_rate,
                    slippage_rate,
                )
                break

        if remaining > 0:
            final_index = _find_sellable_index(frame, target_exit_index, end_bound_index, candidate)
            if final_index is None:
                return None
            final_row = frame.iloc[final_index]
            final_price = _pick_price(final_row, sell_price_field)
            remaining = _append_exit(exits, final_row, final_price, remaining, "holding_days", remaining, fee_rate, slippage_rate)

        if not exits:
            return None

        gross_return = sum((exit_item["price"] / buy_price - 1) * (exit_item["portion_pct"] / 100) for exit_item in exits)
        total_sell_cost = sum((exit_item["portion_pct"] / 100) * (fee_rate + slippage_rate) for exit_item in exits)
        net_return = gross_return - (fee_rate + slippage_rate) - total_sell_cost
        sell_date = exits[-1]["date"]
        sell_price = exits[-1]["price"]
        sell_index = int(frame.index[frame["date"] == pd.to_datetime(sell_date)][-1])
        hold_days = max(1, sell_index - buy_index)

        buy_date = buy_row["date"].strftime("%Y-%m-%d")
        trade = {
            "code": candidate.code,
            "name": candidate.name,
            "strategy_name": candidate.strategy_name,
            "source": candidate.source,
            "signal_date": candidate.signal_date,
            "trade_date": candidate.trade_date,
            "buy_date": buy_date,
            "sell_date": sell_date,
            "buy_price": round(buy_price, 3),
            "sell_price": round(sell_price, 3),
            "hold_days": hold_days,
            "gross_return_pct": round(gross_return * 100, 2),
            "return_pct": round(net_return * 100, 2),
            "exit_reason": exits[-1]["reason"],
            "exits": exits,
            "profit_actions": profit_actions,
        }
        # 任务 C 深度：组合权重模式下，按 position_pct 缩放下单意图股数；权重写入 trade，供 equity_curve 加权聚合
        # 旧默认 position_pct=0 时保持 weight=1.0，原行为不变
        position_pct = _safe_float(params.get("position_pct"), 0.0)
        weight = (position_pct / 100.0) if position_pct > 0 else 1.0
        base_quantity = _safe_int(params.get("intent_quantity"), 0)
        if position_pct > 0 and base_quantity > 0:
            base_quantity = int(base_quantity * weight)
        quantity = _round_lot_quantity(
            base_quantity,
            max(1, _safe_int(params.get("lot_size"), 100)),
        )
        trade["weight"] = round(weight, 6)
        intent = OrderIntent.from_candidate(
            candidate,
            side="BUY",
            planned_at=buy_row["date"],
            price_type=buy_price_field,
            target_price=buy_price,
            quantity=quantity,
        )
        return trade, intent


class MinuteExecutionSimulator:
    """分钟级执行模拟器，用于分时买入验证。"""

    def __init__(self, minute_portal: MinuteDataPortal):
        self.minute_portal = minute_portal

    def run(
        self,
        candidates: list[SignalCandidate],
        params: BacktestParams,
        progress_callback=None,
    ) -> tuple[list[dict], int, list[OrderIntent], dict]:
        trades: list[dict] = []
        intents: list[OrderIntent] = []
        skipped = 0
        runtime = _new_execution_runtime()
        started_at = time.perf_counter()
        budget_seconds = _runtime_budget_seconds(params)
        for candidate in candidates:
            if _budget_exhausted(started_at, budget_seconds, runtime["processed_count"]):
                remaining_count = len(candidates) - runtime["processed_count"]
                skipped += remaining_count
                runtime["stopped_early"] = True
                runtime["warnings"].append(
                    f"回测运行预算 {budget_seconds:.2f} 秒已耗尽，剩余 {remaining_count} 个候选未处理"
                )
                break
            runtime["processed_count"] += 1
            simulated = self.simulate_trade(candidate, params)
            if simulated:
                trade, trade_intents = simulated
                trades.append(trade)
                intents.extend(trade_intents)
            else:
                skipped += 1
            if progress_callback:
                progress_callback(
                    {
                        "total_count": len(candidates),
                        "processed_count": runtime["processed_count"],
                        "current_code": candidate.code,
                        "trade_count": len(trades),
                        "skipped_count": skipped,
                    }
                )
        runtime["elapsed_seconds"] = round(time.perf_counter() - started_at, 4)
        return trades, skipped, intents, runtime

    def simulate_trade(
        self,
        candidate: SignalCandidate,
        params: BacktestParams,
    ) -> Optional[tuple[dict, list[OrderIntent]]]:
        bars = self.minute_portal.get_minute_bars(candidate.code, candidate.signal_date, params.get("simulation_end_date"))
        if not bars:
            return None

        buy_date = _resolve_minute_buy_date(bars, candidate.signal_date, int(params.get("buy_offset_days", 1)))
        if buy_date is None:
            return None

        buy_bar = _first_bar_at_or_after(bars, buy_date, str(params.get("minute_buy_time", "09:35")))
        sell_date = _resolve_minute_sell_date(bars, buy_date, max(1, int(params.get("holding_days", 1))))
        if sell_date is None:
            return None

        sell_bar = _first_bar_at_or_after(bars, sell_date, str(params.get("minute_sell_time", "14:55")))
        if buy_bar is None or sell_bar is None or sell_bar.ts < buy_bar.ts:
            return None

        buy_price_field = str(params.get("minute_buy_price", params.get("buy_price", "open")))
        sell_price_field = str(params.get("minute_sell_price", params.get("sell_price", "close")))
        buy_price = buy_bar.price(buy_price_field)
        sell_price = sell_bar.price(sell_price_field)
        if buy_price <= 0 or sell_price <= 0:
            return None

        fee_rate = _safe_float(params.get("fee_rate"), 0.0003)
        slippage_rate = _safe_float(params.get("slippage_rate"), 0.0005)
        net_return = (sell_price / buy_price - 1) - (fee_rate + slippage_rate) * 2
        # 任务 C 深度：分钟级同理按 position_pct 缩放数量；旧默认 position_pct=0 时不缩放
        position_pct = _safe_float(params.get("position_pct"), 0.0)
        weight = (position_pct / 100.0) if position_pct > 0 else 1.0
        base_quantity = _safe_int(params.get("intent_quantity"), 0)
        if position_pct > 0 and base_quantity > 0:
            base_quantity = int(base_quantity * weight)
        quantity = _round_lot_quantity(
            base_quantity,
            max(1, _safe_int(params.get("lot_size"), 100)),
        )
        intents = [
            OrderIntent.from_candidate(
                candidate,
                side="BUY",
                planned_at=buy_bar.ts,
                price_type=buy_price_field,
                target_price=buy_price,
                quantity=quantity,
            ),
            OrderIntent.from_candidate(
                candidate,
                side="SELL",
                planned_at=sell_bar.ts,
                price_type=sell_price_field,
                target_price=sell_price,
                quantity=quantity,
            ),
        ]
        buy_datetime = buy_bar.ts.strftime("%Y-%m-%d %H:%M:%S")
        sell_datetime = sell_bar.ts.strftime("%Y-%m-%d %H:%M:%S")
        trade = {
            "code": candidate.code,
            "name": candidate.name,
            "strategy_name": candidate.strategy_name,
            "source": candidate.source,
            "signal_date": candidate.signal_date,
            "trade_date": candidate.trade_date,
            "buy_date": buy_bar.ts.strftime("%Y-%m-%d"),
            "sell_date": sell_bar.ts.strftime("%Y-%m-%d"),
            "buy_datetime": buy_datetime,
            "sell_datetime": sell_datetime,
            "buy_price": round(buy_price, 3),
            "sell_price": round(sell_price, 3),
            "hold_days": 1,
            "gross_return_pct": round((sell_price / buy_price - 1) * 100, 2),
            "return_pct": round(net_return * 100, 2),
            "exit_reason": "minute_sell_time",
            "exits": [
                {
                    "date": sell_bar.ts.strftime("%Y-%m-%d"),
                    "datetime": sell_datetime,
                    "price": round(sell_price, 3),
                    "portion_pct": 100.0,
                    "reason": "minute_sell_time",
                    "exit_reason": "minute_sell_time",
                    "fee_slippage_pct": round((fee_rate + slippage_rate) * 100, 4),
                }
            ],
        }
        # 任务 C 深度：分钟级 trade 也带权重，equity_curve 同口径加权
        trade["weight"] = round(weight, 6)
        return trade, intents


def _resolve_minute_buy_date(
    bars: list[MinuteBar],
    signal_date: str,
    buy_offset_days: int,
) -> Optional[pd.Timestamp.date]:
    grouped: dict[object, list[MinuteBar]] = defaultdict(list)
    for bar in bars:
        grouped[bar.ts.date()].append(bar)
    dates = sorted(grouped)
    if not dates:
        return None

    signal_day = pd.to_datetime(signal_date).date()
    start_index = None
    for index, trade_date in enumerate(dates):
        if trade_date >= signal_day:
            start_index = index
            break
    if start_index is None:
        return None

    if dates[start_index] == signal_day:
        target_index = start_index + max(0, buy_offset_days)
    else:
        # 没有信号日分钟线时，第一天可用分钟线通常就是 T+1。
        target_index = start_index + max(0, buy_offset_days - 1)
    if target_index >= len(dates):
        return None
    return dates[target_index]


def _first_bar_at_or_after(
    bars: list[MinuteBar],
    trade_date,
    hhmm: str,
) -> Optional[MinuteBar]:
    target_time = pd.to_datetime(f"{trade_date} {hhmm}").time()
    day_bars = [bar for bar in bars if bar.ts.date() == trade_date and bar.ts.time() >= target_time]
    if not day_bars:
        return None
    return sorted(day_bars, key=lambda item: item.ts)[0]
