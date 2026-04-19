#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
临时调试脚本：对单只股票和指定日期输出 B2 步骤诊断信息
用法: python utils/debug_b2_verbose.py <stock_code> <date>
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.csv_manager import CSVManager
from strategy.b2_strategy import B2CaseAnalyzer, _safe_float


def main():
    if len(sys.argv) < 3:
        print("Usage: python utils/debug_b2_verbose.py <stock_code> <YYYY-MM-DD>")
        return
    code = sys.argv[1]
    date = sys.argv[2]

    cm = CSVManager("data")
    try:
        df = cm.read_stock(code)
    except FileNotFoundError:
        print(f"No CSV for {code}")
        return

    if date not in df['date'].values:
        print(f"Date {date} not found in {code} data")
        return

    analyzer = B2CaseAnalyzer()

    # prepare same working_df as analyzer.analyze does
    df_asc = df.sort_values("date").reset_index(drop=True)
    if not pd.api.types.is_datetime64_any_dtype(df_asc["date"]):
        df_asc["date"] = pd.to_datetime(df_asc["date"])

    from utils.technical import KDJ, calculate_zhixing_state

    state_df = calculate_zhixing_state(df_asc)
    kdj_df = KDJ(df_asc)

    working_df = state_df.copy()
    working_df["K"] = kdj_df["K"].values
    working_df["D"] = kdj_df["D"].values
    working_df["J"] = kdj_df["J"].values
    working_df["date"] = df_asc["date"].values
    working_df["close"] = df_asc["close"].values
    working_df["volume"] = df_asc["volume"].values
    working_df["high"] = df_asc["high"].values if "high" in df_asc.columns else df_asc["close"].values
    working_df["low"] = df_asc["low"].values if "low" in df_asc.columns else df_asc["close"].values
    if "pct_chg" in df_asc.columns:
        working_df["pct_chg"] = df_asc["pct_chg"].values
    else:
        working_df["pct_chg"] = df_asc["close"].pct_change().fillna(0) * 100
    if "turnover" in df_asc.columns:
        working_df["turnover"] = df_asc["turnover"].values
    elif "turnover_rate" in df_asc.columns:
        working_df["turnover"] = df_asc["turnover_rate"].values
    else:
        working_df["turnover"] = float("nan")

    # find index of target date
    target_idx = working_df[working_df['date'] == pd.to_datetime(date)].index
    if len(target_idx) == 0:
        print(f"Target date {date} not found after processing")
        return
    target_idx = int(target_idx[0])

    print(f"Diagnostics for {code} on {date} (index {target_idx})")
    row = working_df.iloc[target_idx]
    print(f"Close={row['close']}, pct_chg={_safe_float(row.get('pct_chg')):.2f}%, volume={_safe_float(row.get('volume'))}")
    print(f"J={_safe_float(row.get('J')):.2f}")
    if target_idx > 0:
        prev = working_df.iloc[target_idx-1]
        print(f"Prev day {str(prev['date'])[:10]}: Close={prev['close']}, J={_safe_float(prev.get('J')):.2f}")

    # B1 precondition scan
    case_cfg = {"lookback_days": 40}
    b1 = analyzer._check_b1_precondition(working_df, case_cfg)
    if b1 is None:
        print("B1 precondition: NOT FOUND in lookback")
    else:
        print("B1 precondition: FOUND ->", b1)

    # If B1 found, show big up candles
    if b1 is not None:
        big_up = analyzer._check_big_up_candles(working_df, b1['idx'])
        print("Big up candles check:", big_up)
    else:
        print("Skipping big up candles (no B1)")

    # consolidation auto-identify (no start/end provided)
    cons = analyzer._identify_consolidation(working_df, None, None)
    print("Consolidation (auto):", cons)

    # detect B2 breakouts from latest B1 (if any)
    if b1 is not None and cons is not None:
        b2 = analyzer._detect_b2_breakout(working_df, b1['idx'], cons)
        print("Detected B2 breakout (first candidate after B1):", b2)
        if b2 is not None:
            print(f"Is target date the B2 candidate? -> {b2['date'] == date}")
    else:
        print("Skipping B2 detection (missing B1 or consolidation)")


if __name__ == '__main__':
    main()
