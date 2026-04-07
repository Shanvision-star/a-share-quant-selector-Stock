"""Verify 688031 vs 688663 and confirm correct stock names."""
import pandas as pd
import json

def load_stock(code, subdir):
    path = f"data/{subdir}/{code}.csv"
    df = pd.read_csv(path)
    cols = df.columns.tolist()
    date_col = cols[0]
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).sort_values(date_col).reset_index(drop=True)
    df.rename(columns={date_col: "date"}, inplace=True)
    if "close" not in df.columns:
        mapping = {cols[1]: "open", cols[2]: "close", cols[3]: "high", cols[4]: "low", cols[5]: "volume"}
        df.rename(columns=mapping, inplace=True)
    return df

def check_dates(code, dates, subdir):
    print(f"\n=== {code} ===")
    try:
        df = load_stock(code, subdir)
        print(f"  range: {df['date'].min().date()} ~ {df['date'].max().date()}  rows={len(df)}")
        for d in dates:
            mask = df["date"].dt.strftime("%Y-%m-%d") == d
            row = df[mask]
            if row.empty:
                target = pd.Timestamp(d)
                nearby = df[(df["date"] >= target - pd.Timedelta(days=5)) & (df["date"] <= target + pd.Timedelta(days=5))]
                nearby_dates = nearby["date"].dt.strftime("%Y-%m-%d").tolist()
                print(f"  {d}: NOT FOUND.  Nearby: {nearby_dates}")
                continue
            pos = row.index[0]
            close_v = float(row.iloc[0]["close"])
            vol_v = float(row.iloc[0]["volume"])
            pct = (close_v - float(df.iloc[pos-1]["close"])) / float(df.iloc[pos-1]["close"]) * 100 if pos > 0 else float("nan")
            mean10 = float(df.iloc[max(0, pos-10):pos]["volume"].mean()) if pos > 0 else float("nan")
            prev_vol = float(df.iloc[pos-1]["volume"]) if pos > 0 else float("nan")
            print(f"  {d}: close={close_v:.2f}  pct={pct:+.2f}%  vol/10dAvg={vol_v/mean10:.2f}x  vol/prev={vol_v/prev_vol:.2f}x")
    except Exception as e:
        print(f"  ERROR: {e}")

# -------- 名称核查 --------
print("===== 股票名称核验 (stock_names.json) =====")
try:
    names = json.load(open("data/stock_names.json", encoding="utf-8"))
    for code in ["688031", "688663"]:
        print(f"  {code}: {names.get(code, 'NOT FOUND')}")
except Exception as e:
    print(f"  ERROR: {e}")

# -------- Case 1: 星环科技正确代码 688031 --------
check_dates("688031", [
    "2025-10-28", "2025-12-04",
    "2025-12-09", "2025-12-10", "2025-12-11", "2025-12-12",
    "2025-12-15", "2025-12-16",
], "68")

print("\n[688663 对比（错误代码）]")
check_dates("688663", ["2025-10-28", "2025-12-04", "2025-12-15"], "68")
