# -*- coding: utf-8 -*-
"""
回溯判断模块

根据股票代码与日期，回溯当日匹配到的策略列表。
依赖全局 StrategyRegistry，复用 BaseStrategy 的 analyze_stock 链路，
保证与 main.py run / web 路径完全一致的判定口径。
"""

import json
import logging
from pathlib import Path

from utils.csv_manager import CSVManager
from strategy.strategy_registry import get_registry

logger = logging.getLogger(__name__)


class BacktraceAnalyzer:
    """回溯分析器：在指定日期上对所有已注册策略做一次离线判定。"""

    def __init__(self, data_dir):
        """
        :param data_dir: CSV 数据目录
        """
        self.data_dir = data_dir
        self.csv_manager = CSVManager(data_dir)
        # 使用全局注册器，保证与 CLI/Web 一致
        self.strategy_registry = get_registry()
        # 若注册器尚未自动注册（首次进程启动时），主动触发
        if not self.strategy_registry.list_strategies():
            self.strategy_registry.auto_register_from_directory("strategy")

    def backtrace(self, stock_code, date):
        """
        根据股票代码和目标日期回溯匹配的策略。

        :param stock_code: 股票代码
        :param date: 日期，格式 'YYYY-MM-DD'
        :return: List[dict]，元素结构: {strategy, signals}
        """
        try:
            stock_data = self.csv_manager.read_stock(stock_code)
        except FileNotFoundError:
            logger.warning("股票数据文件未找到: %s", stock_code)
            return []
        except Exception as exc:
            logger.exception("读取股票 %s 数据失败: %s", stock_code, exc)
            return []

        if stock_data is None or stock_data.empty:
            logger.warning("股票 %s 数据为空", stock_code)
            return []

        if 'date' not in stock_data.columns:
            logger.warning("股票 %s 数据缺少 date 列", stock_code)
            return []

        # 兼容 datetime / 字符串两种 date 列
        date_series = stock_data['date'].astype(str)
        if date not in date_series.values:
            logger.info("股票 %s 在 %s 没有K线数据", stock_code, date)
            return []

        # 截取截至目标日的子集，BaseStrategy 需要至少 60 根K线
        df_until_date = stock_data[date_series <= date].copy()
        if len(df_until_date) < 60:
            logger.info(
                "股票 %s 截至 %s 仅 %d 根K线，不足 60 根",
                stock_code, date, len(df_until_date),
            )
            return []

        stock_name = self._resolve_stock_name(stock_code)

        matched = []
        for strategy_name, strategy in self.strategy_registry.get_registered_strategies().items():
            try:
                result = strategy.analyze_stock(stock_code, stock_name, df_until_date)
            except Exception as exc:
                logger.exception(
                    "策略 %s 在 %s/%s 上分析失败: %s",
                    strategy_name, stock_code, date, exc,
                )
                continue
            if result:
                matched.append({
                    'strategy': strategy_name,
                    'signals': result.get('signals', []),
                })

        return matched

    def _resolve_stock_name(self, stock_code):
        """从 data/stock_names.json 解析股票名称，找不到时回退占位。"""
        names_file = Path(self.data_dir) / 'stock_names.json'
        if names_file.exists():
            try:
                with open(names_file, 'r', encoding='utf-8') as f:
                    names = json.load(f)
                if isinstance(names, dict) and stock_code in names:
                    return names[stock_code]
            except Exception as exc:
                logger.warning("读取 stock_names.json 失败: %s", exc)
        return f"股票{stock_code}"


# 简单 smoke test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    analyzer = BacktraceAnalyzer("data")
    results = analyzer.backtrace("000001", "2026-04-01")
    print(f"匹配的策略: {results}")
