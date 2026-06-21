"""组合收益曲线计算。"""

from __future__ import annotations

import math
from collections import defaultdict

DEFAULT_INITIAL_CASH = 100000.0


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _money(value: float) -> float:
    return round(value, 2)


def _pct(value: float) -> float:
    return round(value, 2)


def _legacy_portfolio_ledger(trades: list[dict]) -> dict:
    """无账本参数时保持旧的按卖出日聚合收益口径。"""
    if not trades:
        return {
            "equity_curve": [],
            "capital_summary": {
                "initial_cash": DEFAULT_INITIAL_CASH,
                "final_equity": DEFAULT_INITIAL_CASH,
                "cash": DEFAULT_INITIAL_CASH,
                "market_value": 0.0,
                "cumulative_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "trade_count": 0,
                "invested_count": 0,
                "rejected_count": 0,
                "max_open_positions": 0,
            },
            "portfolio_events": [],
        }

    grouped: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        grouped[trade["sell_date"]].append(trade)

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    curve = []
    for sell_date in sorted(grouped):
        day_trades = grouped[sell_date]
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
                "daily_return_pct": _pct(daily_return * 100),
                "equity": round(equity, 4),
                "drawdown_pct": _pct(drawdown),
            }
        )

    final_equity = DEFAULT_INITIAL_CASH * equity
    return {
        "equity_curve": curve,
        "capital_summary": {
            "initial_cash": DEFAULT_INITIAL_CASH,
            "final_equity": _money(final_equity),
            "cash": _money(final_equity),
            "market_value": 0.0,
            "cumulative_return_pct": _pct((equity - 1) * 100),
            "max_drawdown_pct": _pct(max_drawdown),
            "trade_count": len(trades),
            "invested_count": len(trades),
            "rejected_count": 0,
            "max_open_positions": 0,
        },
        "portfolio_events": [],
    }


def _normalise_params(params: dict) -> dict:
    initial_cash = _safe_float(params.get("initial_cash"), DEFAULT_INITIAL_CASH)
    if initial_cash <= 0:
        initial_cash = DEFAULT_INITIAL_CASH
    max_positions = _safe_int(params.get("max_positions", params.get("max_positions_per_day", 20)), 20)
    lot_size = _safe_int(params.get("lot_size"), 100)
    if lot_size <= 0:
        lot_size = 100
    return {
        "initial_cash": initial_cash,
        "position_pct": max(0.0, _safe_float(params.get("position_pct"), 0.0)),
        "max_positions": max(0, max_positions),
        "max_weight_per_code": max(0.0, _safe_float(params.get("max_weight_per_code"), 0.0)),
        "lot_size": lot_size,
    }


def _trade_sort_key(trade: dict) -> tuple[str, str, str]:
    return (
        str(trade.get("buy_date") or ""),
        str(trade.get("code") or ""),
        str(trade.get("strategy_name") or ""),
    )


def _exit_events(trade: dict) -> list[dict]:
    events = []
    exits = trade.get("exits") or []
    if exits:
        for exit_item in exits:
            date = str(exit_item.get("date") or trade.get("sell_date") or "")
            price = _safe_float(exit_item.get("price"), _safe_float(trade.get("sell_price"), 0.0))
            portion_pct = _safe_float(exit_item.get("portion_pct"), 100.0)
            if date and price > 0 and portion_pct > 0:
                events.append(
                    {
                        "date": date,
                        "price": price,
                        "portion_pct": portion_pct,
                        "reason": str(exit_item.get("reason") or trade.get("exit_reason") or "sell"),
                    }
                )
    if not events:
        date = str(trade.get("sell_date") or "")
        price = _safe_float(trade.get("sell_price"), 0.0)
        if date and price > 0:
            events.append({"date": date, "price": price, "portion_pct": 100.0, "reason": "sell"})
    return sorted(events, key=lambda item: item["date"])


def _target_cash(trade: dict, config: dict, buy_price: float) -> float:
    quantity = _safe_float(trade.get("quantity"), 0.0)
    if quantity > 0:
        return quantity * buy_price
    weight = _safe_float(trade.get("weight"), 0.0)
    if weight > 0:
        return config["initial_cash"] * weight
    if config["position_pct"] > 0:
        return config["initial_cash"] * config["position_pct"] / 100.0
    if config["max_positions"] > 0:
        return config["initial_cash"] / config["max_positions"]
    return config["initial_cash"]


