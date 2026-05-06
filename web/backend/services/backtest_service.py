"""回测服务：复用策略结果、人工选股池和本地 CSV 行情。"""
from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Optional

import pandas as pd

from utils.csv_manager import CSVManager
from utils.technical import calculate_zhixing_trend
from web.backend.services import manual_selection_service
from web.backend.services import strategy_result_repository as strategy_repo


project_root = Path(__file__).resolve().parents[3]
csv_manager = CSVManager(str(project_root / "data"))
_stock_names_cache: Optional[dict] = None


def _load_stock_names() -> dict:
    global _stock_names_cache
    if _stock_names_cache is not None:
        return _stock_names_cache
    names_path = project_root / 'data' / 'stock_names.json'
    if names_path.exists():
        with open(names_path, 'r', encoding='utf-8') as file:
            _stock_names_cache = json.load(file)
    else:
        _stock_names_cache = {}
    return _stock_names_cache


def _stock_name(code: str) -> str:
    return _load_stock_names().get(code, '')


def _normalize_codes(values) -> list[str]:
    if not values:
        return []
    normalized = []
    for raw in values:
        code = str(raw or '').strip()
        if re.fullmatch(r'\d{6}', code) and code not in normalized:
            normalized.append(code)
    return normalized


def _safe_float(value, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number


def _load_price_frame(code: str) -> pd.DataFrame:
    frame = csv_manager.read_stock(code)
    if frame.empty:
        return frame
    frame = frame.copy()
    frame['date'] = pd.to_datetime(frame['date'])
    for column in ('open', 'high', 'low', 'close'):
        frame[column] = pd.to_numeric(frame[column], errors='coerce')
    frame = frame.dropna(subset=['date', 'open', 'high', 'low', 'close']).sort_values('date').reset_index(drop=True)
    trend = calculate_zhixing_trend(frame)
    frame['short_term_trend'] = trend['short_term_trend']
    frame['bull_bear_line'] = trend['bull_bear_line']
    return frame


def _fetch_strategy_candidates(params: dict, code: Optional[str] = None) -> list[dict]:
    all_items: list[dict] = []
    page = 1
    per_page = 200
    while page <= 100:
        payload = strategy_repo.query_results(
            strategy_filter=params.get('strategy', 'all'),
            start_date=params['start_date'],
            end_date=params['end_date'],
            code=code,
            page=page,
            per_page=per_page,
            sort_by='signal_date',
            sort_order='asc',
        )
        page_items = payload.get('items') or []
        all_items.extend(page_items)
        if len(page_items) < per_page or len(all_items) >= payload.get('total', 0):
            break
        page += 1
    return all_items


def _expand_codes_via_strategy(params: dict, codes: list[str]) -> tuple[list[dict], list[str]]:
    """对每个 input code 展开为策略命中过的 candidate；返回 (展开后的 candidates, 无命中的 code 列表)。"""
    expanded: list[dict] = []
    no_hit: list[str] = []
    for code in codes:
        items = _fetch_strategy_candidates(params, code=code)
        if not items:
            no_hit.append(code)
            continue
        for item in items:
            signal_date = item.get('signal_date') or item.get('trade_date')
            if not signal_date:
                continue
            expanded.append({
                'code': code,
                'name': item.get('name') or _stock_name(code),
                'strategy_name': item.get('strategy_name', ''),
                'trade_date': item.get('trade_date') or signal_date,
                'signal_date': signal_date,
                'source': 'codes',
            })
    return expanded, no_hit


def _fetch_candidates(params: dict) -> list[dict]:
    source = params.get('source', 'manual')
    selected_codes = set(_normalize_codes(params.get('selected_codes')))

    if source == 'strategy' and params.get('selected_candidates'):
        candidates = []
        for item in params.get('selected_candidates') or []:
            signal_date = item.get('signal_date') or item.get('trade_date')
            if not item.get('code') or not signal_date:
                continue
            candidates.append({
                'code': item['code'],
                'name': item.get('name') or _stock_name(item['code']),
                'strategy_name': item.get('strategy_name', ''),
                'trade_date': item.get('trade_date') or signal_date,
                'signal_date': signal_date,
                'source': 'strategy',
            })
        return candidates

    if source == 'codes':
        codes = _normalize_codes(params.get('input_codes'))
        if not codes:
            return []
        expanded, no_hit = _expand_codes_via_strategy(params, codes)
        if no_hit and bool(params.get('codes_fallback_to_start_date', False)):
            for code in no_hit:
                expanded.append({
                    'code': code,
                    'name': _stock_name(code),
                    'strategy_name': '输入个股(无信号回退)',
                    'trade_date': params['start_date'],
                    'signal_date': params['start_date'],
                    'source': 'codes',
                })
        return expanded

    if source == 'manual':
        items = manual_selection_service.list_selections(
            start_date=params['start_date'],
            end_date=params['end_date'],
        )
        candidates = [
            {
                'code': item['code'],
                'name': item.get('name', ''),
                'strategy_name': item.get('strategy_name', 'manual'),
                'trade_date': item['selection_date'],
                'signal_date': item.get('source_signal_date') or item.get('source_trade_date') or item['selection_date'],
                'source': 'manual',
            }
            for item in items
        ]
        return [item for item in candidates if not selected_codes or item['code'] in selected_codes]

    # source == 'strategy' 且未带 selected_candidates：若 input_codes 非空，按 code 分别展开
    input_codes = _normalize_codes(params.get('input_codes'))
    if source == 'strategy' and input_codes:
        expanded, _ = _expand_codes_via_strategy(params, input_codes)
        for item in expanded:
            item['source'] = 'strategy'
        return [item for item in expanded if not selected_codes or item['code'] in selected_codes]

    items = _fetch_strategy_candidates(params)
    candidates = []
    for item in items:
        signal_date = item.get('signal_date') or item.get('trade_date')
        if not item.get('code') or not signal_date:
            continue
        candidates.append({
            'code': item['code'],
            'name': item.get('name', ''),
            'strategy_name': item.get('strategy_name', ''),
            'trade_date': item.get('trade_date') or signal_date,
            'signal_date': signal_date,
            'source': 'strategy',
        })
    return [item for item in candidates if not selected_codes or item['code'] in selected_codes]


def _cap_positions_per_day(candidates: list[dict], max_positions: int) -> list[dict]:
    if max_positions <= 0:
        return candidates
    grouped: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        grouped[str(candidate.get('signal_date') or candidate.get('trade_date') or '')].append(candidate)

    capped: list[dict] = []
    for trade_date in sorted(grouped):
        capped.extend(sorted(grouped[trade_date], key=lambda item: item.get('code', ''))[:max_positions])
    return capped


def _find_signal_index(frame: pd.DataFrame, signal_date: str) -> Optional[int]:
    signal_ts = pd.to_datetime(signal_date)
    matched = frame.index[frame['date'] >= signal_ts]
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
    exits.append({
        'date': row['date'].strftime('%Y-%m-%d'),
        'price': round(price, 3),
        'portion_pct': round(portion * 100, 2),
        'reason': reason,
        'exit_reason': reason,
        'fee_slippage_pct': round((fee_rate + slippage_rate) * 100, 4),
    })
    return max(0.0, remaining_before - portion)


def _simulate_trade(candidate: dict, params: dict) -> Optional[dict]:
    if not candidate.get('code') or not candidate.get('signal_date'):
        return None

    frame = _load_price_frame(candidate['code'])
    if frame.empty:
        return None

    signal_index = _find_signal_index(frame, candidate['signal_date'])
    if signal_index is None:
        return None

    buy_index = signal_index + int(params.get('buy_offset_days', 1))
    if buy_index >= len(frame):
        return None

    end_ts = pd.to_datetime(params['end_date'])
    end_matches = frame.index[frame['date'] <= end_ts]
    if len(end_matches) == 0:
        return None
    end_bound_index = int(end_matches[-1])
    if buy_index > end_bound_index:
        return None

    holding_days = max(1, int(params.get('holding_days', 5)))
    target_exit_index = min(end_bound_index, buy_index + holding_days)
    buy_row = frame.iloc[buy_index]
    buy_price = _pick_price(buy_row, params.get('buy_price', 'open'))
    if buy_price <= 0:
        return None

    legacy_take_profit_pct = _safe_float(params.get('take_profit_pct'), 0.0)
    stop_loss_pct = _safe_float(params.get('stop_loss_pct'), 0.0)
    sell_price_field = params.get('sell_price', 'close')
    fee_rate = _safe_float(params.get('fee_rate'), 0.0003)
    slippage_rate = _safe_float(params.get('slippage_rate'), 0.0005)
    profit_run_enabled = bool(params.get('profit_run_enabled', True))
    profit_trigger_pct = _safe_float(params.get('profit_trigger_pct'), 5.0)
    profit_step_pct = max(0.0, _safe_float(params.get('profit_step_pct'), 10.0))
    profit_sell_pct = max(0.0, min(100.0, _safe_float(params.get('profit_sell_pct'), 25.0)))
    no_gain_days = max(1, int(params.get('no_gain_days', 3)))
    short_break_days = max(1, int(params.get('short_trend_break_days', 2)))
    short_drawdown_pct = _safe_float(params.get('short_trend_drawdown_pct'), 5.0)

    remaining = 1.0
    exits: list[dict] = []
    runner_triggered = False
    next_profit_ladder_pct = profit_trigger_pct + profit_step_pct
    short_break_streak = 0

    for index in range(buy_index + 1, target_exit_index + 1):
        row = frame.iloc[index]
        low_price = _safe_float(row.get('low'), 0.0)
        high_price = _safe_float(row.get('high'), 0.0)
        close_price = _safe_float(row.get('close'), 0.0)
        short_line = _safe_float(row.get('short_term_trend'), 0.0)
        bull_bear_line = _safe_float(row.get('bull_bear_line'), 0.0)

        if short_line > 0 and close_price < short_line:
            short_break_streak += 1
        else:
            short_break_streak = 0

        if stop_loss_pct > 0 and low_price <= buy_price * (1 - stop_loss_pct / 100):
            remaining = _append_exit(
                exits, row, buy_price * (1 - stop_loss_pct / 100), remaining,
                'fixed_stop_loss', remaining, fee_rate, slippage_rate,
            )
            break

        if bool(params.get('enable_no_gain_exit', True)) and index - buy_index >= no_gain_days and close_price <= buy_price:
            remaining = _append_exit(exits, row, close_price, remaining, 'no_gain_exit', remaining, fee_rate, slippage_rate)
            break

        if bool(params.get('exit_on_bull_bear_break', True)) and bull_bear_line > 0 and close_price < bull_bear_line:
            remaining = _append_exit(exits, row, close_price, remaining, 'bull_bear_break', remaining, fee_rate, slippage_rate)
            break

        if bool(params.get('exit_on_short_trend_drawdown', True)) and short_line > 0 and close_price <= short_line * (1 - short_drawdown_pct / 100):
            remaining = _append_exit(exits, row, close_price, remaining, 'short_trend_drawdown', remaining, fee_rate, slippage_rate)
            break

        if bool(params.get('exit_on_short_trend_break', True)) and short_break_streak >= short_break_days:
            remaining = _append_exit(exits, row, close_price, remaining, 'short_trend_break_days', remaining, fee_rate, slippage_rate)
            break

        current_high_pct = (high_price / buy_price - 1) * 100 if buy_price > 0 else 0.0
        if profit_run_enabled and profit_trigger_pct > 0 and current_high_pct >= profit_trigger_pct:
            runner_triggered = True

        if runner_triggered and profit_step_pct > 0 and profit_sell_pct > 0:
            while remaining > 0 and current_high_pct >= next_profit_ladder_pct:
                exit_price = buy_price * (1 + next_profit_ladder_pct / 100)
                remaining = _append_exit(
                    exits, row, exit_price, min(remaining, profit_sell_pct / 100),
                    f'profit_ladder_{next_profit_ladder_pct:.1f}pct', remaining, fee_rate, slippage_rate,
                )
                next_profit_ladder_pct += profit_step_pct

        if runner_triggered and bool(params.get('hold_above_short_trend_after_trigger', True)) and short_line > 0 and close_price < short_line:
            remaining = _append_exit(exits, row, close_price, remaining, 'profit_runner_short_trend_break', remaining, fee_rate, slippage_rate)
            break

        if not profit_run_enabled and legacy_take_profit_pct > 0 and high_price >= buy_price * (1 + legacy_take_profit_pct / 100):
            remaining = _append_exit(
                exits, row, buy_price * (1 + legacy_take_profit_pct / 100), remaining,
                'take_profit', remaining, fee_rate, slippage_rate,
            )
            break

    if remaining > 0:
        final_row = frame.iloc[target_exit_index]
        final_price = _pick_price(final_row, sell_price_field)
        remaining = _append_exit(exits, final_row, final_price, remaining, 'holding_days', remaining, fee_rate, slippage_rate)

    if not exits:
        return None

    gross_return = sum((exit_item['price'] / buy_price - 1) * (exit_item['portion_pct'] / 100) for exit_item in exits)
    total_sell_cost = sum((exit_item['portion_pct'] / 100) * (fee_rate + slippage_rate) for exit_item in exits)
    net_return = gross_return - (fee_rate + slippage_rate) - total_sell_cost
    sell_date = exits[-1]['date']
    sell_price = exits[-1]['price']
    sell_index = int(frame.index[frame['date'] == pd.to_datetime(sell_date)][-1])
    hold_days = max(1, sell_index - buy_index)

    return {
        'code': candidate['code'],
        'name': candidate.get('name', ''),
        'strategy_name': candidate.get('strategy_name', ''),
        'source': candidate.get('source', ''),
        'signal_date': candidate.get('signal_date'),
        'trade_date': candidate.get('trade_date'),
        'buy_date': buy_row['date'].strftime('%Y-%m-%d'),
        'sell_date': sell_date,
        'buy_price': round(buy_price, 3),
        'sell_price': round(sell_price, 3),
        'hold_days': hold_days,
        'gross_return_pct': round(gross_return * 100, 2),
        'return_pct': round(net_return * 100, 2),
        'exit_reason': exits[-1]['reason'],
        'exits': exits,
    }


def _build_equity_curve(trades: list[dict]) -> tuple[list[dict], float, float]:
    if not trades:
        return [], 0.0, 0.0
    grouped: dict[str, list[dict]] = defaultdict(list)
    for trade in trades:
        grouped[trade['sell_date']].append(trade)

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    curve = []
    for sell_date in sorted(grouped):
        daily_return = sum(trade['return_pct'] / 100 for trade in grouped[sell_date]) / len(grouped[sell_date])
        equity *= (1 + daily_return)
        peak = max(peak, equity)
        drawdown = (equity / peak - 1) * 100 if peak > 0 else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        curve.append({
            'date': sell_date,
            'daily_return_pct': round(daily_return * 100, 2),
            'equity': round(equity, 4),
            'drawdown_pct': round(drawdown, 2),
        })
    return curve, (equity - 1) * 100, max_drawdown


def run_backtest(params: dict) -> dict:
    candidates = _fetch_candidates(params)
    candidates = _cap_positions_per_day(candidates, int(params.get('max_positions_per_day', 10)))
    trades = []
    skipped = 0
    for candidate in candidates:
        trade = _simulate_trade(candidate, params)
        if trade:
            trades.append(trade)
        else:
            skipped += 1

    trades.sort(key=lambda item: (item['buy_date'], item['code']))
    equity_curve, cumulative_return, max_drawdown = _build_equity_curve(trades)
    win_count = sum(1 for trade in trades if trade['return_pct'] > 0)
    trade_count = len(trades)
    avg_return = sum(trade['return_pct'] for trade in trades) / trade_count if trade_count else 0.0
    avg_hold_days = sum(trade['hold_days'] for trade in trades) / trade_count if trade_count else 0.0

    return {
        'params': params,
        'summary': {
            'candidate_count': len(candidates),
            'trade_count': trade_count,
            'skipped_count': skipped,
            'win_rate_pct': round((win_count / trade_count * 100) if trade_count else 0.0, 2),
            'avg_return_pct': round(avg_return, 2),
            'cumulative_return_pct': round(cumulative_return, 2),
            'max_drawdown_pct': round(max_drawdown, 2),
            'avg_hold_days': round(avg_hold_days, 1),
            'best_return_pct': round(max((trade['return_pct'] for trade in trades), default=0.0), 2),
            'worst_return_pct': round(min((trade['return_pct'] for trade in trades), default=0.0), 2),
        },
        'trades': trades,
        'equity_curve': equity_curve,
    }
