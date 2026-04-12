#!/usr/bin/env python3
"""生成 Web 页面使用的策略缓存结果文件。"""
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from web.backend.services.strategy_service import build_strategy_result_snapshot, WEB_STRATEGY_RESULTS_FILE


def main() -> int:
    snapshot = build_strategy_result_snapshot()
    print(f"策略缓存已生成: {WEB_STRATEGY_RESULTS_FILE}")
    print(f"交易日: {snapshot.get('trade_date')}")
    print(f"生成时间: {snapshot.get('generated_at')}")
    print(f"总命中数: {snapshot.get('total')}")
    for strategy_filter, group in snapshot.get('groups', {}).items():
        print(f"  - {strategy_filter}: {group.get('total', 0)}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())