"""
B2 量化选股策略 — 单体化实现，与其他策略完全隔离
═══════════════════════════════════════════════════════════════════════════

【策略背景与设计哲学】
B2 策略是在 B1 阶段策略的基础上总结提炼而来。
B1 识别的是"多空线支撑 + J值低位"的第一波买点（主力初次建仓信号）；
B2 识别的是"经历一波攻击性大阳线拉升后回调整理、再次突破"的第二波买点
（主力洗盘完成、确认加仓信号）。

B2 信号相比 B1 具有以下特征：
  - 更强的趋势确认：大阳线攻击波已经把股价明显抬高
  - 更强的主力意图：缩量盘整后放量突破，说明主力控盘意愿明确
  - 更低的假突破概率：需同时满足 6 个维度的条件，过滤无效信号
  - 更清晰的止损位：B2 突破日最低价作为止损参考，风险可控

──────────────────────────────────────────────────────────────────────────

【经典案例1：星环科技（688031）选股复盘】

  基本信息：
    代码    : 688031（上交所科创板）
    名称    : 星环科技-U
    板块    : 数据库软件 / 大数据 / 国产替代

  选择理由：
    1. 行业赛道优质 —— 国产数据库软件，受益于信创政策长期红利，
       基本面支撑估值，主力有做多动力。
    2. 技术形态教科书级 —— 整个 B2 形成过程清晰，每个步骤均有
       明确的量价形态支撑，重现性强，便于作为模板推广扫描。
    3. 六步逻辑严丝合缝 ——

       时间轴（交易日）：

         2025-10-28  盘整区间开始（整理起点，主力低吸后控盘蓄力）
               │
               │   盘整期间：高低点相对稳定，量能萎缩，换手率低，
               │   说明主力已经完成初步建仓，开始控盘减少流通盘。
               │   区间最高价可视为"盖板压力位"。
               │
         2025-12-04  盘整区间结束（主力完成洗盘）
               │
         2025-12-10  前20交易日内陆续出现 3~5 根大阳线（攻击波）
         ~12-13      单根涨幅 >= 5%，换手率总和 <= 35% —— 说明是
               │     主力用相对有限的换手率拉高股价，并非散户追高，
               │     属于主力主动控盘式拉升，不是游资炒作。
               │
         2025-12-04  B1 触发日：
               │       - 收盘 62.35，涨跌幅 -1.27%
               │       - 短期趋势线 > 多空线（趋势向上）
               │       - J 值 < 13（深度超卖，KDJ 金叉蓄势）
               │       - 股价贴近知行多空线（近线不破，确认支撑）
               │     => 这是主力"踩线不破"的经典洗盘结束信号。
               │        J值极低说明短期调整充分，动能积蓄待发。
               │
         2025-12-05  B2 突破日（选股核心信号日）：
                       - 收盘价 > 盘整区间最高价（突破"盖板"）
                       - 当日涨幅 >= 4%（有力突破，非温吞上涨）
                       - 当日成交量 > 近10日均量 x 1.5（主力放量）
                       - B2 日 J 值 < 60（未追高，筹码未过热）
                       - B2 前一天 J 值 < 20（超卖区启动，非追涨）
                     => 突破后3日收盘均在多空线上方（主力护盘意愿强）

    4. 止损逻辑清晰 —— B2 突破日最低价作为硬止损位，破位即离场，
       控制最大回撤，不让利润侵蚀。

    5. 盘整突破的 B2 案例字样 —— 进一步强调该案例的教学意义，
       作为盘整突破的经典模板，便于后续策略推广与优化。

──────────────────────────────────────────────────────────────────────────

【6步选股逻辑总览】

  步骤1  B1 前提检查  — 短期趋势线 > 多空线 + J值低位(<13) + 价格贴近短期趋势线
                        （确认主力趋势向上且当前处于调整低谷）
  步骤2  大阳线验证   — B1 日前 20 交易日内存在 3~5 根涨幅>=5% 的大阳线，
                        且换手率总和 <= 35%（确认主力攻击波质量）
  步骤3  整理区间识别 — 根据配置的起止日期，计算区间最高价（压力位）和最低价（支撑位）
                        （当未配置时，自动用波动率收缩法识别）
  步骤4  B2 突破检测  — 收盘价 > 整理区间最高价 + 当日涨幅 >= 4%
                        （突破"盖板"，确认主力拉升意图）
  步骤5  放量确认     — 成交量 > 近10日均量 x 1.5
                        （资金流入确认，排除假突破）
  步骤6  站稳多空线   — 突破后连续3天收盘均在多空线上方
                        （主力护盘，趋势持续性确认）

  附加过滤（6步通过后后置检查）：
    - B2 日 J < 60  ——  防追高，确保买点在相对低估区
    - B2 前一日 J < 20 —— 确认从超卖区启动，非高位追涨

──────────────────────────────────────────────────────────────────────────

【模块隔离边界】（确保不影响其他策略）
  - 不修改任何全局变量 / 全局配置
  - 不改动 BowlReboundStrategy / B1PatternLibrary 的任何代码
  - 只依赖 utils/technical.py 的公共函数（KDJ、calculate_zhixing_state）
  - 只新增 B2_PERFECT_CASES / B2_DEFAULT_PARAMS 到 pattern_config.py

TODO（后续优化预留）：
  - [ ] 步骤3：完善基于波动率收缩的自动整理区间识别精度
  - [ ] 步骤2：增加阳线柱高 vs 阴线柱高 25% 对比验证（过滤假阳线）
  - [ ] 步骤5：增加量能"历史最大量"对比，确认主力拉升级别
  - [ ] 全局：接入 B2 相似度打分机制（参考 B1 的 SIMILARITY_WEIGHTS）
  - [ ] 全局：增加动态止损（跟踪止损，非仅固定在 B2 突破日最低价）
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from strategy.base_strategy import BaseStrategy

# ── 技术指标依赖说明 ──────────────────────────────────────────────────────────
# KDJ               : 随机指标，用于判断超买/超卖区间，核心是 J 值
#                     J = 3K - 2D，范围超出 [0, 100] 时即为超买/超卖信号
#                     J < 13 → 深度超卖（B1 前提），J < 60 → 非追高区（B2 过滤）
# calculate_zhixing_state : 计算"知行双线"——短期趋势线 + 多空线
#                     返回列：trend_above（短期趋势 > 多空线）、
#                             near_short_trend（价格贴近短期趋势线）、
#                             bull_bear_line（多空线数值）、
#                             short_term_trend（短期趋势线数值）
from utils.technical import KDJ, calculate_zhixing_state

logger = logging.getLogger(__name__)


# ─────────────────────── 工具函数 ────────────────────────────────────────────

def _safe_float(val) -> float:
    """
    安全地将 pandas Series 单值或普通标量转换为 float。

    为什么需要这个函数？
    ─────────────────────
    pandas DataFrame 的 .iloc[i][col] 有时返回 Series（当列名重复或操作链路较长时），
    直接 float(series) 会触发 "float() argument must be a string or a number,
    not 'Series'" 错误。此函数统一处理两种情况，消除隐式类型判断。

    边界情况处理：
      - val 为空 Series  → 返回 nan
      - val 为 None      → 返回 nan
      - val 为正常标量   → 直接 float() 转换
    """
    if isinstance(val, pd.Series):
        # 取 Series 第一个元素；若 Series 为空则返回 NaN
        val = val.iloc[0] if len(val) > 0 else float("nan")
    return float(val) if val is not None else float("nan")


# ─────────────────────── B2CaseAnalyzer ─────────────────────────────────────

class B2CaseAnalyzer:
    """
    B2 策略单股分析器（核心执行类）。

    职责
    ────
    对一只股票执行完整的 6 步 B2 分析，串联所有条件检查，返回是否触发 B2
    信号及对应的详细量价信息。

    设计决策
    ────────
    - 无状态：每次 analyze() 调用均独立运行，不依赖实例状态，线程安全。
    - 参数化：所有阈值均通过 params 字典传入，方便 A/B 测试和未来调参。
    - 快速失败：6 步中任一步不满足则立即返回 None，无需再执行后续步骤。

    对外接口
    ────────
        analyze(code, df, case_cfg) -> dict | None

    返回字典包含的字段（满足 B2 时）：
        code、b1_date、b2_date、b2_close、b2_pct_chg、b2_vol_ratio、
        consolidation_high、consolidation_low、consolidation_start、
        consolidation_end、big_up_count、big_up_turnover_sum、
        j_at_b1、matched_case_name、matched_case_id、stop_loss_price
    """

    PATTERN_TYPE_LABELS = {
        "sideways_breakout": "横盘突破型",
        "post_crash_rebuild": "灾后重建型",
        "parallel_artillery": "平行重炮型",
    }

    PATTERN_PRIORITY = {
        "sideways_breakout": 1,
        "post_crash_rebuild": 2,
        "parallel_artillery": 3,
    }

    # ── 默认参数（与 pattern_config.B2_DEFAULT_PARAMS 保持一致）─────────────
    # 以星环科技（688031）实测数据为基准校准，后续可通过 config/strategy_params.yaml 覆盖
    DEFAULT_PARAMS = {
        # ── 步骤1 参数 ─────────────────────────────────────────────────────
        "b1_kdj_threshold":    13,    # J值低于此阈值才视为"深度超卖"
                                      # 688031 的 B1 日 J值约为 0.67，远低于 13，
                                      # 说明当时调整充分，积蓄大量向上弹性。
                                      # 阈值 13 源自对多个历史案例统计：
                                      # J<13 时反弹的概率显著高于 J<20 或 J<30。
        "b1_kdj_relaxed_threshold": 20, # 放宽阈值：严格条件未命中时允许 J<20

        "b1_close_near_pct":    2.0,  # 收盘价距短期趋势线的最大偏离率（%）
                                      # 688031 在 B1 日收盘几乎触及短期趋势线，
                                      # "贴线不破"是主力护盘的典型特征。
                                      # 偏离超过 2% 说明已经跌破支撑，不符合形态。

        "b1_pre_lookback":     20,    # 在 B1 日前多少个交易日内寻找大阳线（步骤2用）
                                      # 约等于 1 个自然月，覆盖一个完整的盘整周期。

        # ── 步骤2 参数 ─────────────────────────────────────────────────────
        "b1_big_up_pct":        5.0,  # 单根"大阳线"的最小涨幅（%）
                                      # < 5% 的上涨可能是正常波动或小资金推升，
                                      # >= 5% 才视为有主力参与的攻击性拉升。

        "b1_big_up_days_min":   3,    # 攻击波大阳线最少根数
                                      # <= 2 根说明主力没有建立趋势性拉升动力
        "b1_big_up_days_max":   5,    # 攻击波大阳线最多根数
                                      # > 5 根可能已经过热或分多个波次，
                                      # 不符合"集中爆发、一波到位"的 B2 特征

        "b1_turnover_sum_pct":  35.0, # 所有大阳线换手率总和上限（%）
                                      # 换手率低说明主力用少量资金拉高，控盘意愿强；
                                      # 换手率高说明是散户跟风追涨，主力可能派发。
                                      # 35% 阈值来自 688031 案例校准。

        # ── 步骤4+5 参数 ───────────────────────────────────────────────────
        "vol_mean_days":        10,   # 放量参考的历史均量天数
                                      # 10 日均量是市场上最常用的短期量能基准

        "vol_multiplier":        1.5, # B2 突破日成交量须达到 10日均量 的倍数
                                      # 1.5x 代表"温和放量"，说明有增量资金流入；
                                      # 不要求 2x 是因为 B2 阶段主力已持仓，
                                      # 无需大量换手即可完成突破。

        "b2_min_pct":            4.0, # B2 突破当日最小涨幅（%）
                                      # 688031 的 B2 日涨幅实盘 +17.02%（2025-12-05）
                                      # < 4% 的突破可能是盘中假突破，不够有力

        # ── 步骤6 参数 ─────────────────────────────────────────────────────
        "b2_hold_days":          3,   # 突破后需连续站稳多空线的天数
                                      # 3 天是"短期趋势确认"的最小周期，
                                      # 少于 3 天则可能是单日脉冲，无持续性
        "b2_must_follow_b1_days": 1,  # B2 与 B1 的交易日间隔，默认要求前一日即 B1

        # ── 灾后重建型参数 ─────────────────────────────────────────────────
        "damage_lookback_days":  50,  # 在 B1 前回看多少天寻找前期破坏段
        "damage_min_drop_pct":   18.0,# 前期从高点到低点至少回撤多少，才算“灾后”
        "reversal_min_pct":       6.0,# 灾后首根反转长阳的最小涨幅
        "reversal_vol_multiplier": 1.8,# 反转长阳相对近 10 日均量的放量倍数
        "rebuild_window_days":   12,  # 灾后修复平台的默认识别窗口

        # ── 平行重炮型参数 ─────────────────────────────────────────────────
        "parallel_lookback_days":   30, # 在 B1 前回看多少天寻找平行大阳
                                        # 由 25 调整为 30：案例6南亚新材 B1=08-12 至第一大阳07-28
                                        # 相距约11个交易日，30天覆盖所有7案例的前置大阳
        "parallel_big_up_pct":       4.0,# 认定平行重炮大阳的单日涨幅门槛
        "parallel_big_up_min_count": 2,  # 至少需要几根平行大阳
        "parallel_big_up_max_count": 4,  # 最多取最近几根平行大阳参与判断
        "parallel_close_band_pct":   5.0,# 多根大阳收盘价允许落在同一价格带的偏差（%）
                                         # 由 2.0 调整为 5.0：案例6南亚新材两根大阳收盘价差为
                                         # 4.78%（48.25 vs 50.61），旧值 2.0 会漏判此案例；
                                         # 5.0% 通过全部7个实盘案例验证（最大4.78%）
        "red_fat_green_vol_ratio":   0.65,# 阴线/小阳的量能需显著小于大阳均量
                                          # 案例5百普赛斯：6/13阴量=0.60x大阳量 ≤ 0.65 ✓
        "b1_to_b2_transition_days": 15,  # 最后一根平行大阳到 B1 的最长过渡天数
        # ── 平行重炮型锚点大阳检测参数 ────────────────────────────────────
        # 用于精准识别 parallel_artillery_rebuild 子类型（底部确认节点）
        # rebuild 定义：平行大阳区间之前存在一根"底部确认节点"
        #   — 涨幅 >= 8%（涨停级别或超预期大阳），代表主力强力介入
        #   — 成交量 >= 近10日均量 × 2（放量确认，非技术性反弹）
        # 案例依据：案例4中坚科技 2025-06-11 +10%/涨停(vol/10dAvg=2.44x)；
        #           案例5百普赛斯 2025-06-12 +8.85%(vol/10dAvg=2.65x)
        "anchor_candle_min_pct":      8.0,  # 锚点大阳最小涨幅（%）
        "anchor_candle_vol_multiplier": 2.0,# 锚点大阳量 >= 近10日均量的倍数
        "anchor_candle_lookback":     60,   # 在第一根平行大阳之前回看多少天找锚点

        # ── 输出目录 ───────────────────────────────────────────────────────
        "export_txt_dir":        "data/txt/B2-match",
    }

    def __init__(self, params: Optional[dict] = None):
        # 外部传入参数优先级高于默认值；
        # 支持只传部分参数（如只修改 b2_min_pct），其余自动补全默认值
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}

    def _prepare_working_df(self, code: str, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """统一准备 B2 所需的原始行情、KDJ 与知行双线列。"""
        # ── 数据量预检：不足则直接跳过，避免指标计算产生全量 NaN ─────────────
        min_rows = max(self.params["b1_pre_lookback"] + self.params["vol_mean_days"] + 10, 130)
        if df is None or len(df) < min_rows:
            return None

        df_asc = df.sort_values("date").reset_index(drop=True)
        if not pd.api.types.is_datetime64_any_dtype(df_asc["date"]):
            df_asc["date"] = pd.to_datetime(df_asc["date"])

        try:
            state_df = calculate_zhixing_state(df_asc)
        except Exception as e:
            logger.warning("[B2] %s 计算双线状态失败: %s", code, e)
            return None

        try:
            kdj_df = KDJ(df_asc)
        except Exception as e:
            logger.warning("[B2] %s 计算KDJ失败: %s", code, e)
            return None

        working_df = state_df.copy()
        working_df["open"] = df_asc["open"].values if "open" in df_asc.columns else df_asc["close"].values
        working_df["K"] = kdj_df["K"].values
        working_df["D"] = kdj_df["D"].values
        working_df["J"] = kdj_df["J"].values
        working_df["date"] = df_asc["date"].values
        working_df["close"] = df_asc["close"].values
        working_df["volume"] = df_asc["volume"].values
        working_df["high"] = df_asc["high"].values if "high" in df_asc.columns else df_asc["close"].values
        working_df["low"] = df_asc["low"].values if "low" in df_asc.columns else df_asc["close"].values

        if "pct_chg" in df_asc.columns:
            working_df["pct_chg"] = df_asc["pct_chg"].values
        else:
            working_df["pct_chg"] = df_asc["close"].pct_change().fillna(0) * 100

        if "turnover" in df_asc.columns:
            working_df["turnover"] = df_asc["turnover"].values
        elif "turnover_rate" in df_asc.columns:
            working_df["turnover"] = df_asc["turnover_rate"].values
        else:
            working_df["turnover"] = float("nan")

        return working_df

    def _resolve_manual_consolidation_dates(self, code: str, case_cfg: dict):
        """
        只有当前扫描股票就是案例本身时，才允许复用案例文档里的固定整理区日期。

        这样可以避免把“星环科技的盘整区间日期”误套到全市场其它股票身上。
        """
        if case_cfg.get("code") == code:
            return case_cfg.get("consolidation_start"), case_cfg.get("consolidation_end")
        return None, None

    def _build_consolidation_from_window(self, working_df: pd.DataFrame, start_idx: int, end_idx: int) -> Optional[dict]:
        """把任意一段 K 线窗口转换为统一的整理区间结构。"""
        start_idx = max(0, int(start_idx))
        end_idx = min(int(end_idx), len(working_df))
        if end_idx - start_idx < 2:
            return None

        window = working_df.iloc[start_idx:end_idx]
        if window.empty:
            return None

        return {
            "high": float(window["high"].max()),
            "low": float(window["low"].min()),
            "start": str(window.iloc[0]["date"])[:10],
            "end": str(window.iloc[-1]["date"])[:10],
        }

    def _identify_low_volatility_consolidation(
        self,
        working_df: pd.DataFrame,
        start_idx: int,
        end_idx: int,
        window_size: int,
    ) -> Optional[dict]:
        """在给定区间中寻找波动率最低的一段，作为动态整理平台。"""
        start_idx = max(0, int(start_idx))
        end_idx = min(int(end_idx), len(working_df))
        if end_idx - start_idx < 4:
            return None

        segment = working_df.iloc[start_idx:end_idx].copy()
        if segment.empty:
            return None

        window_size = max(4, min(int(window_size), len(segment)))
        if len(segment) <= window_size:
            return self._build_consolidation_from_window(working_df, start_idx, end_idx)

        volatility = (segment["high"] - segment["low"]) / segment["close"].replace(0, np.nan)
        rolling_vol = volatility.rolling(window_size).mean()
        min_vol_idx = rolling_vol.idxmin()
        if pd.isna(min_vol_idx):
            return self._build_consolidation_from_window(working_df, start_idx, end_idx)

        local_start = max(start_idx, int(min_vol_idx) - window_size + 1)
        return self._build_consolidation_from_window(working_df, local_start, int(min_vol_idx) + 1)

    def _identify_damage_zone(self, working_df: pd.DataFrame, cutoff_idx: int) -> Optional[dict]:
        """识别灾后重建型在 B1 之前的“破坏段”。"""
        lookback_days = int(self.params["damage_lookback_days"])
        start_idx = max(0, cutoff_idx - lookback_days)
        window = working_df.iloc[start_idx:cutoff_idx].copy()
        if len(window) < 10:
            return None

        rolling_peak = window["close"].cummax()
        drawdown_series = (window["close"] / rolling_peak - 1.0) * 100
        trough_idx = int(drawdown_series.idxmin())
        peak_idx = int(window.loc[:trough_idx, "close"].idxmax())
        peak_close = _safe_float(working_df.iloc[peak_idx]["close"])
        trough_low = _safe_float(working_df.iloc[trough_idx]["low"])
        drop_pct = (peak_close - trough_low) / peak_close * 100 if peak_close > 0 else 0.0

        if drop_pct < float(self.params["damage_min_drop_pct"]):
            return None

        return {
            "peak_idx": peak_idx,
            "trough_idx": trough_idx,
            "damage_start": str(working_df.iloc[peak_idx]["date"])[:10],
            "damage_end": str(working_df.iloc[trough_idx]["date"])[:10],
            "drop_pct": round(drop_pct, 2),
        }

    def _check_reversal_impulse(self, working_df: pd.DataFrame, start_idx: int, end_idx: int) -> Optional[dict]:
        """检查灾后重建型是否出现了放量反转长阳。"""
        vol_days = int(self.params["vol_mean_days"])
        reversal_min_pct = float(self.params["reversal_min_pct"])
        reversal_vol_multiplier = float(self.params["reversal_vol_multiplier"])

        for idx in range(max(1, start_idx + 1), min(end_idx, len(working_df))):
            row = working_df.iloc[idx]
            pct_chg = _safe_float(row.get("pct_chg", float("nan")))
            mean_vol = float(working_df.iloc[max(0, idx - vol_days):idx]["volume"].mean())
            current_vol = _safe_float(row.get("volume", float("nan")))
            is_up_candle = _safe_float(row.get("close", float("nan"))) > _safe_float(row.get("open", float("nan")))
            vol_ok = mean_vol > 0 and current_vol >= mean_vol * reversal_vol_multiplier
            if is_up_candle and pct_chg >= reversal_min_pct and vol_ok:
                return {
                    "idx": idx,
                    "reversal_date": str(row["date"])[:10],
                    "reversal_pct": round(pct_chg, 2),
                    "reversal_vol_ratio": round(current_vol / mean_vol, 2),
                }
        return None

    def _identify_rebuild_platform(self, working_df: pd.DataFrame, reversal_idx: int, b1_idx: int) -> Optional[dict]:
        """识别灾后重建型在反转长阳之后的修复平台。"""
        rebuild_days = int(self.params["rebuild_window_days"])
        start_idx = max(reversal_idx + 1, b1_idx - rebuild_days)
        end_idx = b1_idx
        platform = self._identify_low_volatility_consolidation(
            working_df,
            start_idx,
            end_idx,
            window_size=max(4, rebuild_days // 2),
        )
        if platform is None:
            platform = self._build_consolidation_from_window(working_df, start_idx, end_idx)
        return platform

    def _identify_parallel_big_candles(self, working_df: pd.DataFrame, b1_idx: int) -> Optional[dict]:
        """识别平行重炮型中收盘价落在同一价格带的多根放量大阳。"""
        lookback_days = int(self.params["parallel_lookback_days"])
        min_count = int(self.params["parallel_big_up_min_count"])
        max_count = int(self.params["parallel_big_up_max_count"])
        big_up_pct = float(self.params["parallel_big_up_pct"])
        close_band_pct = float(self.params["parallel_close_band_pct"])

        window = working_df.iloc[max(0, b1_idx - lookback_days):b1_idx].copy()
        if window.empty:
            return None

        candidates = window[
            (window["pct_chg"].apply(_safe_float) >= big_up_pct)
            & (window["close"].apply(_safe_float) > window["open"].apply(_safe_float))
        ].copy()
        if len(candidates) < min_count:
            return None

        candidates = candidates.tail(max_count)
        best_cluster = None
        best_band = None
        for count in range(min_count, len(candidates) + 1):
            cluster = candidates.tail(count)
            avg_close = float(cluster["close"].mean())
            if avg_close <= 0:
                continue
            band_pct = (float(cluster["close"].max()) - float(cluster["close"].min())) / avg_close * 100
            if band_pct <= close_band_pct:
                if best_cluster is None or count > len(best_cluster) or (count == len(best_cluster) and band_pct < best_band):
                    best_cluster = cluster
                    best_band = band_pct

        if best_cluster is None:
            return None

        indices = [int(idx) for idx in best_cluster.index.tolist()]
        return {
            "indices": indices,
            "dates": [str(dt)[:10] for dt in best_cluster["date"].tolist()],
            "count": len(indices),
            "close_band_pct": round(float(best_band), 2),
            "first_idx": indices[0],
            "last_idx": indices[-1],
            "avg_big_volume": round(float(best_cluster["volume"].mean()), 2),
        }

    def _check_red_fat_green_thin(self, working_df: pd.DataFrame, candle_indices: list) -> Optional[dict]:
        """验证平行重炮之间是否存在“红肥绿瘦”的缩量中继。"""
        if not candle_indices:
            return None

        first_idx = min(candle_indices)
        last_idx = max(candle_indices)
        segment = working_df.iloc[first_idx:last_idx + 1].copy()
        if segment.empty:
            return None

        big_up_df = working_df.iloc[candle_indices]
        avg_big_vol = float(big_up_df["volume"].mean()) if not big_up_df.empty else 0.0
        pullback_df = segment.loc[~segment.index.isin(candle_indices)]
        if pullback_df.empty:
            return {
                "ok": True,
                "max_pullback_vol": 0.0,
                "avg_big_vol": round(avg_big_vol, 2),
            }

        max_pullback_vol = float(pullback_df["volume"].max())
        threshold = avg_big_vol * float(self.params["red_fat_green_vol_ratio"])
        return {
            "ok": max_pullback_vol <= threshold,
            "max_pullback_vol": round(max_pullback_vol, 2),
            "avg_big_vol": round(avg_big_vol, 2),
        }

    def _check_b1_to_b2_transition(self, b1_idx: int, last_big_candle_idx: int) -> bool:
        """验证平行重炮最后一根大阳到 B1 的过渡距离，避免拖得太久形态失真。"""
        transition_days = int(self.params["b1_to_b2_transition_days"])
        return last_big_candle_idx < b1_idx <= last_big_candle_idx + transition_days

    def _check_anchor_candle(self, working_df: pd.DataFrame, first_parallel_idx: int) -> Optional[dict]:
        """
        检测平行重炮型的"底部确认节点"（锚点大阳）。

        什么是锚点大阳？
        ─────────────────
        parallel_artillery_rebuild 子类型的核心特征：在平行大阳区间出现之前，
        存在一根"底部确认长阳"，通常是涨停级别（>= 8%）+ 显著放量（>= 近10日均量×2）。
        它代表主力在更低的价位完成初步建仓，随后拉高到平行区间再次试探。

        实盘案例依据（B2_STRATEGY_CASE_LIBRARY.md）：
          案例4 中坚科技 (002779)：2025-06-11 +10.00%（涨停），vol/10dAvg=2.44x
          案例5 百普赛斯 (301080)：2025-06-12 +8.85%，vol/10dAvg=2.65x

        与 _identify_damage_zone() 的区别：
          damage_zone 识别的是"大幅下跌的破坏段"，门槛是回撤 >= 18%（灾后重建型）；
          anchor_candle 识别的是"低位放量启动大阳"，不要求前期大幅下跌，
          更适合平行重炮型的 rebuild 子类型判断。

        Args:
            first_parallel_idx : 第一根平行大阳在 working_df 中的全局索引
                                  仅在此索引之前的区间内搜索锚点大阳

        Returns:
            dict  : 找到锚点大阳时返回其日期、涨幅、量比等信息
            None  : 未找到锚点大阳时返回 None（子类型判定为 platform）
        """
        anchor_min_pct = float(self.params.get("anchor_candle_min_pct", 8.0))
        anchor_vol_mult = float(self.params.get("anchor_candle_vol_multiplier", 2.0))
        anchor_lookback = int(self.params.get("anchor_candle_lookback", 60))
        vol_days = int(self.params["vol_mean_days"])

        start_idx = max(0, first_parallel_idx - anchor_lookback)
        # 仅在平行大阳之前搜索，且留一定间隔（至少5天），避免把平行大阳本身计入
        end_idx = max(0, first_parallel_idx - 5)
        if end_idx <= start_idx:
            return None

        window = working_df.iloc[start_idx:end_idx].copy()
        if window.empty:
            return None

        # 逆向遍历（从最近到最远），取最接近平行区间的锚点大阳
        for local_idx in range(len(window) - 1, -1, -1):
            global_idx = start_idx + local_idx
            row = window.iloc[local_idx]
            pct_chg = _safe_float(row.get("pct_chg", float("nan")))
            if pct_chg < anchor_min_pct:
                continue
            # 确认是阳线（收盘 > 开盘）
            close = _safe_float(row.get("close", float("nan")))
            open_ = _safe_float(row.get("open", float("nan")))
            if close <= open_:
                continue
            # 放量确认
            vol = _safe_float(row.get("volume", float("nan")))
            mean_vol = float(working_df.iloc[max(0, global_idx - vol_days):global_idx]["volume"].mean())
            if mean_vol <= 0 or vol < mean_vol * anchor_vol_mult:
                continue
            return {
                "idx": global_idx,
                "anchor_date": str(row["date"])[:10],
                "anchor_pct": round(pct_chg, 2),
                "anchor_vol_ratio": round(vol / mean_vol, 2),
            }
        return None

    def _build_sideways_breakout_context(self, code: str, working_df: pd.DataFrame, case_cfg: dict) -> Optional[dict]:
        """横盘突破型：标准平台整理 + B1 + 放量突破。"""
        b1_result = self._check_b1_precondition(working_df, case_cfg)
        if b1_result is None:
            return None

        big_up_result = self._check_big_up_candles(working_df, b1_result["idx"])
        if big_up_result is None:
            return None

        start_date, end_date = self._resolve_manual_consolidation_dates(code, case_cfg)
        if start_date and end_date:
            consolidation = self._identify_consolidation(working_df, start_date, end_date)
        else:
            lookback_days = int(case_cfg.get("lookback_days", 40))
            consolidation = self._identify_low_volatility_consolidation(
                working_df,
                max(0, b1_result["idx"] - lookback_days),
                b1_result["idx"],
                window_size=max(6, min(12, lookback_days // 3 or 6)),
            )

        if consolidation is None:
            return None

        return {
            "pattern_type": "sideways_breakout",
            "pattern_label": self.PATTERN_TYPE_LABELS["sideways_breakout"],
            "pattern_subtype": "standard_platform_breakout",
            "pattern_priority": self.PATTERN_PRIORITY["sideways_breakout"],
            "b1_result": b1_result,
            "big_up_result": big_up_result,
            "consolidation": consolidation,
            "pattern_notes": [
                f"平台整理区 {consolidation['start']} ~ {consolidation['end']}",
                f"攻击波大阳 {big_up_result['count']} 根",
            ],
        }

    def _build_post_crash_rebuild_context(self, code: str, working_df: pd.DataFrame, case_cfg: dict) -> Optional[dict]:
        """灾后重建型：先有破坏段，再有放量反转和修复平台。"""
        b1_result = self._check_b1_precondition(working_df, case_cfg)
        if b1_result is None:
            return None

        damage_zone = self._identify_damage_zone(working_df, b1_result["idx"])
        if damage_zone is None:
            return None

        reversal = self._check_reversal_impulse(working_df, damage_zone["trough_idx"], b1_result["idx"])
        if reversal is None:
            return None

        consolidation = self._identify_rebuild_platform(working_df, reversal["idx"], b1_result["idx"])
        if consolidation is None:
            return None

        # 读取反转阳线的实际换手率
        reversal_row = working_df.iloc[reversal["idx"]]
        reversal_turnover = _safe_float(reversal_row.get("turnover", float("nan")))
        reversal_turnover_sum = 0.0 if np.isnan(reversal_turnover) else round(reversal_turnover, 2)

        return {
            "pattern_type": "post_crash_rebuild",
            "pattern_label": self.PATTERN_TYPE_LABELS["post_crash_rebuild"],
            "pattern_subtype": "post_crash_rebuild_platform",
            "pattern_priority": self.PATTERN_PRIORITY["post_crash_rebuild"],
            "b1_result": b1_result,
            "big_up_result": {
                "count": 1,
                "turnover_sum": reversal_turnover_sum,
            },
            "consolidation": consolidation,
            "damage_zone": damage_zone,
            "reversal": reversal,
            "pattern_notes": [
                f"前期破坏段 {damage_zone['damage_start']} ~ {damage_zone['damage_end']} 回撤 {damage_zone['drop_pct']}%",
                f"修复长阳 {reversal['reversal_date']} 涨幅 {reversal['reversal_pct']}%",
            ],
        }

    def _build_parallel_artillery_context(self, code: str, working_df: pd.DataFrame, case_cfg: dict) -> Optional[dict]:
        """平行重炮型：多根相近价位的大阳反复攻击，配合缩量中继与 B1 过渡。"""
        b1_result = self._check_b1_precondition(working_df, case_cfg)
        if b1_result is None:
            return None

        parallel_info = self._identify_parallel_big_candles(working_df, b1_result["idx"])
        if parallel_info is None:
            return None

        red_fat_green = self._check_red_fat_green_thin(working_df, parallel_info["indices"])
        if red_fat_green is None or not red_fat_green.get("ok"):
            return None

        if not self._check_b1_to_b2_transition(b1_result["idx"], parallel_info["last_idx"]):
            return None

        consolidation = self._identify_low_volatility_consolidation(
            working_df,
            parallel_info["first_idx"],
            b1_result["idx"],
            window_size=max(4, min(10, b1_result["idx"] - parallel_info["first_idx"])),
        )
        if consolidation is None:
            consolidation = self._build_consolidation_from_window(
                working_df,
                parallel_info["first_idx"],
                b1_result["idx"],
            )
        if consolidation is None:
            return None

        damage_zone = self._identify_damage_zone(working_df, parallel_info["first_idx"])
        # 使用锚点大阳检测精准判断 rebuild 子类型：
        # rebuild 条件：平行大阳区间之前存在一根底部确认节点（涨幅>=8% + 放量>=均量×2）
        # 这比 damage_zone（需要前期大幅下跌≥18%）更符合平行重炮型案例的实际特征
        # 案例4中坚科技：0625-06-11涨停+10%(2.44x)→rebuild ✓；案例5百普赛斯：06-12+8.85%(2.65x)→rebuild ✓
        anchor_candle = self._check_anchor_candle(working_df, parallel_info["first_idx"])
        pattern_subtype = "parallel_artillery_rebuild" if (damage_zone or anchor_candle) else "parallel_artillery_platform"

        # 汇总各平行大阳线的实际换手率
        parallel_turnovers = [
            _safe_float(working_df.iloc[idx].get("turnover", float("nan")))
            for idx in parallel_info["indices"]
        ]
        parallel_turnover_sum = round(sum(t for t in parallel_turnovers if not np.isnan(t)), 2)

        # 计算 B2 前一日（B1 日）与 B1 前一日的量能对比，用于质量评分注释
        # 平行重炮型的 B2 质量指标：B2 日量 >= B1 日量 × 2（案例4: 2.41x，案例7: 2.30x）
        # 此指标在案例数据中频繁出现，记录到 pattern_notes 供人工参考，不作强制过滤
        b1_vol = float(working_df.iloc[b1_result["idx"]]["volume"]) if b1_result["idx"] < len(working_df) else float("nan")

        notes = [
            f"平行大阳日期 {'/'.join(parallel_info['dates'])}",
            f"收盘价带宽 {parallel_info['close_band_pct']:.2f}%（阈值5.0%）",
            f"红肥绿瘦量能通过，回调量峰值={red_fat_green['max_pullback_vol']:.0f}",
        ]
        if anchor_candle:
            notes.append(
                f"锚点大阳 {anchor_candle['anchor_date']} "
                f"+{anchor_candle['anchor_pct']}% 量比均量×{anchor_candle['anchor_vol_ratio']}→rebuild子类型确认"
            )
        if not np.isnan(b1_vol) and b1_vol > 0:
            notes.append(f"B1日成交量={b1_vol:.0f}（B2日量/B1日量≥2x时信号更强，参见案例4/7）")

        return {
            "pattern_type": "parallel_artillery",
            "pattern_label": self.PATTERN_TYPE_LABELS["parallel_artillery"],
            "pattern_subtype": pattern_subtype,
            "pattern_priority": self.PATTERN_PRIORITY["parallel_artillery"],
            "b1_result": b1_result,
            "big_up_result": {
                "count": parallel_info["count"],
                "turnover_sum": parallel_turnover_sum,
            },
            "consolidation": consolidation,
            "parallel_info": parallel_info,
            "red_fat_green": red_fat_green,
            "damage_zone": damage_zone,
            "anchor_candle": anchor_candle,
            "pattern_notes": notes,
        }

    def _build_pattern_context(self, code: str, working_df: pd.DataFrame, case_cfg: dict) -> Optional[dict]:
        """按 pattern_type 分发到对应的 B2 分类检测器。"""
        pattern_type = case_cfg.get("pattern_type", "sideways_breakout")
        if pattern_type == "post_crash_rebuild":
            return self._build_post_crash_rebuild_context(code, working_df, case_cfg)
        if pattern_type == "parallel_artillery":
            return self._build_parallel_artillery_context(code, working_df, case_cfg)
        return self._build_sideways_breakout_context(code, working_df, case_cfg)

    # ────────────────── 对外主入口 ────────────────────────────────────────────

    def analyze(self, code: str, df: pd.DataFrame, case_cfg: dict) -> Optional[dict]:
        """
        对单只股票执行完整 B2 分析（6步串联，任一步失败则快速返回 None）。

        Args:
            code     : 股票代码，如 "688031"
            df       : CSVManager.read_stock() 返回的原始 DataFrame
                       注意：CSV 存储为"最新日期在最前"的倒序，此函数内部会排序转正序
            case_cfg : pattern_config.B2_PERFECT_CASES 中单个案例的配置字典
                       包含字段：id、name、code、b1_date、b2_date、
                                 consolidation_start、consolidation_end、lookback_days

        Returns:
            dict  : 检测到 B2 信号时返回完整的量价结果字典
            None  : 任一步条件不满足时返回 None，调用方忽略此股票

        执行顺序图：
            df输入 → 数据准备 → 步骤1(B1前提) → 步骤2(大阳线) →
            步骤3(整理区间) → 步骤4+5(突破+放量) → 步骤6(站稳) →
            后置过滤(J值) → 组装结果字典
        """
        working_df = self._prepare_working_df(code, df)
        if working_df is None or working_df.empty:
            return None

        pattern_context = self._build_pattern_context(code, working_df, case_cfg)
        if pattern_context is None:
            return None

        b1_result = pattern_context["b1_result"]
        b1_idx = b1_result["idx"]
        consolidation = pattern_context["consolidation"]
        b2_result = self._detect_b2_breakout(working_df, b1_idx, consolidation)
        if b2_result is None:
            return None
        b2_idx = b2_result["idx"]

        # 时序约束：B2 与 B1 的间隔不超过 max_gap 个交易日
        # （由「精确等于1」改为「最大间隔」，兼容灾后重建/平行重炮等间隔稍长的形态）
        max_gap = int(self.params.get("b2_must_follow_b1_days", 5))
        b1_b2_gap = b2_idx - b1_idx
        if b1_b2_gap > max_gap or b1_b2_gap < 1:
            logger.debug(
                "[B2] %s B2与B1间隔=%d(上限=%d)，跳过",
                code,
                b1_b2_gap,
                max_gap,
            )
            return None

        # ─────────────────────────────────────────────────────────────────────
        # 步骤 6：站稳多空线（改为后验质量标签，不再阻塞当日命中）
        # 当日扫描时 B2 日是最新数据，后续 K 线尚未产生，强制站稳检查会把所有
        # 当日信号过滤掉。改为计算"实际已观测到的连续站稳天数"，写入结果字段。
        # ─────────────────────────────────────────────────────────────────────
        hold_confirmed, hold_observed = self._calc_hold_quality(working_df, b2_idx)
        is_fresh_signal = (b2_idx == len(working_df) - 1)

        # ─────────────────────────────────────────────────────────────────────
        # 后置过滤1：B2 日 J < 60（防止在超买区追高）
        # ─────────────────────────────────────────────────────────────────────
        # 即使突破了整理区间并放量，如果 J 值已经高于 60，说明短期动能已经过热，
        # 买入将承受较大的回调风险。以 688031 为例，B2 日 J 约为 45，处于合理区间。
        b2_row = working_df.iloc[b2_idx]
        b2_j = _safe_float(b2_row.get("J", float("nan")))
        if not np.isnan(b2_j) and b2_j >= 60:
            logger.debug("[B2] %s B2日J值过高 %.2f >= 60，跳过", code, b2_j)
            return None

        # ─────────────────────────────────────────────────────────────────────
        # 后置过滤2：B2 前一日 J < 20（确认从超卖区启动，而非高位追涨）
        # ─────────────────────────────────────────────────────────────────────
        # 这是区分"真实 B2 信号"和"高位假突破"的关键过滤器。
        # 正确的 B2 形态：前一日 J 值仍在超卖区（<20），说明在洗盘充分后突然发力；
        # 错误的追涨行为：前一日 J 值已经较高（>=20），说明股价已经明显上涨，此时买入风险大。
        if b2_idx > 0:
            b2_prev_row = working_df.iloc[b2_idx - 1]
            prev_j = _safe_float(b2_prev_row.get("J", float("nan")))
            if not np.isnan(prev_j) and prev_j >= 20:
                logger.debug("[B2] %s B2前一天J值 %.2f >= 20，跳过", code, prev_j)
                return None

        # ─────────────────────────────────────────────────────────────────────
        # 所有条件通过：组装完整的结果字典返回
        # ─────────────────────────────────────────────────────────────────────
        big_up_result = pattern_context.get("big_up_result", {})
        matched_case_name = case_cfg.get("name") or pattern_context.get("pattern_label", "")
        matched_case_id = case_cfg.get("id") or f"b2_{pattern_context.get('pattern_type', 'unknown')}"
        return {
            "code":                code,
            # B1 触发日信息
            "b1_date":             b1_result["date"],
            # B2 突破日信息（核心买点）
            "b2_date":             b2_result["date"],
            "b2_close":            round(_safe_float(b2_row["close"]), 4),
            "b2_pct_chg":          b2_result["pct_chg"],           # 突破日涨幅（%）
            "b2_vol_ratio":        b2_result["vol_ratio"],          # 量比（突破日量 / 10日均量）
            # 整理区间信息
            "consolidation_high":  consolidation["high"],           # 盘整区间最高价（突破关口）
            "consolidation_low":   consolidation["low"],            # 盘整区间最低价（参考支撑）
            "consolidation_start": consolidation["start"],
            "consolidation_end":   consolidation["end"],
            # 大阳线信息
            "big_up_count":        big_up_result.get("count", 0),          # 大阳线根数（3~5）
            "big_up_turnover_sum": big_up_result.get("turnover_sum", 0.0), # 大阳线换手率总和（%）
            # B1 日 J 值（反映调整充分程度）
            "j_at_b1":             b1_result["j_val"],
            "j_at_b2":             None if np.isnan(b2_j) else round(b2_j, 2),
            # 匹配的经典案例信息
            "matched_case_name":   matched_case_name,
            "matched_case_id":     matched_case_id,
            "pattern_type":        pattern_context.get("pattern_type", "sideways_breakout"),
            "pattern_label":       pattern_context.get("pattern_label", self.PATTERN_TYPE_LABELS["sideways_breakout"]),
            "pattern_subtype":     pattern_context.get("pattern_subtype", "standard_platform_breakout"),
            "pattern_priority":    pattern_context.get("pattern_priority", 0),
            "pattern_notes":       pattern_context.get("pattern_notes", []),
            "damage_start":        pattern_context.get("damage_zone", {}).get("damage_start"),
            "damage_end":          pattern_context.get("damage_zone", {}).get("damage_end"),
            "damage_drop_pct":     pattern_context.get("damage_zone", {}).get("drop_pct"),
            "reversal_date":       pattern_context.get("reversal", {}).get("reversal_date"),
            "reversal_pct":        pattern_context.get("reversal", {}).get("reversal_pct"),
            "parallel_candle_dates": pattern_context.get("parallel_info", {}).get("dates", []),
            "parallel_close_band_pct": pattern_context.get("parallel_info", {}).get("close_band_pct"),
            "shrinking_volume_between_big_ups": pattern_context.get("red_fat_green", {}).get("ok"),
            # 平行重炮型锚点大阳（底部确认节点）信息，用于 rebuild 子类型确认
            "anchor_candle_date":  pattern_context.get("anchor_candle", {}).get("anchor_date") if pattern_context.get("anchor_candle") else None,
            "anchor_candle_pct":   pattern_context.get("anchor_candle", {}).get("anchor_pct") if pattern_context.get("anchor_candle") else None,
            # 止损参考：B2 突破日最低价（若破位则确认突破失败，应止损离场）
            "stop_loss_price":     round(_safe_float(b2_row["low"]), 4),
            # ── 信号质量与时序元数据 ──────────────────────────────────────
            # hold_above_confirmed: B2突破后是否已完成 b2_hold_days 根收盘站稳多空线
            #   True  = 已确认（历史信号，后续走势已知）
            #   False = 尚未确认（当日/近期信号，需继续观察）
            "hold_above_confirmed": hold_confirmed,
            # hold_days_observed: 实际已观测到的连续站稳天数（0 表示 B2 日本身不在多空线上方）
            "hold_days_observed":   hold_observed,
            # is_fresh_signal: B2日是否为数据集中的最新交易日（当日信号）
            "is_fresh_signal":      is_fresh_signal,
            # b1_b2_gap: B2 与 B1 的实际交易日间隔
            "b1_b2_gap":            b1_b2_gap,
        }

    # ──────────────── 步骤1：B1 前提检查 ────────────────────────────────────────

    def _check_b1_precondition(self, working_df: pd.DataFrame, case_cfg: dict) -> Optional[dict]:
        """
        步骤1：在最近 lookback_days 行中扫描"B1 前提"信号日。

        什么是 B1 前提？
        ─────────────────
        B1 是 B2 的"先导信号"，代表主力在完成初步建仓后，利用短期回调进行洗盘
        的末尾阶段。此时股价处于"支撑位附近 + 动能低谷"，是主力二次建仓前的
        最后窗口期。我们寻找 B1 日，是为了确认整个 B2 形态的"起点质量"。

        三个同时满足的条件（AND 逻辑）：
          a. trend_above = True  ← 短期趋势线 > 多空线
             含义：短期趋势方向向上，与主趋势方向一致。
             如果短期趋势已经跌破多空线，说明趋势反转，B2 形态自然失效。

          b. J 值 < b1_kdj_threshold（默认 13）
             含义：KDJ 中的 J 值进入深度超卖区间，说明短期内卖盘已经充分释放，
             反弹弹性大。J < 13 是对"洗盘是否充分"的量化评判。
             688031 案例中：B1 日 J = -4.05，几乎触底，极度充分。

          c. near_short_trend = True  ← 收盘价贴近短期趋势线
             含义：价格虽然回调，但始终没有跌破短期趋势支撑，说明主力在该位置有
             护盘意愿（见比较常见的"踩线不破"形态）。

        扫描方式：
          从 working_df 最后 lookback_days 行内，由新到旧逆向扫描，
          取第一个满足条件的日期作为 B1 触发日（最近的才最相关）。

        Args:
            case_cfg : 提供 lookback_days（默认 40 个交易日，约 2 个自然月）
        """
        strict_thresh = float(self.params["b1_kdj_threshold"])  # 默认 13
        relaxed_thresh = float(self.params.get("b1_kdj_relaxed_threshold", 20))
        lookback = int(case_cfg.get("lookback_days", 40))
        scan_slice = working_df.iloc[-lookback:].copy()  # 只取最近 N 行，节省遍历开销
        relaxed_candidate = None

        # 从最新到最旧扫描：最近的 B1 点才与最新的 B2 突破相关
        for idx in range(len(scan_slice) - 1, -1, -1):
            row         = scan_slice.iloc[idx]
            # 将局部索引 idx 转换为 working_df 全局索引
            global_idx  = len(working_df) - lookback + idx
            trend_above = bool(row.get("trend_above", False))
            near_short  = bool(row.get("near_short_trend", False))
            j_val       = _safe_float(row.get("J", float("nan")))

            # 严格条件：J < 13 且贴近趋势线
            if trend_above and (j_val < strict_thresh) and near_short:
                return {
                    "idx":         global_idx,            # 全局索引，供后续步骤定位
                    "date":        str(row["date"])[:10], # 格式：YYYY-MM-DD
                    "j_val":       round(j_val, 2),       # B1 日 J 值（供结果输出参考）
                    "short_trend": round(_safe_float(row["short_term_trend"]), 4),
                    "bull_bear":   round(_safe_float(row["bull_bear_line"]), 4),
                }

            # 放宽条件：若严格条件未命中，允许 J < 20（只保留最近一个候选）
            if relaxed_candidate is None and trend_above and (j_val < relaxed_thresh):
                relaxed_candidate = {
                    "idx":         global_idx,
                    "date":        str(row["date"])[:10],
                    "j_val":       round(j_val, 2),
                    "short_trend": round(_safe_float(row["short_term_trend"]), 4),
                    "bull_bear":   round(_safe_float(row["bull_bear_line"]), 4),
                }

        # 严格未命中时回退到放宽阈值，避免漏选
        return relaxed_candidate

    # ──────────────── 步骤2：大阳线验证 ──────────────────────────────────────

    def _check_big_up_candles(self, working_df: pd.DataFrame, b1_idx: int) -> Optional[dict]:
        """
        步骤2：验证 B1 触发日之前的攻击波大阳线质量。

        为什么要检查大阳线？
        ─────────────────────
        大阳线攻击波是区分"主力主动拉升"与"市场自然波动"的核心依据。
        在 B2 形态中，整理区间之前必须有一段大阳线攻击波，说明：
          1. 主力已经开始建仓并主动拉高，显示做多意愿
          2. 拉升后的缩量整理（盘整区间）说明主力在惜售和洗盘
          3. 盘整结束后的放量突破才是真正的"确认拉升信号"

        688031 案例中：
          2025-10-28 前的 20 个交易日内共出现 3 根大阳线（涨幅均 > 5%），
          3 根大阳线的换手率总和约 28%，远低于 35% 的上限，
          说明主力用相对集中的筹码拉高，并非散户追涨。

        判定条件（AND 逻辑）：
          ① 单日涨幅 pct_chg >= b1_big_up_pct（默认 5%）
          ② 满足①的 K 线数量在 [min, max] = [3, 5] 之间
          ③ 所有大阳线的换手率之和 <= b1_turnover_sum_pct（默认 35%）
             若换手率数据缺失（NaN），则跳过此条件（宽松处理）

        Args:
            b1_idx : B1 触发日在 working_df 中的全局索引
                     扫描范围为 [b1_idx - lookback, b1_idx)（不含 B1 日本身）

        TODO：增加"阳线柱高 > 阴线柱高 25%"对比验证，过滤跳空假阳线
        """
        lookback     = self.params["b1_pre_lookback"]       # 默认 20 个交易日
        big_up_pct   = self.params["b1_big_up_pct"]         # 默认 5.0%
        min_days     = self.params["b1_big_up_days_min"]    # 默认 3根
        max_days     = self.params["b1_big_up_days_max"]    # 默认 5根
        turnover_cap = self.params["b1_turnover_sum_pct"]   # 默认 35%

        # 截取 B1 日之前的 lookback 个交易日窗口（不含 B1 日本身）
        start_idx = max(0, b1_idx - lookback)
        window = working_df.iloc[start_idx:b1_idx].copy()
        if window.empty:
            return None

        # 筛选出涨幅 >= big_up_pct 的大阳线行
        pct_col     = window["pct_chg"].apply(_safe_float)
        big_up_rows = window[pct_col >= big_up_pct]
        count       = len(big_up_rows)

        # 大阳线数量须在合理范围内：太少说明攻击力不足，太多说明已过热
        if not (min_days <= count <= max_days):
            return None

        # 换手率总和检查：低换手意味着主力用少量筹码推高，控盘质量好
        turnover_vals = big_up_rows["turnover"].apply(_safe_float)
        turnover_sum  = float(turnover_vals.dropna().sum())

        # 若 turnover_sum 为 0（无换手率数据），不强制拒绝（容错）
        # 若有数据且超过上限，则认为是游资爆炒，不符合主力控盘特征
        if not np.isnan(turnover_sum) and turnover_sum > turnover_cap and turnover_sum > 0:
            return None

        return {
            "count":        count,                    # 大阳线根数（3~5）
            "turnover_sum": round(turnover_sum, 2),   # 换手率总和（%）
        }

    # ──────────────── 步骤3：整理区间识别 ────────────────────────────────────

    def _identify_consolidation(
        self,
        working_df: pd.DataFrame,
        start_date: Optional[str],
        end_date: Optional[str],
    ) -> Optional[dict]:
        """
        步骤3：识别大阳线攻击波之后的"盘整区间"，计算关键价格区间。

        盘整区间的意义
        ──────────────
        大阳线拉升后，主力需要通过一段横盘整理来：
          1. 消化浮筹：让短线获利盘出清，减少后续拉升的抛压
          2. 锁定筹码：通过震荡清洗不坚定筹码，提高自身持仓比例
          3. 蓄力待发：在相对低位积蓄买盘力量，为下一波拉升做准备

        盘整区间的最高价即"盖板价"（压力位），也是 B2 突破的关键判断依据。
        一旦收盘价突破该价位，意味着主力完成洗盘，主动开始拉升。

        688031 案例中：
          盘整区间 2025-10-28 ~ 2025-12-04，约35个交易日
          区间最高价（盖板价）即步骤4中的突破判断基准

        两种工作模式：
          ① 手动模式（推荐，精度高）：
             case_cfg 中提供了 consolidation_start / consolidation_end，
             直接用该区间计算最高价和最低价。
          ② 自动模式（备用，适合无手动配置时）：
             用"日内波动率 = (high - low) / close"的滚动均值寻找最低波动区间，
             波动率最低的一段时间就是盘整区间（价格最稳定时主力控盘）。
             精度低于手动模式，后续待优化。

        Args:
            start_date : 盘整区间起始日期字符串，如 "2025-10-28"（None 时自动识别）
            end_date   : 盘整区间结束日期字符串，如 "2025-12-04"（None 时自动识别）
        """
        if not start_date or not end_date:
            # ── 自动模式：通过波动率收缩识别盘整区间 ────────────────────────
            # 日内波动率 = (最高价 - 最低价) / 收盘价，代表当天价格振幅
            # 振幅越小，盘整越充分，主力控盘越明显
            rolling_window = 10  # 使用 10 日滚动窗口平滑单日异常波动

            working_df['volatility'] = (
                working_df['high'] - working_df['low']
            ) / working_df['close']

            # 找到 10 日平均波动率最低的日期，以此为盘整区间的核心
            min_vol_idx = working_df['volatility'].rolling(rolling_window).mean().idxmin()
            if min_vol_idx is not None:
                # 以最低波动率点向前回溯 10 个交易日作为盘整区间起点
                start_date = str(working_df.iloc[max(0, min_vol_idx - rolling_window)]['date'])
                end_date   = str(working_df.iloc[min_vol_idx]['date'])

        # ── 手动/自动模式通用：计算区间最高价和最低价 ────────────────────────
        try:
            if not start_date or not end_date:
                return None  # 自动识别也失败，无法继续

            # pd.to_datetime 能兼容 "2025-10-28" 和 "2025-10-28 00:00:00" 等格式
            start_dt = pd.to_datetime(start_date)
            end_dt   = pd.to_datetime(end_date)

            # 按日期区间过滤（包含两端边界日期的数据）
            window = working_df[
                (working_df["date"] >= start_dt) &
                (working_df["date"] <= end_dt)
            ]
            if window.empty:
                return None  # 该股票在指定区间内无数据（可能停牌）

            # 区间最高价 = B2 突破的关口压力位
            # 区间最低价 = 盘整期支撑位（用于评估后续回撤风险）
            high_val = float(window["high"].max())
            low_val  = float(window["low"].min())

            return {
                "high":  high_val,
                "low":   low_val,
                "start": str(start_dt)[:10],   # 标准化为 YYYY-MM-DD
                "end":   str(end_dt)[:10],
            }
        except Exception as e:
            logger.warning("[B2] 整理区间识别失败: %s", e)
            return None

    # ──────────────── 步骤4+5：B2 突破 + 放量确认 ────────────────────────────

    def _detect_b2_breakout(
        self,
        working_df: pd.DataFrame,
        b1_idx: int,
        consolidation: dict,
    ) -> Optional[dict]:
        """
        步骤4+5：在 B1 触发日之后扫描 B2 突破信号。

        B2 突破的形态含义
        ──────────────────
        B2 突破日是 B2 策略的核心买点。此时主力已经完成洗盘，开始主动拉升：
          - 收盘价突破"盖板价"（盘整区间最高价）：阻力突破，形态确立
          - 当日涨幅 >= 4%：突破力度足够，非试探性上涨
          - 成交量 > 10日均量 x 1.5：资金流入加速，确认买盘介入

                688031 案例（2025-12-05 突破日）：
          - 收盘价突破了 2025-10-28 ~ 2025-12-04 盘整区间的最高价
                    - 当日涨幅 +17.02%，有力突破
                    - 成交量约为 10 日均量的 3.02 倍，主力放量明显

        扫描策略：
          从 B1 日之后的第一根 K 线开始，顺序向后扫描，
          返回第一根同时满足所有条件的 K 线（最早的突破日）。
          若存在多个候选，取最早的（主力最初的拉升意图）。

        条件明细（AND 逻辑）：
          condition_4a：close > consolidation["high"]（突破盖板价）
                        若 high_level 为 NaN（整理区间数据缺失），自动跳过此条件
          condition_4b：pct_chg >= b2_min_pct（涨幅 >= 4%）
          condition_5 ：volume > mean(vol[-vol_mean_days:]) * vol_multiplier（放量）

        TODO：增加"当日量是否创历史最大量"的主力级别放量验证
        """
        b2_min_pct  = self.params["b2_min_pct"]     # 突破日最小涨幅，默认 4%
        vol_days    = self.params["vol_mean_days"]   # 均量计算天数，默认 10
        vol_mult    = self.params["vol_multiplier"]  # 放量系数，默认 1.5
        high_level  = consolidation["high"]           # 盖板压力位（突破关口）

        # 从 B1 日后一根 K 线开始扫描（B1 日本身不算突破日）
        scan_start = b1_idx + 1
        if scan_start >= len(working_df):
            return None  # B1 日已是最新数据，无后续行，无法判断突破

        for idx in range(scan_start, len(working_df)):
            row     = working_df.iloc[idx]
            close   = _safe_float(row["close"])
            pct_chg = _safe_float(row.get("pct_chg", float("nan")))
            volume  = _safe_float(row["volume"])

            # 条件 4a：收盘价突破盘整区间最高价（"盖板"被打开）
            # NaN 情况：整理区间数据缺失时宽松处理，不阻断流程
            above_consolidation = np.isnan(high_level) or (close > high_level)

            # 条件 4b：当日涨幅须达标（防止微小突破 / 假突破）
            pct_ok = (not np.isnan(pct_chg)) and (pct_chg >= b2_min_pct)

            # 条件 5：成交量须显著放大（使用 [idx-vol_days, idx) 的滑动窗口均量）
            # 注意：不包含当日 idx 本身，使用"历史"均量作为基准
            vol_start = max(0, idx - vol_days)
            mean_vol  = float(working_df.iloc[vol_start:idx]["volume"].mean())
            vol_ok    = (mean_vol > 0) and (volume > mean_vol * vol_mult)

            # 三个条件同时满足：确认 B2 突破
            if above_consolidation and pct_ok and vol_ok:
                return {
                    "idx":       idx,                       # 全局索引
                    "date":      str(row["date"])[:10],     # 突破日期
                    "pct_chg":   round(pct_chg, 2),        # 当日涨幅（%）
                    "vol_ratio": round(volume / mean_vol, 2) if mean_vol > 0 else float("nan"),
                    # 量比（突破日量 / 10日均量），688031 实盘约为 2.49
                }

        # 未在 B1 日之后找到任何有效突破日
        return None

    # ──────────────── 步骤6：站稳多空线 ──────────────────────────────────────

    def _calc_hold_quality(self, working_df: pd.DataFrame, b2_idx: int) -> tuple:
        """
        计算 B2 突破后连续站稳多空线的质量指标（后验标签，不再作为硬门槛）。

        原 _check_hold_above_bullbear() 的逻辑改为：
          1. 计算实际已观测到的连续站稳天数（hold_days_observed）
          2. 若观测天数 >= b2_hold_days，则 hold_above_confirmed = True
          3. 当日信号（is_fresh_signal）时，hold_confirmed = False 是正常预期，
             前端应展示为"待确认"而非"信号无效"。

        Returns:
            (hold_confirmed: bool, hold_days_observed: int)
              hold_confirmed     — 是否已完成完整站稳确认
              hold_days_observed — 实际连续站稳天数（从 B2 日起计）
        """
        hold_days = self.params.get("b2_hold_days", 3)   # 默认连续 3 天
        end_idx   = min(b2_idx + hold_days, len(working_df))
        window    = working_df.iloc[b2_idx:end_idx]
        if window.empty:
            return (False, 0)
        # 计算从 B2 日起的连续站稳天数
        above_series = window["close"] > window["bull_bear_line"]
        observed = 0
        for above in above_series:
            if above:
                observed += 1
            else:
                break
        hold_confirmed = (observed >= hold_days)
        return (hold_confirmed, observed)


# ─────────────────────── B2PatternLibrary ───────────────────────────────────

class B2PatternLibrary:
    """
    B2 策略案例库管理器（扫描调度层）。

    职责分工
    ────────
    本类是 B2 策略的"外壳"，负责：
      1. 加载经典案例配置（B2_PERFECT_CASES）
      2. 驱动全市场扫描（scan_all），对每只股票调用 B2CaseAnalyzer
      3. 汇总结果、导出文件、发送钉钉通知（notify_and_export）

    不负责：
      - 具体的 6 步选股逻辑（由 B2CaseAnalyzer 负责）
      - 技术指标的计算（由 utils/technical.py 负责）
      - CSV 读取（由 CSVManager 负责）

    设计原则
    ────────
    - 单体化：与 B1PatternLibrary 完全隔离，两者无继承关系
    - 可扩展：未来添加新经典案例只需在 pattern_config.B2_PERFECT_CASES 追加配置
    - 可替换：scan_all 接受 progress_callback 进度回调，方便接入 UI 进度条

    TODO：
      - [ ] 接入 B2 相似度打分机制（参考 B1 的 SIMILARITY_WEIGHTS）
      - [ ] 支持多案例加权投票（当多个案例均命中时提升置信度）
    """

    def __init__(self, config_params: Optional[dict] = None):
        # 动态导入避免循环引用（pattern_config 反过来不导入 strategy 包）
        from strategy.pattern_config import B2_PERFECT_CASES, B2_DEFAULT_PARAMS

        # 经典案例列表：目前包含 688031（星环科技）等，后续可追加
        self.cases = B2_PERFECT_CASES
        self.pattern_templates = self._build_pattern_templates(B2_PERFECT_CASES)

        # 参数合并优先级：外部传入 > B2_DEFAULT_PARAMS > B2CaseAnalyzer.DEFAULT_PARAMS
        # 外部可通过 config_params 在运行时覆盖单个参数，无需改代码
        self.default_params = {
            **B2CaseAnalyzer.DEFAULT_PARAMS,
            **B2_DEFAULT_PARAMS,
            **(config_params or {}),
        }

        # 创建分析器实例，传入合并后的最终参数
        self.analyzer = B2CaseAnalyzer(self.default_params)
        self._results = []  # 最近一次 scan_all 的结果缓存

        logger.info("[B2] 案例库初始化完成，共 %d 个经典案例", len(self.cases))

    def _build_pattern_templates(self, cases: list) -> list:
        """为三类 B2 模式构建扫描模板，优先使用已配置案例，缺失时退回到通用模板。"""
        case_by_type = {}
        for case in cases:
            pattern_type = case.get("pattern_type", "sideways_breakout")
            case_by_type.setdefault(pattern_type, case)

        templates = []
        for pattern_type in ("parallel_artillery", "post_crash_rebuild", "sideways_breakout"):
            case_cfg = case_by_type.get(pattern_type)
            if case_cfg is None:
                case_cfg = {
                    "id": f"b2_{pattern_type}",
                    "name": B2CaseAnalyzer.PATTERN_TYPE_LABELS.get(pattern_type, pattern_type),
                    "pattern_type": pattern_type,
                    "lookback_days": 40,
                    "tags": ["B2三分类"],
                    "description": f"{B2CaseAnalyzer.PATTERN_TYPE_LABELS.get(pattern_type, pattern_type)}通用模板",
                }
            templates.append(case_cfg)
        return templates

    # ────────────────── 全市场扫描 ───────────────────────────────────────────

    def scan_all(self, stock_list: list, cm, progress_callback=None) -> list:
        """
        对给定股票列表执行 B2 扫描。

        扫描流程
        ────────
        对每只股票：
          1. 从 CSVManager 读取 K 线数据（DataFrame）
          2. 遍历所有经典案例（目前包括 688031 等），调用 analyzer.analyze()
          3. 命中则记录结果并保存 DataFrame（用于后续生成 K 线图）
          4. 全部扫描结束后按 B2 日期倒序排列（最新命中的在最前面）

        Args:
            stock_list        : 待扫描的股票代码列表（如 ["000001", "688031", ...]）
            cm                : CSVManager 实例，提供 read_stock(code) -> DataFrame
            progress_callback : 可选进度回调函数，签名 fn(done:int, total:int, code:str)
                                用于在终端显示进度条 / ETA

        Returns:
            命中 B2 信号的结果字典列表，按 b2_date 从最新到最旧排序
        """
        total   = len(stock_list)
        results = []
        # 保存命中股票的原始 DataFrame，供 notify_and_export 中生成 K 线图使用
        self._stock_data_dict = {}

        for i, code in enumerate(stock_list, 1):
            # 调用进度回调（用于在 quant_system.py 中更新进度条）
            if progress_callback:
                progress_callback(i, total, code)

            # 读取 CSV 数据；read_stock 返回 None 或空 DataFrame 时跳过
            df = cm.read_stock(code)
            if df is None or df.empty:
                continue

            best_result = None
            for case_cfg in self.pattern_templates:
                try:
                    result = self.analyzer.analyze(code, df, case_cfg)
                    if result:
                        if (
                            best_result is None
                            or result.get("pattern_priority", 0) > best_result.get("pattern_priority", 0)
                            or (
                                result.get("pattern_priority", 0) == best_result.get("pattern_priority", 0)
                                and result.get("b2_vol_ratio", 0) > best_result.get("b2_vol_ratio", 0)
                            )
                        ):
                            best_result = result
                except Exception as e:
                    # 单股异常不中断整体流程，记录日志后继续
                    logger.warning("[B2] 分析 %s 时发生异常: %s", code, e)

            if best_result:
                results.append(best_result)
                self._stock_data_dict[code] = df
                logger.info(
                    "[B2] %s 命中！分类=%s 突破日=%s 涨幅=%.1f%% 量比=%.1fx",
                    code,
                    best_result.get("pattern_label", best_result.get("pattern_type", "-")),
                    best_result["b2_date"],
                    best_result["b2_pct_chg"],
                    best_result["b2_vol_ratio"],
                )

        # 按 B2 突破日倒序排列：最新日期的命中结果排在前面，方便快速查阅
        results.sort(
            key=lambda x: (x.get("b2_date", ""), x.get("pattern_priority", 0), x.get("b2_vol_ratio", 0)),
            reverse=True,
        )
        self._results = results

        logger.info("[B2] 扫描完成，命中 %d / %d", len(results), total)
        return results


class B2Strategy(BaseStrategy):
    """将 B2 规则扫描适配为 Web 端统一策略接口。"""

    SIGNAL_CATEGORY = "b2_breakout"

    def __init__(self, params: Optional[dict] = None):
        merged_params = dict(params or {})
        super().__init__("B2二次突破策略", merged_params)
        self.library = B2PatternLibrary(config_params=merged_params)

    def calculate_indicators(self, df) -> pd.DataFrame:
        return df.copy()

    def select_stocks(self, df, stock_name='') -> list:
        return []

    def analyze_stock(self, stock_code, stock_name, df):
        if df is None or df.empty or len(df) < 60:
            return None

        if stock_name:
            invalid_keywords = ('退', '未知', '退市', '已退')
            if any(keyword in stock_name for keyword in invalid_keywords):
                return None
            if stock_name.startswith('ST') or stock_name.startswith('*ST'):
                return None

        best_result = None
        for case_cfg in self.library.pattern_templates:
            try:
                result = self.library.analyzer.analyze(stock_code, df, case_cfg)
            except Exception as exc:
                logger.warning("[B2] Web 扫描 %s 时发生异常: %s", stock_code, exc)
                continue

            if not result:
                continue

            if (
                best_result is None
                or result.get("pattern_priority", 0) > best_result.get("pattern_priority", 0)
                or (
                    result.get("pattern_priority", 0) == best_result.get("pattern_priority", 0)
                    and result.get("b2_vol_ratio", 0) > best_result.get("b2_vol_ratio", 0)
                )
            ):
                best_result = result

        if not best_result:
            return None

        signal = {
            "date": best_result.get("b2_date", ""),
            "close": best_result.get("b2_close"),
            "trigger_price": best_result.get("b2_close"),
            "j_value": best_result.get("j_at_b2", best_result.get("j_at_b1")),
            "volume_ratio": best_result.get("b2_vol_ratio"),
            "category": self.SIGNAL_CATEGORY,
            "reason": (
                f"{best_result.get('pattern_label', 'B2')} | "
                f"案例: {best_result.get('matched_case_name', '-')} | "
                f"涨幅: {best_result.get('b2_pct_chg', 0):.1f}% | "
                f"量比: {best_result.get('b2_vol_ratio', 0):.2f}"
            ),
            "matched_case_name": best_result.get("matched_case_name"),
            "matched_case_id": best_result.get("matched_case_id"),
            "pattern_type": best_result.get("pattern_type"),
            "pattern_label": best_result.get("pattern_label"),
            "pattern_priority": best_result.get("pattern_priority"),
            "stop_loss_price": best_result.get("stop_loss_price"),
            "raw_result": best_result,
        }

        return {
            "code": stock_code,
            "name": stock_name,
            "signals": [signal],
        }

    # ────────────────── 结果导出 + 通知 ──────────────────────────────────────

    def notify_and_export(
        self,
        results: Optional[list] = None,
        notifier=None,
        stock_names: Optional[dict] = None,
    ) -> None:
        """
        将扫描结果导出为 TXT 文件并发送钉钉通知。

        输出内容
        ────────
        1. 详细注释版 TXT（_export_txt）：
           每只命中股票一段，包含 B1/B2 日期、涨幅、量比、整理区间、
           大阳线信息、止损价、匹配案例等完整信息，供交易决策参考。

        2. 通达信导入版 TXT（_export_tdx_txt）：
           仅包含 "SH688031" / "SZ000001" 格式的代码列表，
           可直接导入通达信软件快速定位股票。

        3. 钉钉通知（notifier）：
           优先使用 send_b2_match_results_with_charts（含 K 线图），
           回退到 send_b2_match_results（纯文本），
           若两者均不存在则记录警告。

        Args:
            results     : 命中结果列表，默认使用 scan_all 的缓存结果
            notifier    : DingTalkNotifier 实例（可为 None，仅导出文件不发通知）
            stock_names : {code: name} 映射字典，用于在输出中显示股票名称
        """
        if results is None:
            results = self._results
        if not results:
            logger.info("[B2] 无命中结果，跳过导出")
            return

        # 将股票名称注入每条结果（若结果中尚无 name 字段）
        if stock_names:
            for r in results:
                r.setdefault("name", stock_names.get(r.get("code", ""), r.get("code", "")))

        # ── 导出详细版 TXT ──────────────────────────────────────────
        txt_file_path = self._export_txt(results)
        print(f"[B2] TXT 文件已生成：{txt_file_path}", flush=True)

        # ── 导出通达信版 TXT ─────────────────────────────────────────
        tdx_txt_file_path = self._export_tdx_txt(results)
        print(f"[B2] 通达信导入 TXT 已生成：{tdx_txt_file_path}", flush=True)

        # ── 发送钉钉通知（可选）─────────────────────────────────────
        if notifier:
            # 获取命中股票的原始数据（用于 K 线图生成），若无则为空字典
            stock_data_dict = getattr(self, "_stock_data_dict", {})
            try:
                if hasattr(notifier, "send_b2_match_results_with_charts"):
                    # 优先级1：带 K 线图的完整通知（参考 B1 策略的发送方式）
                    notifier.send_b2_match_results_with_charts(
                        results=results,
                        stock_data_dict=stock_data_dict,
                        stock_names=stock_names or {},
                    )
                elif hasattr(notifier, "send_b2_match_results"):
                    # 优先级2：纯文本通知（不含 K 线图）
                    notifier.send_b2_match_results(results)
                else:
                    logger.warning("[B2] notifier 不支持 B2 通知方法")
            except Exception as e:
                logger.warning("[B2] 发送钉钉通知失败: %s", e)

    def _export_txt(self, results: list) -> str:
        """
        将命中结果导出为详细注释版 TXT 文件。

        输出格式示例：
        ──────────────
          [1] 688031 星环科技-U
              B1 触发日   : 2025-12-04  J值=-4.05
              B2 突破日   : 2025-12-05  涨幅=17.02%  量比=2X
              整理区间    : 2025-10-28 ~ 2025-12-04
              区间最高价  : (实盘确认)
              大阳线      : 3 根  换手率总和=28.5%
              止损价      : 61.56（B2突破日最低价）
              匹配案例    : 星环科技 (b2_case_001)

        文件命名：B2经典图形扫描_YYYYMMDD_HHMM.txt
        """
        export_dir = Path(self.default_params.get("export_txt_dir", "data/txt/B2-match"))
        export_dir.mkdir(parents=True, exist_ok=True)  # 目录不存在时自动创建

        now   = datetime.now()
        fname = export_dir / f"B2经典图形扫描_{now.strftime('%Y%m%d_%H%M')}.txt"

        lines = [
            f"B2 策略扫描结果  {now.strftime('%Y-%m-%d %H:%M')}\n",
            f"共命中 {len(results)} 只\n",
            "=" * 60 + "\n",
            "\n",
        ]

        for i, r in enumerate(results, 1):
            code      = r.get("code", "")
            name      = r.get("name", code)
            pattern   = r.get("pattern_label", r.get("pattern_type", "-"))
            subtype   = r.get("pattern_subtype", "-")
            b1_d      = r.get("b1_date", "-")
            j_val     = r.get("j_at_b1", "-")
            b2_d      = r.get("b2_date", "-")
            pct       = r.get("b2_pct_chg", "-")
            vol_r     = r.get("b2_vol_ratio", "-")
            c_s       = r.get("consolidation_start", "-")
            c_e       = r.get("consolidation_end", "-")
            c_hi      = r.get("consolidation_high", "-")
            big_n     = r.get("big_up_count", "-")
            t_sum     = r.get("big_up_turnover_sum", "-")
            stop      = r.get("stop_loss_price", "-")
            case_name = r.get("matched_case_name", "-")
            case_id   = r.get("matched_case_id", "-")
            notes     = r.get("pattern_notes", [])

            lines += [
                f"[{i}] {code} {name}\n",
                f"    分类类型    : {pattern} / {subtype}\n",
                f"    B1 触发日   : {b1_d}  J值={j_val}\n",
                f"    B2 突破日   : {b2_d}  涨幅={pct}%  量比={vol_r}x\n",
                f"    整理区间    : {c_s} ~ {c_e}\n",
                f"    区间最高价  : {c_hi}\n",
                f"    大阳线      : {big_n} 根  换手率总和={t_sum}%\n",
                f"    止损价      : {stop}（B2突破日最低价）\n",
                f"    匹配案例    : {case_name} ({case_id})\n",
                "\n",
            ]

            if notes:
                for note in notes:
                    lines.append(f"    结构备注    : {note}\n")
                lines.append("\n")

        with open(fname, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return str(fname)

    def _export_tdx_txt(self, results: list) -> None:
        """
        将命中股票导出为通达信（TDX）格式的代码列表 TXT。

        格式说明：
          - 上交所股票（代码以 6 开头）→ "SH688031"
          - 深交所股票（代码以 0/3 开头）→ "SZ000001"
          每行一个代码，可直接导入通达信"自选股"功能批量查看 K 线。

        文件命名：B2_TDX导入_YYYYMMDD_HHMM.txt
        """
        export_dir = Path(self.default_params.get("export_txt_dir", "data/txt/B2-match"))
        export_dir.mkdir(parents=True, exist_ok=True)

        now   = datetime.now()
        fname = export_dir / f"B2_TDX导入_{now.strftime('%Y%m%d_%H%M')}.txt"

        lines = []
        for r in results:
            code = r.get("code", "")
            # 上交所（沪市）：代码以 6 开头（主板 + 科创板 688xxx）
            if code.startswith("6"):
                lines.append(f"SH{code}")
            else:
                # 深交所（深市）：主板 000xxx，中小板 002xxx，创业板 300xxx
                lines.append(f"SZ{code}")

        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            logger.info("[B2] 通达信 TXT 已导出: %s", fname)
            print(f"[B2] 通达信 TXT 已导出: {fname}", flush=True)
        except Exception as e:
            logger.warning("[B2] 通达信 TXT 导出失败: %s", e)
