"""
碗口反弹策略 - 通达信公式 Python 实现

指标定义：
1. 知行短期趋势线 = EMA(EMA(CLOSE,10),10)
   - 对收盘价先做一次10日EMA，再做一次10日EMA

2. 知行多空线 = (MA(CLOSE,5) + MA(CLOSE,10) + MA(CLOSE,20) + MA(CLOSE,30)) / 4
   - 5日、10日、20日、30日均线平均值

选股条件：
3. 趋势线在上 = 知行短期趋势线 > 知行多空线
   - 短期趋势在多空线上方，表示上升趋势

4. 异动放量阳线 = V>=REF(V,1)*N AND C>O AND 总市值>CAP
   - 成交量是前一天的N倍以上 AND 阳线 AND 总市值达标

5. 异动 = EXIST(关键K线, M)
   - 在M天内存在关键K线

6. KDJ计算(9,3,3): RSV->K->D->J
   - J = 3*K - 2*D

7. J值低位 = J <= J_VAL

8. 分类标记（满足条件的按优先级标记）：
   - 回落碗中：价格位于知行短期趋势线和知行多空线之间（优先级最高）
   - 靠近多空线：价格距离知行多空线 ±duokong_pct% 范围内
   - 靠近短期趋势线：价格距离知行短期趋势线 ±short_pct% 范围内

9. 选股信号 = 异动 AND 趋势线在上 AND J值低位 AND (回落碗中 OR 靠近多空线 OR 靠近短期趋势线)
"""
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy
from utils.technical import (
    MA, EMA, LLV, HHV, REF, EXIST,
    KDJ, calculate_zhixing_state
)


