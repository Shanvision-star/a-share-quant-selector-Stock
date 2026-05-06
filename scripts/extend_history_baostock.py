"""
全量扩展历史脚本 — 用 Baostock 把所有股票扩展到 N 年完整历史

主链路已切换至 Baostock（utils/akshare_fetcher.py:fetch_stock_history），
本脚本只需扫描 data/ 下所有 CSV，按需筛选短历史股，调用主链路即可。

特性：
  - 自动扫描全部本地股票 CSV
  - 可选过滤：只补行数 < threshold 的股票
  - 复用 backfill_history.py 的断点续传/失败重试结构
  - Baostock 单进程登录有限频，并发数保守（默认 4 线程）

用法：
    # 1) 先 dry-run 预览
    python scripts/extend_history_baostock.py --dry-run

    # 2) 全量扩展到 8 年（默认 4 线程）
    python scripts/extend_history_baostock.py --years 8

    # 3) 只补行数小于 1500 的（默认）
    python scripts/extend_history_baostock.py --years 8 --min-rows 1500

    # 4) 强制重跑全部
    python scripts/extend_history_baostock.py --years 8 --min-rows 0 --reset-progress
"""
import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"
EXTEND_CANDIDATES = DATA_DIR / "extend_candidates.txt"
EXTEND_PROGRESS = DATA_DIR / "extend_progress.txt"
EXTEND_FAILED = DATA_DIR / "extend_failed.txt"


def scan_all_stocks(data_dir: Path) -> list[tuple[str, int]]:
    """扫描 data/ 下所有股票 CSV，返回 [(code, rows), ...]"""
    results = []
    for sub in data_dir.iterdir():
        if not sub.is_dir() or len(sub.name) != 2:
            continue
        for csv_path in sub.glob("*.csv"):
            code = csv_path.stem
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    rows = sum(1 for _ in f) - 1
                results.append((code, max(0, rows)))
            except Exception:
                continue
    return results


def main():
    parser = argparse.ArgumentParser(description="全量扩展历史（Baostock）")
    parser.add_argument("--years", type=int, default=8, help="目标年限")
    parser.add_argument("--min-rows", type=int, default=1500,
                        help="只处理行数小于该值的股票（0=全部强制重跑）")
    parser.add_argument("--workers", type=int, default=4,
                        help="并发线程数（Baostock 限频，建议 4）")
    parser.add_argument("--jitter-min", type=float, default=0.1)
    parser.add_argument("--jitter-max", type=float, default=0.4)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset-progress", action="store_true")
    args = parser.parse_args()

    print(f"[扫描] {DATA_DIR}")
    all_stocks = scan_all_stocks(DATA_DIR)
    print(f"[扫描] 共发现 {len(all_stocks)} 只股票")

    if args.min_rows > 0:
        candidates = [c for c, r in all_stocks if r < args.min_rows]
        print(f"[筛选] 行数 < {args.min_rows} 的: {len(candidates)} 只")
    else:
        candidates = [c for c, _ in all_stocks]
        print(f"[筛选] 全量重跑: {len(candidates)} 只")

    candidates.sort()
    EXTEND_CANDIDATES.write_text(
        f"# extend_history_baostock 候选清单 - {datetime.now().isoformat()}\n"
        f"# years={args.years}, min-rows={args.min_rows}\n"
        + "\n".join(candidates) + "\n",
        encoding="utf-8"
    )
    print(f"[输出] 候选清单已写入: {EXTEND_CANDIDATES}")

    if not candidates:
        print("[完成] 没有需要处理的股票")
        return 0

    # 调用 backfill_history.main 逻辑（复用其断点续传/并发结构）
    # 这里直接以 subprocess 调用方式把控制权交给 backfill_history.py
    import subprocess
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "backfill_history.py"),
        "--candidates", str(EXTEND_CANDIDATES),
        "--workers", str(args.workers),
        "--years", str(args.years),
        "--jitter-min", str(args.jitter_min),
        "--jitter-max", str(args.jitter_max),
    ]
    if args.dry_run:
        cmd.append("--dry-run")
    # extend 操作语义上独立于 backfill，默认重置进度文件，避免误跳过
    if args.reset_progress or not args.dry_run:
        cmd.append("--reset-progress")

    print(f"[执行] {' '.join(cmd)}\n")
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
