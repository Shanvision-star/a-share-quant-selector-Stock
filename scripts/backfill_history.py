"""
数据补齐脚本 — 针对短历史股做完整回填

读取 data/backfill_candidates.txt 候选清单，对每只股票调用
AKShareFetcher.fetch_stock_history(years=N) 拉取完整历史，
然后写回 CSV（CSVManager.write_stock 会去重排序）。

特性：
  - 并发拉取（ThreadPoolExecutor）
  - 断点续传：进度文件记录已成功的代码，重跑时跳过
  - 失败清单单独输出，便于二次重试
  - 限频保护：每个线程在请求间随机 sleep
  - Dry-run 模式：仅打印计划，不实际拉取

用法：
    # 先 dry-run 预览
    python scripts/backfill_history.py --dry-run

    # 正式执行（默认 8 线程，6 年）
    python scripts/backfill_history.py

    # 自定义参数
    python scripts/backfill_history.py --workers 4 --years 6 --candidates data/backfill_candidates.txt

    # 仅重试上次失败的
    python scripts/backfill_history.py --candidates data/backfill_failed.txt
"""
import argparse
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from utils.akshare_fetcher import AKShareFetcher  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CANDIDATES = DATA_DIR / "backfill_candidates.txt"
PROGRESS_FILE = DATA_DIR / "backfill_progress.txt"
FAILED_FILE = DATA_DIR / "backfill_failed.txt"

_print_lock = threading.Lock()


def log(msg: str):
    """线程安全打印。"""
    with _print_lock:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_candidates(path: Path) -> list[str]:
    """从候选清单加载股票代码（忽略以 # 开头的注释行和空行）。"""
    codes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        codes.append(line)
    return codes


def load_progress() -> set[str]:
    """加载已成功完成的代码集合（断点续传）。"""
    if not PROGRESS_FILE.exists():
        return set()
    return {
        line.strip()
        for line in PROGRESS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def append_progress(code: str):
    """追加一条成功记录（线程安全）。"""
    with _print_lock:
        with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{code}\n")


def fetch_one(fetcher: AKShareFetcher, code: str, years: int, min_jitter: float, max_jitter: float) -> tuple[str, int, str]:
    """
    回填单只股票。
    返回 (code, rows_written, status)，status ∈ {'ok', 'empty', 'error:<msg>'}
    """
    try:
        time.sleep(random.uniform(min_jitter, max_jitter))
        df = fetcher.fetch_stock_history(code, years=years)
        if df is None or df.empty:
            return code, 0, "empty"
        fetcher.csv_manager.write_stock(code, df)
        return code, len(df), "ok"
    except Exception as e:
        return code, 0, f"error:{type(e).__name__}:{e}"


def main():
    parser = argparse.ArgumentParser(description="A股短历史股数据回填")
    parser.add_argument("--candidates", type=str, default=str(DEFAULT_CANDIDATES))
    parser.add_argument("--workers", type=int, default=8, help="并发线程数")
    parser.add_argument("--years", type=int, default=6, help="拉取的历史年限")
    parser.add_argument("--jitter-min", type=float, default=0.1, help="请求间最小抖动秒数")
    parser.add_argument("--jitter-max", type=float, default=0.5, help="请求间最大抖动秒数")
    parser.add_argument("--dry-run", action="store_true", help="只打印将处理的列表，不实际拉取")
    parser.add_argument("--reset-progress", action="store_true", help="忽略已有进度，重新跑全部")
    parser.add_argument("--data-dir", type=str, default=str(DATA_DIR))
    args = parser.parse_args()

    candidates_path = Path(args.candidates)
    if not candidates_path.exists():
        print(f"[错误] 候选清单不存在: {candidates_path}")
        return 1

    all_codes = load_candidates(candidates_path)
    if not all_codes:
        print(f"[错误] 候选清单为空: {candidates_path}")
        return 1

    if args.reset_progress and PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        log("已重置进度文件")

    done = load_progress()
    pending = [c for c in all_codes if c not in done]

    print(f"[配置] 候选清单: {candidates_path}")
    print(f"[配置] 总数: {len(all_codes)}  已完成: {len(done)}  待处理: {len(pending)}")
    print(f"[配置] 并发: {args.workers} 线程  拉取年限: {args.years} 年")
    print(f"[配置] 请求抖动: {args.jitter_min}~{args.jitter_max} 秒")

    if args.dry_run:
        print("\n[DRY-RUN] 将处理以下股票（前 30 条）:")
        for code in pending[:30]:
            print(f"  {code}")
        if len(pending) > 30:
            print(f"  ... 还有 {len(pending) - 30} 只")
        return 0

    if not pending:
        log("没有待处理的股票，全部已完成")
        return 0

    # 初始化 fetcher（单例供所有线程共享）
    log("初始化 AKShareFetcher ...")
    fetcher = AKShareFetcher(data_dir=args.data_dir)

    # 清空失败清单（每轮重跑都重新统计）
    if FAILED_FILE.exists():
        FAILED_FILE.unlink()

    success = 0
    empty = 0
    failed = []
    started_at = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_one, fetcher, code, args.years, args.jitter_min, args.jitter_max): code
            for code in pending
        }
        total = len(futures)
        for i, fut in enumerate(as_completed(futures), 1):
            code = futures[fut]
            try:
                _, rows, status = fut.result()
            except Exception as e:
                failed.append((code, f"future-error:{e}"))
                log(f"[{i}/{total}] {code}  [FAIL] future异常: {e}")
                continue

            if status == "ok":
                append_progress(code)
                success += 1
                log(f"[{i}/{total}] {code}  [OK] {rows} 行")
            elif status == "empty":
                empty += 1
                failed.append((code, "empty"))
                log(f"[{i}/{total}] {code}  [WARN] 空数据")
            else:
                failed.append((code, status))
                log(f"[{i}/{total}] {code}  [FAIL] {status}")

    elapsed = time.time() - started_at
    print()
    print(f"[完成] 用时 {elapsed:.1f}s")
    print(f"  ├─ 成功: {success}")
    print(f"  ├─ 空数据: {empty}")
    print(f"  └─ 失败: {len(failed) - empty}")

    if failed:
        with open(FAILED_FILE, "w", encoding="utf-8") as f:
            f.write(f"# 回填失败清单 - {datetime.now().isoformat()}\n")
            for code, reason in failed:
                f.write(f"{code}\t{reason}\n")
        # 同时输出一个纯代码文件，方便重跑
        plain_failed = FAILED_FILE.with_suffix(".codes.txt")
        with open(plain_failed, "w", encoding="utf-8") as f:
            for code, _ in failed:
                f.write(f"{code}\n")
        print(f"\n失败明细: {FAILED_FILE}")
        print(f"失败代码（可作为下一轮 --candidates）: {plain_failed}")

    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