class BowlReboundStrategy(BaseStrategy):
    """碗口反弹策略 - 分类标记版"""
    
    def __init__(self, params=None):
        # 默认参数
        default_params = {
            'N': 4,              # 成交量倍数
            'M': 15,             # 回溯天数
            'CAP': 4000000000,   # 总市值>40亿
            'J_VAL': 30,         # J值上限
            'duokong_pct': 3,    # 距离多空线百分比(默认3%)
            'short_pct': 2,      # 距离短期趋势线百分比(默认2%)
            'M1': 14,            # MA周期1 (多空线)
            'M2': 28,            # MA周期2 (多空线)
            'M3': 57,            # MA周期3 (多空线)
            'M4': 114            # MA周期4 (多空线)
        }
        
        # 合并用户参数
        if params:
            default_params.update(params)
        
        super().__init__("碗口反弹策略", default_params)
    
    def calculate_indicators(self, df) -> pd.DataFrame:
        """
        计算碗口反弹策略所需的所有指标
        """
        result = df.copy()
        result = result.loc[:, ~result.columns.duplicated()].copy()

        # 1. 统一计算知行双线和位置状态，避免策略与B1定义分叉
        zhixing_df = calculate_zhixing_state(
            result, 
            m1=self.params['M1'],
            m2=self.params['M2'],
            m3=self.params['M3'],
            m4=self.params['M4'],
            duokong_pct=self.params['duokong_pct'],
            short_pct=self.params['short_pct']
        )
        for column in zhixing_df.columns:
            result[column] = zhixing_df[column]
        
        # 4. KDJ指标
        from utils.technical import KDJ
        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        result['K'] = kdj_df['K']
        result['D'] = kdj_df['D']
        result['J'] = kdj_df['J']
        
        # 5. 放量阳线条件
        # 成交量 >= 前一日 * N
        from utils.technical import REF
        result['vol_ratio'] = result['volume'] / REF(result['volume'], 1)
        result['vol_surge'] = result['vol_ratio'] >= self.params['N']
        
        # 阳线：收盘价 > 开盘价
        result['positive_candle'] = result['close'] > result['open']
        
        # 总市值达标（选股阶段禁止逐股实时请求，否则会把本地选股变成网络瓶颈）
        result['market_cap_ok'] = self._check_market_cap(result)
        
        # 关键K线 = 放量 AND 阳线 AND 市值达标
        result['key_candle'] = (
            result['vol_surge'] & 
            result['positive_candle'] & 
            result['market_cap_ok']
        )
        
        # 6. 异动 = EXIST(关键K线, M)
        from utils.technical import EXIST
        result['abnormal'] = EXIST(result['key_candle'], self.params['M'])
        
        # 7. J值低位
        result['j_low'] = result['J'] <= self.params['J_VAL']
        
        return result
    
    def _check_market_cap(self, df) -> pd.Series:
        """
        检查总市值是否达标。

        选股阶段只使用本地数据，避免逐股实时请求导致整体阻塞。
        优先使用 market_cap 列；若缺失，则退化为不过滤，保证流程稳定与速度。
        """
        if df.empty:
            return pd.Series(dtype=bool)

        if 'market_cap' in df.columns:
            market_cap = pd.to_numeric(df['market_cap'], errors='coerce')
            valid_market_cap = market_cap.dropna()
            if not valid_market_cap.empty:
                sample_cap = valid_market_cap.iloc[-1]
                if sample_cap > 1e8:
                    return market_cap > self.params['CAP']

        return pd.Series([True] * len(df), index=df.index)
    
    def select_stocks(self, df, stock_name='') -> list:
        """
        选股逻辑 - 基于最新一天的数据进行筛选
        选股后按类型分类标记（优先级：回落碗中 > 靠近多空线 > 靠近短期趋势线）
        """
        if df.empty:
            return []
        
        # 过滤退市/异常股票
        if stock_name:
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in stock_name for kw in invalid_keywords):
                return []
            
            # 过滤 ST/*ST 股票
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []
        
        # 获取最新一天的数据
        latest = df.iloc[0]
        latest_date = latest['date']
        
        # 检查最新一天是否有有效交易
        if latest['volume'] <= 0 or pd.isna(latest['close']):
            return []
        
        # 过滤数据异常的股票
        recent_df = df.head(30)
        if recent_df['J'].abs().mean() > 80:
            return []
        
        # ========== 核心条件检查 ==========
        
        # 1. 上升趋势
        if not latest['trend_above']:
            return []
        
        # 2. J值条件
        if not latest['j_low']:
            return []
        
        # 3. 异动条件：在M天内存在放量阳线
        lookback_df = df.head(self.params['M'])

        # 剔除：如果回顾期内最大成交量的一天是阴线（最大量是阴量）
        max_volume_idx = lookback_df['volume'].idxmax()
        max_volume_row = lookback_df.loc[max_volume_idx]
        if max_volume_row['close'] < max_volume_row['open']:
            # 最大成交量那天是阴线，剔除
            return []

        key_candles = lookback_df[
            (lookback_df['key_candle'] == True) &
            (lookback_df['close'] > lookback_df['open'])
        ]

        if key_candles.empty:
            return []
        
        # ========== 分类标记（按优先级） ==========
        
        reasons = []
        category = None
        
        # 优先级1：回落碗中（价格位于多空线和短期趋势线之间）
        if latest['fall_in_bowl']:
            reasons.append('回落碗中')
            category = 'bowl_center'
        # 优先级2：靠近多空线
        elif latest['near_duokong']:
            reasons.append(f'靠近多空线(±{self.params["duokong_pct"]}%)')
            category = 'near_duokong'
        # 优先级3：靠近短期趋势线
        elif latest['near_short_trend']:
            reasons.append(f'靠近短期趋势线(±{self.params["short_pct"]}%)')
            category = 'near_short_trend'
        else:
            # 不满足任何位置条件
            return []
        
        # ========== 构建选股信号 ==========
        
        latest_key = key_candles.iloc[0]
        
        signal_info = {
            'date': latest_date,
            'close': round(latest['close'], 2),
            'J': round(latest['J'], 2),
            'volume_ratio': round(latest['vol_ratio'], 2) if not pd.isna(latest['vol_ratio']) else 1.0,
            'market_cap': round(latest['market_cap'] / 1e8, 2),
            'short_term_trend': round(latest['short_term_trend'], 2),
            'bull_bear_line': round(latest['bull_bear_line'], 2),
            'reasons': reasons,
            'category': category,  # 分类标记
            'key_candle_date': latest_key['date'],
        }
        
        return [signal_info]
