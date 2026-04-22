"""
新增策略模板。

使用方式：
1. 复制本文件为 strategy/你的策略文件.py。
2. 将类名和策略名称改为真实名称。
3. 在 calculate_indicators() 中补齐指标计算。
4. 在 select_stocks() 中写入选股条件，并保持返回结构兼容现有 CLI / Web / 导出链路。
5. 如需调参，在 config/strategy_params.yaml 中增加同名配置。

注意：
- 本文件以下划线开头，StrategyRegistry.auto_register_from_directory() 会跳过它，
  因此它不会被当成真实策略自动注册。
- 新策略必须继承 BaseStrategy，才能接入现有 run / backtrace / web 相关流程。
"""

from copy import deepcopy

import pandas as pd

from strategy.base_strategy import BaseStrategy


class NewStrategyTemplate(BaseStrategy):
    """可复制的选股策略骨架。"""

    DEFAULT_PARAMS = {
        'min_history_bars': 60,
        'lookback_days': 20,
        'volume_ratio_threshold': 1.5,
        'price_change_threshold': 3.0,
    }
    SIGNAL_CATEGORY = 'custom_strategy'

    def __init__(self, params=None):
        merged_params = deepcopy(self.DEFAULT_PARAMS)
        if params:
            merged_params.update(params)
        super().__init__('新增策略模板', merged_params)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """在这里统一准备策略所需指标。"""
        if df is None or df.empty:
            return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

        result = df.loc[:, ~df.columns.duplicated()].copy()
        if 'date' in result.columns:
            result['date'] = pd.to_datetime(result['date'], errors='coerce')
            result = result.sort_values('date', ascending=False).reset_index(drop=True)

        for column in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']:
            if column in result.columns:
                result[column] = pd.to_numeric(result[column], errors='coerce')

        if 'close' in result.columns:
            result['pct_change'] = result['close'].pct_change(-1) * 100
        else:
            result['pct_change'] = 0.0

        if 'volume' in result.columns:
            prev_volume = result['volume'].shift(-1).replace(0, pd.NA)
            result['volume_ratio'] = result['volume'] / prev_volume
        else:
            result['volume_ratio'] = pd.NA

        result['template_signal'] = False
        result['template_score'] = 0.0

        return result

    def select_stocks(self, df: pd.DataFrame, stock_name='') -> list:
        """在这里基于最新一根K线编写选股逻辑。"""
        if df is None or df.empty:
            return []

        if stock_name and self._is_invalid_stock_name(stock_name):
            return []

        prepared = self.calculate_indicators(df)
        min_history_bars = int(self.params.get('min_history_bars', 60))
        if prepared.empty or len(prepared) < min_history_bars:
            return []

        latest = prepared.iloc[0]

        signal_triggered = bool(latest.get('template_signal', False))
        if not signal_triggered:
            return []

        reasons = [
            'TODO: 替换为实际策略触发理由',
            f"volume_ratio={self._safe_float(latest.get('volume_ratio')):.2f}",
            f"pct_change={self._safe_float(latest.get('pct_change')):.2f}%",
        ]

        return [{
            'date': self._format_date(latest.get('date')),
            'close': round(self._safe_float(latest.get('close')), 2),
            'volume_ratio': round(self._safe_float(latest.get('volume_ratio')), 2),
            'score': round(self._safe_float(latest.get('template_score')), 2),
            'reasons': reasons,
            'category': self.SIGNAL_CATEGORY,
        }]

    @staticmethod
    def _is_invalid_stock_name(stock_name: str) -> bool:
        invalid_keywords = ['退', '未知', '退市', '已退']
        if any(keyword in stock_name for keyword in invalid_keywords):
            return True
        return stock_name.startswith('ST') or stock_name.startswith('*ST')

    @staticmethod
    def _safe_float(value, default=0.0) -> float:
        if pd.isna(value):
            return float(default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _format_date(value) -> str:
        if isinstance(value, pd.Timestamp):
            return value.strftime('%Y-%m-%d')
        if value is None or pd.isna(value):
            return ''
        return str(value)