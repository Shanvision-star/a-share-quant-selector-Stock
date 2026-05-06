"""
数据覆盖度诊断脚本

扫描 data/ 目录下所有股票 CSV，统计历史长度与日期范围分布，
识别"短历史股"（首次入库未做完整回填导致），输出补齐候选清单。

用法：
    python scripts/diagnose_data_coverage.py
    python scripts/diagnose_data_coverage.py --threshold 500 --out data/backfill_candidates.txt

输出：
    1. 终端报告：行数分布直方图 + 最早日期分布 + 异常股票统计
    2. 候选清单文件：所有 行数 < threshold 的股票代码，每行一个，供补齐脚本消费
"""
import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
SUBDIR_PREFIXES = ("00", "30", "60", "68")  # 深主板/创业板/沪主板/科创板


def scan_one(csv_path: Path) -> dict | None:
    """读取单个 CSV，返回基本统计；失败返回 None。"""
    try:
        if csv_path.stat().st_size == 0:
            return {"code": csv_path.stem, "rows": 0, "earliest": None, "latest": None, "empty": True}
        # 只读 date 列，速度快
        df = pd.read_csv(csv_path, usecols=["date"])
        if df.empty:
            return {"code": csv_path.stem, "rows": 0, "earliest": None, "latest": None, "empty": True}
        dates = pd.to_datetime(df["date"], errors="coerce").dropna()
        if dates.empty:
            return {"code": csv_path.stem, "rows": len(df), "earliest": None, "latest": None, "empty": False}
        return {
            "code": csv_path.stem,
            "rows": len(df),
            "earliest": dates.min(),
            "latest": dates.max(),
            "empty": False,
        }
    except Exception as e:
        return {"code": csv_path.stem, "rows": -1, "earliest": None, "latest": None, "empty": False, "error": str(e)}


def histogram(values, bins):
    """简单直方图统计。"""
    counter = Counter()
    for v in values:
        for label, lo, hi in bins:
            if lo <= v < hi:
                counter[label] += 1
                break
    return counter


def main():
    parser = argparse.ArgumentParser(description="A股日线数据覆盖度诊断")
    parser.add_argument("--threshold", type=int, default=500,
                        help="行数低于此值视为短历史股，需要补齐 (默认500)")
    parser.add_argument("--out", type=str, default=str(DATA_DIR / "backfill_candidates.txt"),
                        help="补齐候选清单输出路径")
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR))
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_path = Path(args.out)

    print(f"[扫描] 数据目录: {data_dir}")
    print(f"[配置] 短历史阈值: <{args.threshold} 行")
    print()

    all_records = []
    for prefix in SUBDIR_PREFIXES:
        sub = data_dir / prefix
        if not sub.exists():
            continue
        csvs = sorted(sub.glob("*.csv"))
        print(f"  扫描 {prefix}/ ... {len(csvs)} 个文件")
        for csv in csvs:
            rec = scan_one(csv)
            if rec is not None:
                rec["prefix"] = prefix
                all_records.append(rec)

    total = len(all_records)
    if total == 0:
        print("[错误] 未找到任何 CSV 文件")
        return 1

    print(f"\n[汇总] 共扫描 {total} 只股票")

    # 错误/空文件
    errors = [r for r in all_records if r.get("rows", 0) == -1]
    empties = [r for r in all_records if r.get("empty")]
    valid = [r for r in all_records if not r.get("empty") and r.get("rows", 0) > 0]
    print(f"  ├─ 解析失败:  {len(errors)}")
    print(f"  ├─ 空文件:    {len(empties)}")
    print(f"  └─ 有效文件:  {len(valid)}")

    if not valid:
        print("[错误] 没有任何有效数据")
        return 1

    # 行数分布
    print("\n[行数分布]")
    bins = [
        ("    0  ~   50", 0, 50),
        ("   50  ~  200", 50, 200),
        ("  200  ~  500", 200, 500),
        ("  500  ~ 1000", 500, 1000),
        (" 1000  ~ 2000", 1000, 2000),
        (" 2000  +     ", 2000, 10**9),
    ]
    rows_hist = histogram((r["rows"] for r in valid), bins)
    for label, _, _ in bins:
        cnt = rows_hist.get(label, 0)
        bar = "█" * min(60, cnt * 60 // max(total, 1))
        print(f"  {label}: {cnt:>5}  {bar}")

    # 最早日期分布（按年）
    print("\n[最早日期分布 - 越早覆盖越完整]")
    year_counter = Counter(r["earliest"].year for r in valid if r["earliest"] is not None)
    for year in sorted(year_counter):
        cnt = year_counter[year]
        bar = "█" * min(60, cnt * 60 // max(total, 1))
        print(f"  {year}: {cnt:>5}  {bar}")

    # 最新日期分布（识别更新滞后股）
    latest_dates = [r["latest"] for r in valid if r["latest"] is not None]
    if latest_dates:
        max_latest = max(latest_dates)
        stale = [r for r in valid if r["latest"] is not None and (max_latest - r["latest"]).days > 7]
        print(f"\n[更新状态] 全局最新日期: {max_latest.date()}")
        print(f"  更新滞后 >7 天的股票: {len(stale)}")

    # 短历史候选
    short = sorted(
        [r for r in valid if r["rows"] < args.threshold],
        key=lambda r: r["rows"],
    )
    print(f"\n[补齐候选] 行数 <{args.threshold} 的股票: {len(short)} 只 ({len(short)*100//total}%)")
    if short:
        print("  最严重的前 20 只:")
        for r in short[:20]:
            earliest = r["earliest"].date() if r["earliest"] is not None else "?"
            print(f"    {r['code']}  rows={r['rows']:>4}  earliest={earliest}")

    # 写候选清单
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# 数据补齐候选清单\n")
        f.write(f"# 生成时间: {datetime.now().isoformat()}\n")
        f.write(f"# 阈值: rows < {args.threshold}\n")
        f.write(f"# 总数: {len(short)}\n")
        for r in short:
            f.write(f"{r['code']}\n")
    print(f"\n[输出] 候选清单已写入: {out_path}")

    # 错误清单（如果有）
    if errors:
        err_path = out_path.with_name("scan_errors.txt")
        with open(err_path, "w", encoding="utf-8") as f:
            for r in errors:
                f.write(f"{r['code']}\t{r.get('error', '')}\n")
        print(f"[警告] 解析失败清单: {err_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
