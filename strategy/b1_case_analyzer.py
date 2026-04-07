"""
B1阶段型策略 / 案例分析兼容模块

本模块当前以 B1CaseStrategy 作为主实现，同时保留 B1CaseAnalyzer 兼容别名。
职责包括：
1. 作为独立分析器，服务于 B1 案例库、回溯验证、前瞻预警扫描。
2. 作为标准策略类，接入 main.py run 默认执行链路，与 BowlReboundStrategy 并行运行。

策略核心思想：
    - 先寻找低位 KDJ 触发日（anchor）
    - 再确认护盘、拉升、洗盘不破位
    - 最后识别当前是否处于再次回踩知行多空线的 setup 窗口
    - 如果阶段 1-5 均满足，则提前给出“待大阳确认”的阶段型 B1 预警
"""
from __future__ import annotations

from copy import deepcopy

import pandas as pd

from strategy.base_strategy import BaseStrategy
from utils.technical import KDJ, calculate_zhixing_state


ZHANGYUE_B1_ANALYSIS_CONFIG = {
    'anchor_date': '2025-11-17',
    'reference_low_date': '2025-10-17',
    'breakout_date': '2025-11-21',
    'washout_end_date': '2025-12-17',
    'revisit_date': '2026-02-06',
    'setup_window_days': 2,
    'buy_date': '2026-02-09',
    'anchor_kdj_field': 'J',
    'anchor_kdj_max': 20,
    'no_break_days': 3,
    'guard_reference_field': 'open',
    'guard_compare_field': 'low',
    'breakout_min_pct': 4.0,
    'breakout_min_streak': 3,
    'washout_compare_field': 'close',
    'revisit_line_field': 'bull_bear_line',
    'revisit_band_pct': 3.0,
    'revisit_kdj_field': 'J',
    'revisit_kdj_max': 20.0,
    'buy_compare_field': 'close',
    'buy_trigger_min_pct': 9.5,
    'buy_breakout_lookback_days': 5,
    'short_pct': 2.0,
    'duokong_pct': 3.0,
    'M1': 14,
    'M2': 28,
    'M3': 57,
    'M4': 114,
}