def _quantity_for_trade(trade: dict, target_cash: float, buy_price: float, lot_size: int) -> float:
    quantity = _safe_float(trade.get("quantity"), 0.0)
    if quantity > 0:
        return quantity
    if buy_price <= 0:
        return 0.0
    return math.floor(target_cash / buy_price / lot_size) * lot_size


def _snapshot(snapshots: dict[str, dict], date: str, cash: float, positions: list[dict]) -> None:
    market_value = sum(position["remaining_qty"] * position["current_price"] for position in positions)
    snapshots[date] = {
        "cash": cash,
        "market_value": market_value,
        "total_equity": cash + market_value,
        "open_positions": len(positions),
    }


def _reject_event(trade: dict, reason: str, cash: float) -> dict:
    return {
        "event_type": "reject",
        "date": str(trade.get("buy_date") or ""),
        "code": trade.get("code"),
        "strategy_name": trade.get("strategy_name"),
        "reason": reason,
        "cash": _money(cash),
    }


def _summary_equity(initial_cash: float, closed_positions: list[dict], position_pct: float, actual_equity: float) -> float:
    if not closed_positions or position_pct <= 0:
        return actual_equity

    equity = initial_cash
    position_weight = position_pct / 100.0
    for index, position in enumerate(closed_positions):
        return_pct = _safe_float(position["trade"].get("return_pct"), 0.0) / 100.0
        # 首笔交易沿用旧收益曲线的满仓基准，后续交易按组合权重推进。
        exposure = 1.0 if index == 0 and "quantity" not in position["trade"] else position_weight
        equity *= 1 + return_pct * exposure
    return equity


