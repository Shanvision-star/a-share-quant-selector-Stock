"""Verify B2 case library data against actual CSV files."""
import pandas as pd
import numpy as np

def load_stock(code, subdir):
    path = f"data/{subdir}/{code}.csv"
    df = pd.read_csv(path)
    cols = df.columns.tolist()
    date_col = cols[0]
    if not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    df.rename(columns={date_col: "date"}, inplace=True)
    # Map positional columns if named
    if "close" not in df.columns:
        # Standard order: date,open,close,high,low,volume,...
        mapping = {cols[1]: "open", cols[2]: "close", cols[3]: "high", cols[4]: "low", cols[5]: "volume"}
        df.rename(columns=mapping, inplace=True)
    return df

def check_dates(code, dates, subdir):
    print(f"\n=== {code} ===")
    try:
        df = load_stock(code, subdir)
        for d in dates:
            mask = df["date"].dt.strftime("%Y-%m-%d") == d
            row = df[mask]
            if row.empty:
                target = pd.Timestamp(d)
                nearby = df[(df["date"] >= target - pd.Timedelta(days=5)) & (df["date"] <= target + pd.Timedelta(days=5))]
                nearby_dates = nearby["date"].dt.strftime("%Y-%m-%d").tolist()
                print(f"  {d}: NOT FOUND. Nearby: {nearby_dates}")
                continue
            pos = row.index[0]
            close = float(row.iloc[0]["close"])
            vol = float(row.iloc[0]["volume"])
            if pos > 0:
                prev_close = float(df.iloc[pos - 1]["close"])
                pct = (close - prev_close) / prev_close * 100
            else:
                pct = float("nan")
            mean_vol_10 = float(df.iloc[max(0, pos - 10):pos]["volume"].mean()) if pos > 0 else float("nan")
            vol_ratio = vol / mean_vol_10 if mean_vol_10 > 0 else float("nan")
            prev_vol = float(df.iloc[pos - 1]["volume"]) if pos > 0 else float("nan")
            prev_vol_ratio = vol / prev_vol if prev_vol > 0 else float("nan")
            print(f"  {d}: close={close:.2f}  pct_chg={pct:+.2f}%  vol={int(vol)}  vol/10dAvg={vol_ratio:.2f}x  vol/prevDay={prev_vol_ratio:.2f}x")
    except Exception as e:
        import traceback
        print(f"  ERROR: {e}")
        traceback.print_exc()

# Case 1: 星环科技 688663
check_dates("688663", [
    "2025-10-28", "2025-12-04",
    "2025-12-09", "2025-12-10", "2025-12-11", "2025-12-12",
    "2025-12-14", "2025-12-15", "2025-12-16"
], "68")

# Case 2: 晶科科技 601778
check_dates("601778", ["2025-06-17", "2025-08-05", "2025-08-07", "2025-08-08"], "60")

# Case 3: 四会富仕 300852
check_dates("300852", ["2025-08-20", "2025-08-28", "2025-09-09", "2025-09-10", "2025-09-11"], "30")

# Case 4: 中坚科技 002779
check_dates("002779", [
    "2025-06-11", "2025-07-25",
    "2025-07-28", "2025-07-29", "2025-07-30", "2025-07-31", "2025-08-01",
], "00")

# Case 5: 百普赛斯 301080
check_dates("301080", ["2025-06-12", "2025-06-13", "2025-06-16", "2025-06-23", "2025-06-24"], "30")

# Case 6: 南亚新材 688519
check_dates("688519", ["2025-07-25", "2025-07-28", "2025-07-29", "2025-08-01", "2025-08-12", "2025-08-13"], "68")

# Case 7: 世运电路 603920
check_dates("603920", ["2025-07-25", "2025-07-28", "2025-07-29", "2025-08-08", "2025-08-11", "2025-08-12"], "60")