class B1CaseStrategy(BaseStrategy):
    """既可独立分析，也可直接参与默认选股执行链路的 B1 阶段型策略。"""

    DEFAULT_CONFIG = ZHANGYUE_B1_ANALYSIS_CONFIG
    SIGNAL_CATEGORY = 'stage_b1_setup'
    MIN_HISTORY_BARS = 60

    def __init__(self, config=None, params=None):
        merged_config = deepcopy(self.DEFAULT_CONFIG)
        if params:
            merged_config.update(params)
        if config:
            merged_config.update(config)

        self.config = merged_config
        super().__init__('B1阶段型预警策略', deepcopy(self.config))

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """适配 BaseStrategy 接口，统一准备 B1 所需指标。"""
        return self.prepare_indicators(df)

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """统一准备KDJ和知行双线状态。"""
        if df.empty:
            return df.copy()

        result = df.copy()
        # 避免上游重复列导致 row[col] 返回Series，从而触发 float(Series) 异常。
        result = result.loc[:, ~result.columns.duplicated()].copy()
        result['date'] = pd.to_datetime(result['date'])
        result = result.sort_values('date').reset_index(drop=True)

        kdj_df = KDJ(result, n=9, m1=3, m2=3)
        zhixing_df = calculate_zhixing_state(
            result,
            m1=self.config['M1'],
            m2=self.config['M2'],
            m3=self.config['M3'],
            m4=self.config['M4'],
            duokong_pct=self.config['duokong_pct'],
            short_pct=self.config['short_pct'],
        )

        # 覆盖写入指标列而不是 concat，确保列名唯一。
        for col in ['K', 'D', 'J']:
            if col in kdj_df.columns:
                result[col] = pd.to_numeric(kdj_df[col], errors='coerce')

        zhixing_cols = [
            'short_term_trend',
            'bull_bear_line',
            'trend_above',
            'between_lines',
            'fall_in_bowl',
            'near_duokong',
            'near_short_trend',
            'distance_to_bullbear_pct',
            'distance_to_short_term_pct',
            'line_spread_pct',
            'avg_line_bias_pct',
        ]
        for col in zhixing_cols:
            if col in zhixing_df.columns:
                result[col] = zhixing_df[col]

        return result

    def _ensure_prepared_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """避免重复计算指标；如果上游已经准备过指标，则只做列去重与排序。"""
        if df is None or df.empty:
            return df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()

        result = df.loc[:, ~df.columns.duplicated()].copy()
        if 'date' in result.columns:
            result['date'] = pd.to_datetime(result['date'])
            result = result.sort_values('date').reset_index(drop=True)

        required_cols = {
            'K', 'D', 'J', 'short_term_trend', 'bull_bear_line', 'distance_to_bullbear_pct'
        }
        if required_cols.issubset(result.columns):
            return result
        return self.prepare_indicators(result)

    def select_stocks(self, df: pd.DataFrame, stock_name='') -> list:
        """
        适配 BaseStrategy 接口。

        默认 run 链路不再只看 BowlReboundStrategy，
        当股票处于 B1 阶段型 setup 窗口时，这里直接返回预警信号。
        """
        if df is None or df.empty:
            return []

        if stock_name:
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(keyword in stock_name for keyword in invalid_keywords):
                return []
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return []

        prepared = self._ensure_prepared_indicators(df)
        if prepared.empty or len(prepared) < self.MIN_HISTORY_BARS:
            return []

        signal = self.scan_pre_signal(
            prepared,
            lookback_days=int(self.params.get('lookback_days', 80)),
        )
        if not signal.get('detected'):
            return []

        latest = prepared.iloc[-1]
        signal_date = latest['date'].strftime('%Y-%m-%d') if isinstance(latest['date'], pd.Timestamp) else str(latest['date'])
        close_value = self._to_scalar(latest['close'], 'close')
        current_j = signal.get('current_j')
        if current_j is None:
            current_j = self._to_scalar(latest['J'], 'J')

        return [{
            'date': signal_date,
            'close': round(close_value, 2),
            'J': round(float(current_j), 2),
            'volume_ratio': '-',
            'market_cap': '-',
            'short_term_trend': round(self._to_scalar(latest['short_term_trend'], 'short_term_trend'), 2),
            'bull_bear_line': round(self._to_scalar(latest['bull_bear_line'], 'bull_bear_line'), 2),
            'reasons': self._build_pre_signal_reasons(signal),
            'category': self.SIGNAL_CATEGORY,
            'key_candle_date': signal.get('setup_window_start') or signal.get('anchor_date'),
            'anchor_date': signal.get('anchor_date'),
            'anchor_j': signal.get('anchor_j'),
            'setup_window_start': signal.get('setup_window_start'),
            'support_price': signal.get('support_price'),
            'pending': signal.get('pending', 'buy_signal'),
            'message': signal.get('message', ''),
        }]

    def _build_pre_signal_reasons(self, signal: dict) -> list:
        """把阶段型 B1 预警结构压缩成默认结果展示可读的中文理由。"""
        reasons = ['阶段型B1预警', '阶段1-5通过，等待放量大阳确认']

        anchor_date = signal.get('anchor_date')
        anchor_j = signal.get('anchor_j')
        if anchor_date and anchor_j is not None:
            reasons.append(f'低位触发日 {anchor_date} J={anchor_j}')

        setup_window_start = signal.get('setup_window_start')
        if setup_window_start:
            reasons.append(f'setup窗口起点 {setup_window_start}')

        current_j = signal.get('current_j')
        current_dist = signal.get('current_dist_pct')
        if current_j is not None and current_dist is not None:
            reasons.append(f'当前J={current_j} 多空线偏离={current_dist}%')

        support_price = signal.get('support_price')
        if support_price is not None:
            reasons.append(f'洗盘支撑价 {support_price}')

        return reasons

    def analyze(self, df: pd.DataFrame, config=None) -> dict:
        """按阶段分析单个B1案例。"""
        case_config = deepcopy(self.config)
        if config:
            case_config.update(config)

        prepared = self._ensure_prepared_indicators(df)
        if prepared.empty:
            return {'passed': False, 'reason': 'empty_data', 'stages': {}}

        anchor_idx, anchor_row = self._get_row(prepared, case_config['anchor_date'])
        reference_idx, reference_row = self._get_row(prepared, case_config['reference_low_date'])
        breakout_idx, breakout_row = self._get_row(prepared, case_config['breakout_date'])
        washout_end_idx, _ = self._get_row(prepared, case_config['washout_end_date'])
        revisit_idx, revisit_row = self._get_row(prepared, case_config['revisit_date'])
        buy_idx, buy_row = self._get_row(prepared, case_config['buy_date'])

        guard_price = self._to_scalar(anchor_row[case_config['guard_reference_field']], case_config['guard_reference_field'])
        guard_slice = prepared.iloc[anchor_idx + 1: anchor_idx + 1 + case_config['no_break_days']]
        guard_low = self._to_scalar(guard_slice[case_config['guard_compare_field']].min(), case_config['guard_compare_field']) if not guard_slice.empty else None
        guard_passed = (not guard_slice.empty) and guard_low >= guard_price

        anchor_kdj = self._to_scalar(anchor_row[case_config['anchor_kdj_field']], case_config['anchor_kdj_field'])
        anchor_passed = anchor_kdj <= case_config['anchor_kdj_max']

        breakout_close = self._to_scalar(breakout_row['close'], 'close')
        breakout_open = self._to_scalar(breakout_row['open'], 'open')
        breakout_change_pct = (breakout_close - breakout_open) / breakout_open * 100
        breakout_streak = self._count_breakout_streak(prepared, breakout_idx)
        breakout_passed = breakout_change_pct >= case_config['breakout_min_pct'] and breakout_streak >= case_config['breakout_min_streak']

        washout_start_idx = breakout_idx + breakout_streak
        washout_slice = prepared.iloc[washout_start_idx:washout_end_idx + 1]
        support_price = self._to_scalar(reference_row['low'], 'low')
        washout_min_close = self._to_scalar(washout_slice['close'].min(), 'close') if not washout_slice.empty else None
        washout_min_low = self._to_scalar(washout_slice['low'].min(), 'low') if not washout_slice.empty else None
        washout_compare_value = self._to_scalar(washout_slice[case_config['washout_compare_field']].min(), case_config['washout_compare_field']) if not washout_slice.empty else None
        washout_passed = (not washout_slice.empty) and washout_compare_value >= support_price

        setup_start_idx = max(0, revisit_idx - case_config['setup_window_days'] + 1)
        setup_slice = prepared.iloc[setup_start_idx:revisit_idx + 1]
        revisit_line_value = self._to_scalar(revisit_row[case_config['revisit_line_field']], case_config['revisit_line_field'])
        revisit_close = self._to_scalar(revisit_row['close'], 'close')
        revisit_dist_pct = 0.0 if revisit_line_value == 0 else (revisit_close - revisit_line_value) / revisit_line_value * 100
        revisit_kdj = self._to_scalar(revisit_row[case_config['revisit_kdj_field']], case_config['revisit_kdj_field'])
        setup_band_ok = (
            (setup_slice['distance_to_bullbear_pct'].abs() <= case_config['revisit_band_pct']).all()
            if not setup_slice.empty else False
        )
        setup_kdj_ok = (
            (setup_slice[case_config['revisit_kdj_field']] <= case_config['revisit_kdj_max']).all()
            if not setup_slice.empty else False
        )
        setup_band_ok = bool(setup_band_ok)
        setup_kdj_ok = bool(setup_kdj_ok)

        revisit_passed = bool(
            abs(revisit_dist_pct) <= case_config['revisit_band_pct']
            and revisit_kdj <= case_config['revisit_kdj_max']
            and setup_band_ok
            and setup_kdj_ok
        )

        previous_buy_row = prepared.iloc[buy_idx - 1] if buy_idx > 0 else None
        buy_reference_price = self._to_scalar(previous_buy_row[case_config['buy_compare_field']], case_config['buy_compare_field']) if previous_buy_row is not None else None
        buy_trigger_pct = None
        if buy_reference_price and buy_reference_price != 0:
            buy_close_value = self._to_scalar(buy_row['close'], 'close')
            buy_trigger_pct = (buy_close_value - buy_reference_price) / buy_reference_price * 100

        breakout_window_start = max(0, buy_idx - case_config['buy_breakout_lookback_days'])
        breakout_window = prepared.iloc[breakout_window_start:buy_idx]
        previous_high = self._to_scalar(breakout_window['high'].max(), 'high') if not breakout_window.empty else None
        buy_open = self._to_scalar(buy_row['open'], 'open')
        buy_close = self._to_scalar(buy_row['close'], 'close')
        buy_high = self._to_scalar(buy_row['high'], 'high')
        buy_low = self._to_scalar(buy_row['low'], 'low')
        buy_is_limit_like = buy_open == buy_close == buy_high == buy_low
        buy_breakout_ok = previous_high is not None and buy_close >= previous_high
        buy_passed = bool(
            buy_trigger_pct is not None
            and buy_trigger_pct >= case_config['buy_trigger_min_pct']
            and buy_breakout_ok
            and buy_idx > revisit_idx
        )

        stages = {
            'anchor_kdj': {
                'passed': anchor_passed,
                'date': case_config['anchor_date'],
                'field': case_config['anchor_kdj_field'],
                'value': round(anchor_kdj, 2),
                'threshold': case_config['anchor_kdj_max'],
            },
            'guard_days': {
                'passed': guard_passed,
                'days': case_config['no_break_days'],
                'reference_price': round(guard_price, 2),
                'min_guard_value': None if guard_low is None else round(guard_low, 2),
                'records': guard_slice[['date', 'open', 'close', 'low']].to_dict('records'),
            },
            'breakout_streak': {
                'passed': breakout_passed,
                'date': case_config['breakout_date'],
                'breakout_pct': round(breakout_change_pct, 2),
                'streak_days': breakout_streak,
                'min_breakout_pct': case_config['breakout_min_pct'],
            },
            'washout_support': {
                'passed': washout_passed,
                'start_date': str(washout_slice['date'].iloc[0].date()) if not washout_slice.empty else None,
                'end_date': case_config['washout_end_date'],
                'days': int(len(washout_slice)),
                'support_low': round(support_price, 2),
                'min_close': None if washout_min_close is None else round(washout_min_close, 2),
                'min_low': None if washout_min_low is None else round(washout_min_low, 2),
                'compare_field': case_config['washout_compare_field'],
            },
            'revisit_signal': {
                'passed': revisit_passed,
                'date': case_config['revisit_date'],
                'line_field': case_config['revisit_line_field'],
                'distance_pct': round(revisit_dist_pct, 2),
                'band_pct': case_config['revisit_band_pct'],
                'kdj_field': case_config['revisit_kdj_field'],
                'kdj_value': round(revisit_kdj, 2),
                'kdj_threshold': case_config['revisit_kdj_max'],
                'setup_window_days': case_config['setup_window_days'],
                'setup_window_start': str(setup_slice['date'].iloc[0].date()) if not setup_slice.empty else None,
                'setup_window_end': case_config['revisit_date'],
                'setup_band_ok': setup_band_ok,
                'setup_kdj_ok': setup_kdj_ok,
            },
            'buy_signal': {
                'passed': buy_passed,
                'date': case_config['buy_date'],
                'compare_field': case_config['buy_compare_field'],
                'trigger_pct': None if buy_trigger_pct is None else round(buy_trigger_pct, 2),
                'trigger_min_pct': case_config['buy_trigger_min_pct'],
                'breakout_lookback_days': case_config['buy_breakout_lookback_days'],
                'previous_window_high': None if previous_high is None else round(previous_high, 2),
                'buy_close': round(buy_close, 2),
                'limit_like': buy_is_limit_like,
            },
        }

        revisit_offset = revisit_idx - anchor_idx
        support_offset = revisit_idx - reference_idx
        buy_offset = buy_idx - anchor_idx
        buy_support_offset = buy_idx - reference_idx

        return {
            'passed': all(stage['passed'] for stage in stages.values()),
            'stages': stages,
            'recommended_lookback_days': {
                'anchor_to_setup_inclusive': revisit_offset + 1,
                'support_to_setup_inclusive': support_offset + 1,
                'anchor_to_buy_inclusive': buy_offset + 1,
                'support_to_buy_inclusive': buy_support_offset + 1,
            },
            'timeline': {
                'anchor_date': case_config['anchor_date'],
                'breakout_date': case_config['breakout_date'],
                'washout_end_date': case_config['washout_end_date'],
                'setup_date': case_config['revisit_date'],
                'buy_date': case_config['buy_date'],
                'anchor_to_setup_offset': revisit_offset,
                'support_to_setup_offset': support_offset,
                'anchor_to_buy_offset': buy_offset,
                'support_to_buy_offset': buy_support_offset,
            },
        }

    def summarize(self, analysis_result: dict) -> dict:
        """提取适合通知和结果列表展示的摘要字段。"""
        timeline = analysis_result.get('timeline', {})
        lookbacks = analysis_result.get('recommended_lookback_days', {})
        revisit_stage = analysis_result.get('stages', {}).get('revisit_signal', {})
        buy_stage = analysis_result.get('stages', {}).get('buy_signal', {})

        return {
            'passed': bool(analysis_result.get('passed', False)),
            'setup_date': timeline.get('setup_date'),
            'buy_date': timeline.get('buy_date'),
            'setup_distance_pct': revisit_stage.get('distance_pct'),
            'setup_kdj_field': revisit_stage.get('kdj_field'),
            'setup_kdj_value': revisit_stage.get('kdj_value'),
            'buy_trigger_pct': buy_stage.get('trigger_pct'),
            'buy_close': buy_stage.get('buy_close'),
            'anchor_lookback_days': lookbacks.get('anchor_to_buy_inclusive'),
            'support_lookback_days': lookbacks.get('support_to_buy_inclusive'),
        }

    # ------------------------------------------------------------------
    # 前瞻扫描模式 —— 不需要固定日期，动态查找B1结构，适用于全市场实盘扫描
    # 阶段1-5通过即发出"预买入信号"，阶段6(大阳买点)标记为"待确认"
    # ------------------------------------------------------------------

    def scan_pre_signal(self, df: pd.DataFrame, lookback_days: int = 80) -> dict:
        """
        前瞻性B1结构扫描，适用于全市场实盘选股。

        与 analyze() 的区别：
          - 不使用固定历史日期，动态在回溯窗口内寻找anchor
          - 只要阶段1-5全部满足就发出预买信号，阶段6(大阳)尚未发生
          - 适用于"还没启动，处于setup窗口"的股票

        Returns:
            dict with keys:
              detected       : bool  阶段1-5是否全通过
              stage_passed   : {1:bool, 2:bool, 3:bool, 4:bool, 5:bool}
              anchor_date    : str|None  找到的低位KDJ触发日
              anchor_j       : float|None  触发日J值
              setup_window_start : str|None  当前setup窗口开始日
              current_j      : float  今日J值
              current_dist_pct : float  今日距多空线偏离%
              support_price  : float|None  洗盘守护支撑价
              pending        : 'buy_signal'  等待大阳确认买点
              message        : str  诊断信息
        """
        cfg = self.config
        _EMPTY = {
            'detected': False, 'stage_passed': {},
            'anchor_date': None, 'anchor_j': None,
            'setup_window_start': None,
            'current_j': None, 'current_dist_pct': None,
            'support_price': None, 'pending': 'buy_signal',
            'message': 'no_data',
        }

        if df is None or df.empty or len(df) < 30:
            return _EMPTY

        prepared = self._ensure_prepared_indicators(df)
        if prepared.empty:
            return _EMPTY

        # 只看最近 lookback_days 行
        window = prepared.tail(lookback_days).copy().reset_index(drop=True)
        n = len(window)
        today_idx = n - 1

        setup_window_days = int(cfg.get('setup_window_days', 3))
        anchor_kdj_max = float(cfg.get('anchor_kdj_max', 13))
        no_break_days = int(cfg.get('no_break_days', 3))
        breakout_min_pct = float(cfg.get('breakout_min_pct', 4.0))
        breakout_min_streak = int(cfg.get('breakout_min_streak', 3))
        revisit_kdj_max = float(cfg.get('revisit_kdj_max', 20.0))
        revisit_band_pct = float(cfg.get('revisit_band_pct', 3.0))

        # --- 当前状态读取 ---
        try:
            current_j = self._to_scalar(window.iloc[today_idx]['J'], 'J')
            dist_col = window.iloc[today_idx].get('distance_to_bullbear_pct', None)
            current_dist_pct = self._to_scalar(dist_col, 'distance_to_bullbear_pct') if dist_col is not None else 999.0
        except Exception:
            return {**_EMPTY, 'message': 'indicator_error'}

        stage_passed = {}

        # --- Stage 1: 在窗口内找最近的 J ≤ anchor_kdj_max，且至少在25个交易日前 ---
        # 搜索范围：窗口开始 → today-25
        anchor_idx = None
        anchor_j = None
        anchor_open = None
        search_end = max(0, today_idx - 25)

        for i in range(search_end, -1, -1):   # 从近到远，找最近满足条件的一次
            try:
                j_val = self._to_scalar(window.iloc[i]['J'], 'J')
            except Exception:
                continue
            if j_val <= anchor_kdj_max:
                try:
                    open_val = self._to_scalar(window.iloc[i]['open'], 'open')
                except Exception:
                    continue
                anchor_idx = i
                anchor_j = j_val
                anchor_open = open_val
                break

        stage_passed[1] = anchor_idx is not None
        if not stage_passed[1]:
            return {
                **_EMPTY,
                'current_j': round(current_j, 2),
                'current_dist_pct': round(current_dist_pct, 2),
                'message': 'stage1_fail_no_anchor',
            }

        anchor_date = str(window.iloc[anchor_idx]['date'].date())

        # --- Stage 2: 护盘 —— anchor后连续3天 low >= anchor_open ---
        guard_slice = window.iloc[anchor_idx + 1: anchor_idx + 1 + no_break_days]
        if guard_slice.empty:
            stage_passed[2] = False
        else:
            try:
                guard_low_min = float(guard_slice['low'].min())
                stage_passed[2] = guard_low_min >= anchor_open
            except Exception:
                stage_passed[2] = False

        # --- Stage 3: 大阳突破 + 连涨 ---
        breakout_idx = None
        breakout_streak = 0
        if stage_passed[2]:
            search_from = anchor_idx + 1 + no_break_days
            # 大阳突破必须发生在 setup窗口之前留出足够时间（至少15天前）
            search_to = max(search_from, today_idx - setup_window_days - 10)
            for i in range(search_from, search_to):
                try:
                    row_open = self._to_scalar(window.iloc[i]['open'], 'open')
                    row_close = self._to_scalar(window.iloc[i]['close'], 'close')
                    if row_open > 0:
                        pct = (row_close - row_open) / row_open * 100
                        if pct >= breakout_min_pct:
                            breakout_idx = i
                            breakout_streak = self._count_breakout_streak(window, i)
                            break
                except Exception:
                    continue

        stage_passed[3] = (
            breakout_idx is not None
            and breakout_streak >= breakout_min_streak
        )

        # --- Stage 4: 洗盘守住支撑 ---
        support_price = None
        if stage_passed[3]:
            # 支撑价 = anchor 前后3行内的最低 low（模拟参考低点）
            ref_start = max(0, anchor_idx - 2)
            ref_end = min(n, anchor_idx + 3)
            try:
                support_price = float(window.iloc[ref_start:ref_end]['low'].min())
            except Exception:
                support_price = None

            # 洗盘区间：突破连涨结束 → setup窗口开始前
            washout_start = breakout_idx + breakout_streak
            setup_start_idx = max(0, today_idx - setup_window_days + 1)
            washout_slice = window.iloc[washout_start:setup_start_idx]

            if washout_slice.empty or support_price is None:
                stage_passed[4] = True   # 没有中间过渡段，视为通过
            else:
                try:
                    washout_min_close = float(washout_slice['close'].min())
                    stage_passed[4] = washout_min_close >= support_price
                except Exception:
                    stage_passed[4] = False
        else:
            stage_passed[4] = False

        # --- Stage 5: 当前处于 setup 窗口 (J ≤ 20 且 距多空线 ≤ ±3%) ---
        setup_start_idx = max(0, today_idx - setup_window_days + 1)
        setup_slice = window.iloc[setup_start_idx: today_idx + 1]
        setup_window_start = None

        min_days_required = max(1, setup_window_days - 1)  # 至少满足 N-1 天（3天窗口→至少2天，2天窗口→至少1天）
        if setup_slice.empty:
            stage_passed[5] = False
        else:
            try:
                j_series = setup_slice['J'].apply(lambda x: float(x) if not isinstance(x, float) else x)
                dist_series = setup_slice['distance_to_bullbear_pct'].abs()
                days_ok = int(((j_series <= revisit_kdj_max) & (dist_series <= revisit_band_pct)).sum())
                stage_passed[5] = days_ok >= min_days_required
                setup_window_start = str(setup_slice['date'].iloc[0].date())
            except Exception:
                stage_passed[5] = False

        stages_1_to_5_all = all(stage_passed.get(i, False) for i in range(1, 6))
        first_fail = next((i for i in range(1, 6) if not stage_passed.get(i, False)), None)
        message = 'pre_signal_detected' if stages_1_to_5_all else f'stage{first_fail}_fail'

        return {
            'detected': stages_1_to_5_all,
            'stage_passed': stage_passed,
            'anchor_date': anchor_date,
            'anchor_j': round(anchor_j, 2) if anchor_j is not None else None,
            'setup_window_start': setup_window_start,
            'current_j': round(current_j, 2),
            'current_dist_pct': round(current_dist_pct, 2),
            'support_price': round(support_price, 2) if support_price is not None else None,
            'pending': 'buy_signal',
            'message': message,
        }

    def _count_breakout_streak(self, df: pd.DataFrame, breakout_idx: int) -> int:
        streak = 0
        for idx in range(breakout_idx, len(df)):
            current = df.iloc[idx]
            if current['close'] <= current['open']:
                break

            if idx > breakout_idx:
                prev_close = float(df.iloc[idx - 1]['close'])
                if float(current['close']) <= prev_close:
                    break

            streak += 1
        return streak

    def _get_row(self, df: pd.DataFrame, date_str: str):
        target_date = pd.Timestamp(date_str)
        matches = df.index[df['date'] == target_date]
        if len(matches) == 0:
            raise ValueError(f'未找到日期: {date_str}')
        idx = int(matches[0])
        return idx, df.iloc[idx]

    @staticmethod
    def _to_scalar(value, field_name: str):
        """将行取值安全转换为标量，兼容重复列导致的Series场景。"""
        if isinstance(value, pd.Series):
            if value.empty:
                raise ValueError(f'字段 {field_name} 无可用值')
            value = value.iloc[-1]
        return float(value)


# 兼容旧导入名称，避免已有脚本与文档引用立即失效。
B1CaseAnalyzer = B1CaseStrategy