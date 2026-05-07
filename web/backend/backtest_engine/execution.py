"""执行模拟器。

执行层只做两件事：生成 OrderIntent，并在本地行情上模拟成交结果。
这里不连接 QMT，也不调用任何真实下单接口。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Optional

import pandas as pd

from web.backend.backtest_engine.data_portal import DailyDataPortal, MinuteDataPortal
from web.backend.backtest_engine.models import BacktestParams, MinuteBar, OrderIntent, SignalCandidate


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


def _find_signal_index(frame: pd.DataFrame, signal_date: str) -> Optional[int]:
    signal_ts = pd.to_datetime(signal_date)
    matched = frame.index[frame["date"] >= signal_ts]
    if len(matched) == 0:
        return None
    return int(matched[0])


def _pick_price(row, field: str) -> float:
    return _safe_float(row.get(field), 0.0)


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
    ) -> tuple[list[dict], int, list[OrderIntent]]:
        trades: list[dict] = []
        intents: list[OrderIntent] = []
        skipped = 0
        for candidate in candidates:
            simulated = self.simulate_trade(candidate, params)
            if simulated:
                trade, intent = simulated
                trades.append(trade)
                intents.append(intent)
            else:
                skipped += 1
        return trades, skipped, intents

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

        buy_index = signal_index + int(params.get("buy_offset_days", 1))
        if buy_index >= len(frame):
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
        if buy_index > end_bound_index:
            return None

        holding_days = max(1, int(params.get("holding_days", 5)))
        target_exit_index = min(end_bound_index, buy_index + holding_days)
        buy_row = frame.iloc[buy_index]
        buy_price_field = str(params.get("buy_price", "open"))
        buy_price = _pick_price(buy_row, buy_price_field)
        if buy_price <= 0:
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
        no_gain_days = max(1, int(params.get("no_gain_days", 3)))
        short_break_days = max(1, int(params.get("short_trend_break_days", 2)))
        short_drawdown_pct = _safe_float(params.get("short_trend_drawdown_pct"), 5.0)

        remaining = 1.0
        exits: list[dict] = []
        runner_triggered = False
        next_profit_ladder_pct = profit_trigger_pct + profit_step_pct
        short_break_streak = 0

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

            if runner_triggered and profit_step_pct > 0 and profit_sell_pct > 0:
                while remaining > 0 and current_high_pct >= next_profit_ladder_pct:
                    exit_price = buy_price * (1 + next_profit_ladder_pct / 100)
                    remaining = _append_exit(
                        exits,
                        row,
                        exit_price,
                        min(remaining, profit_sell_pct / 100),
                        f"profit_ladder_{next_profit_ladder_pct:.1f}pct",
                        remaining,
                        fee_rate,
                        slippage_rate,
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
            final_row = frame.iloc[target_exit_index]
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
        }
        intent = OrderIntent.from_candidate(
            candidate,
            side="BUY",
            planned_at=buy_row["date"],
            price_type=buy_price_field,
            target_price=buy_price,
            quantity=_safe_int(params.get("intent_quantity"), 0),
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
    ) -> tuple[list[dict], int, list[OrderIntent]]:
        trades: list[dict] = []
        intents: list[OrderIntent] = []
        skipped = 0
        for candidate in candidates:
            simulated = self.simulate_trade(candidate, params)
            if simulated:
                trade, trade_intents = simulated
                trades.append(trade)
                intents.extend(trade_intents)
            else:
                skipped += 1
        return trades, skipped, intents

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
        sell_bar = _first_bar_at_or_after(bars, buy_date, str(params.get("minute_sell_time", "14:55")))
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
        quantity = _safe_int(params.get("intent_quantity"), 0)
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
