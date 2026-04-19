# -*- coding: utf-8 -*-
"""
回溯判断模块

此模块用于根据输入的股票代码和日期，回溯匹配的策略。
"""

from datetime import datetime
from utils.csv_manager import CSVManager
from strategy.strategy_registry import StrategyRegistry

class BacktraceAnalyzer:
    """
    回溯分析器类，用于回溯匹配策略。
    """

    def __init__(self, data_dir):
        """
        初始化回溯分析器。

        :param data_dir: 数据文件所在目录
        """
        self.data_dir = data_dir
        self.csv_manager = CSVManager(data_dir)
        self.strategy_registry = StrategyRegistry()

    def backtrace(self, stock_code, date):
        """
        根据股票代码和日期回溯匹配的策略。

        :param stock_code: 股票代码
        :param date: 日期，格式为 'YYYY-MM-DD'
        :return: 匹配的策略列表
        """
        try:
            # 加载股票数据
            stock_data = self.csv_manager.read_stock(stock_code)

            # 检查日期是否存在
            if date not in stock_data['date'].values:
                return []

            # 获取目标日期的数据
            target_row = stock_data[stock_data['date'] == date].iloc[0]

            # 遍历所有策略，检查是否匹配
            matched_strategies = []
            for strategy_name, strategy_class in self.strategy_registry.get_all_strategies().items():
                strategy = strategy_class()
                if strategy.match(target_row):
                    matched_strategies.append(strategy_name)

            return matched_strategies

        except FileNotFoundError:
            print(f"股票数据文件未找到: {stock_code}")
            return []
        except Exception as e:
            print(f"回溯分析时发生错误: {e}")
            return []

# 示例用法
if __name__ == "__main__":
    data_directory = "data"
    analyzer = BacktraceAnalyzer(data_directory)
    stock = "000001"
    trace_date = "2026-04-01"
    results = analyzer.backtrace(stock, trace_date)
    print(f"匹配的策略: {results}")