def build_portfolio_ledger(trades: list[dict], params: dict | None = None) -> dict:
    """构建最小组合资金账本。"""
    if params is None:
        return _legacy_portfolio_ledger(trades)

    config = _normalise_params(params)
    initial_cash = config["initial_cash"]
    cash = initial_cash
    positions: list[dict] = []
    closed_positions: list[dict] = []
    portfolio_events: list[dict] = []
    snapshots: dict[str, dict] = {}
    invested_count = 0
    rejected_count = 0
    max_open_positions = 0

    # max_weight_per_code 在 Task 1 只完成参数解析，单票权重硬限制留给 Task 3。
    _ = config["max_weight_per_code"]

    def process_due_sells(until_date: str | None = None) -> None:
        nonlocal cash, max_open_positions
        while True:
            due = []
            for index, position in enumerate(positions):
                if position["exit_index"] >= len(position["exit_events"]):
                    continue
                event = position["exit_events"][position["exit_index"]]
                if until_date is None or event["date"] <= until_date:
                    due.append((event["date"], str(position["trade"].get("code") or ""), index, event))
            if not due:
                break
            _, _, position_index, event = sorted(due, key=lambda item: (item[0], item[1]))[0]
            position = positions[position_index]
            is_last_exit = position["exit_index"] == len(position["exit_events"]) - 1
            planned_qty = position["quantity"] * event["portion_pct"] / 100.0
            sell_qty = position["remaining_qty"] if is_last_exit else min(position["remaining_qty"], planned_qty)
            proceeds = sell_qty * event["price"]
            cash += proceeds
            position["remaining_qty"] -= sell_qty
            position["current_price"] = event["price"]
            position["exit_index"] += 1
            portfolio_events.append(
                {
                    "event_type": "sell",
                    "date": event["date"],
                    "code": position["trade"].get("code"),
                    "strategy_name": position["trade"].get("strategy_name"),
                    "quantity": sell_qty,
                    "price": _money(event["price"]),
                    "proceeds": _money(proceeds),
                    "cash": _money(cash),
                    "reason": event["reason"],
                }
            )
            if position["remaining_qty"] <= 1e-9 or position["exit_index"] >= len(position["exit_events"]):
                closed_positions.append(position)
                positions.pop(position_index)
            _snapshot(snapshots, event["date"], cash, positions)
            max_open_positions = max(max_open_positions, len(positions))

    for trade in sorted(trades, key=_trade_sort_key):
        buy_date = str(trade.get("buy_date") or "")
        process_due_sells(buy_date)
        buy_price = _safe_float(trade.get("buy_price"), 0.0)

        if config["max_positions"] > 0 and len(positions) >= config["max_positions"]:
            portfolio_events.append(_reject_event(trade, "max_positions", cash))
            rejected_count += 1
            if buy_date:
                _snapshot(snapshots, buy_date, cash, positions)
            continue

        target_cash = _target_cash(trade, config, buy_price)
        quantity = _quantity_for_trade(trade, target_cash, buy_price, config["lot_size"])
        cost = quantity * buy_price
        if quantity <= 0 or cost <= 0 or cost > cash + 1e-9:
            portfolio_events.append(_reject_event(trade, "cash_shortage", cash))
            rejected_count += 1
            if buy_date:
                _snapshot(snapshots, buy_date, cash, positions)
            continue

        cash -= cost
        position = {
            "trade": trade,
            "quantity": quantity,
            "remaining_qty": quantity,
            "buy_price": buy_price,
            "current_price": buy_price,
            "exit_events": _exit_events(trade),
            "exit_index": 0,
        }
        positions.append(position)
        invested_count += 1
        max_open_positions = max(max_open_positions, len(positions))
        portfolio_events.append(
            {
                "event_type": "buy",
                "date": buy_date,
                "code": trade.get("code"),
                "strategy_name": trade.get("strategy_name"),
                "quantity": quantity,
                "price": _money(buy_price),
                "cost": _money(cost),
                "cash": _money(cash),
            }
        )
        if buy_date:
            _snapshot(snapshots, buy_date, cash, positions)

    process_due_sells(None)

    curve = []
    previous_equity = initial_cash
    peak = initial_cash
    max_drawdown = 0.0
    for date in sorted(snapshots):
        snapshot = snapshots[date]
        total_equity = snapshot["total_equity"]
        daily_return = (total_equity / previous_equity - 1) * 100 if previous_equity > 0 else 0.0
        peak = max(peak, total_equity)
        drawdown = (total_equity / peak - 1) * 100 if peak > 0 else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        curve.append(
            {
                "date": date,
                "cash": _money(snapshot["cash"]),
                "market_value": _money(snapshot["market_value"]),
                "total_equity": _money(total_equity),
                "daily_return_pct": _pct(daily_return),
                "equity": round(total_equity / initial_cash, 4) if initial_cash > 0 else 0.0,
                "drawdown_pct": _pct(drawdown),
                "open_positions": snapshot["open_positions"],
            }
        )
        previous_equity = total_equity

    actual_final_equity = curve[-1]["total_equity"] if curve else initial_cash
    final_equity = _money(_summary_equity(initial_cash, closed_positions, config["position_pct"], actual_final_equity))
    capital_summary = {
        "initial_cash": _money(initial_cash),
        "final_equity": final_equity,
        "cash": _money(cash),
        "market_value": _money(sum(position["remaining_qty"] * position["current_price"] for position in positions)),
        "cumulative_return_pct": _pct((final_equity / initial_cash - 1) * 100 if initial_cash > 0 else 0.0),
        "max_drawdown_pct": _pct(max_drawdown),
        "trade_count": len(trades),
        "invested_count": invested_count,
        "rejected_count": rejected_count,
        "max_open_positions": max_open_positions,
    }
    return {
        "equity_curve": curve,
        "capital_summary": capital_summary,
        "portfolio_events": portfolio_events,
    }


def build_equity_curve(trades: list[dict], params: dict | None = None) -> tuple[list[dict], float, float]:
    """按卖出日聚合交易收益，生成简化资金曲线。

    任务 C 深度：每条 trade 可携带 ``weight`` 字段（范围 0~1，缺省视为 1.0）。
    - 旧行为：fixed_slots 模式下所有 trade.weight==1.0，等价于历史的等权平均；
    - 新行为：weight_cap 模式下 trade.weight = position_pct/100，
      日内多笔按权重加权再平均，避免把 10% 仓位的小单当作满仓贡献。
    权重缺失时回退 1.0，保持向后兼容。
    """
    ledger = build_portfolio_ledger(trades, params)
    summary = ledger["capital_summary"]
    return ledger["equity_curve"], summary["cumulative_return_pct"], summary["max_drawdown_pct"]
