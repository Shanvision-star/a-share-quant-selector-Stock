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

【经典案例：星环科技（688663）选股复盘】

  基本信息：
    代码    : 688663（上交所科创板）
    名称    : 星环科技
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
         2025-12-14  B1 触发日：
               │       - 短期趋势线 > 多空线（趋势向上）
               │       - J 值 < 13（深度超卖，KDJ 金叉蓄势）
               │       - 股价贴近短期趋势线（近线不破，确认支撑）
               │     => 这是主力"踩线不破"的经典洗盘结束信号。
               │        J值极低说明短期调整充分，动能积蓄待发。
               │
         2025-12-15  B2 突破日（选股核心信号日）：
                       - 收盘价 > 盘整区间最高价（突破"盖板"）
                       - 当日涨幅 >= 4%（有力突破，非温吞上涨）
                       - 当日成交量 > 近10日均量 x 1.5（主力放量）
                       - B2 日 J 值 < 60（未追高，筹码未过热）
                       - B2 前一天 J 值 < 20（超卖区启动，非追涨）
                     => 突破后3日收盘均在多空线上方（主力护盘意愿强）

    4. 止损逻辑清晰 —— B2 突破日最低价作为硬止损位，破位即离场，
       控制最大回撤，不让利润侵蚀。

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

    # ── 默认参数（与 pattern_config.B2_DEFAULT_PARAMS 保持一致）─────────────
    # 以星环科技（688663）实测数据为基准校准，后续可通过 config/strategy_params.yaml 覆盖
    DEFAULT_PARAMS = {
        # ── 步骤1 参数 ─────────────────────────────────────────────────────
        "b1_kdj_threshold":    13,    # J值低于此阈值才视为"深度超卖"
                                      # 688663 的 B1 日 J值约为 0.67，远低于 13，
                                      # 说明当时调整充分，积蓄大量向上弹性。
                                      # 阈值 13 源自对多个历史案例统计：
                                      # J<13 时反弹的概率显著高于 J<20 或 J<30。

        "b1_close_near_pct":    2.0,  # 收盘价距短期趋势线的最大偏离率（%）
                                      # 688663 在 B1 日收盘几乎触及短期趋势线，
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
                                      # 35% 阈值来自 688663 案例校准。

        # ── 步骤4+5 参数 ───────────────────────────────────────────────────
        "vol_mean_days":        10,   # 放量参考的历史均量天数
                                      # 10 日均量是市场上最常用的短期量能基准

        "vol_multiplier":        1.5, # B2 突破日成交量须达到 10日均量 的倍数
                                      # 1.5x 代表"温和放量"，说明有增量资金流入；
                                      # 不要求 2x 是因为 B2 阶段主力已持仓，
                                      # 无需大量换手即可完成突破。

        "b2_min_pct":            4.0, # B2 突破当日最小涨幅（%）
                                      # 688663 的 B2 日涨幅约 5.1%
                                      # < 4% 的突破可能是盘中假突破，不够有力

        # ── 步骤6 参数 ─────────────────────────────────────────────────────
        "b2_hold_days":          3,   # 突破后需连续站稳多空线的天数
                                      # 3 天是"短期趋势确认"的最小周期，
                                      # 少于 3 天则可能是单日脉冲，无持续性

        # ── 输出目录 ───────────────────────────────────────────────────────
        "export_txt_dir":        "data/txt/B2-match",
    }

    def __init__(self, params: Optional[dict] = None):
        # 外部传入参数优先级高于默认值；
        # 支持只传部分参数（如只修改 b2_min_pct），其余自动补全默认值
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}

    # ────────────────── 对外主入口 ────────────────────────────────────────────

    def analyze(self, code: str, df: pd.DataFrame, case_cfg: dict) -> Optional[dict]:
        """
        对单只股票执行完整 B2 分析（6步串联，任一步失败则快速返回 None）。

        Args:
            code     : 股票代码，如 "688663"
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
        # ── 数据量预检：不足则直接跳过，避免指标计算产生全量 NaN ─────────────
        # 多空线（bull_bear_line）需要至少 114 个交易日才能收敛（约半年数据）；
        # 加上回溯天数 + 均量天数的 buffer，设置 130 行为安全下限。
        min_rows = max(self.params["b1_pre_lookback"] + self.params["vol_mean_days"] + 10, 130)
        if df is None or len(df) < min_rows:
            return None

        # ── 数据预处理：CSV 为倒序（最新日期在前），转为正序便于时序计算 ───────
        # 正序（升序）是所有技术指标（KDJ、移动平均）计算的标准输入方向。
        df_asc = df.sort_values("date").reset_index(drop=True)
        if not pd.api.types.is_datetime64_any_dtype(df_asc["date"]):
            # 将字符串日期（如 "2025-12-15"）转为 pandas Timestamp，
            # 便于后续区间过滤时做日期比较
            df_asc["date"] = pd.to_datetime(df_asc["date"])

        # ── 计算知行双线（核心趋势判断指标）────────────────────────────────────
        # calculate_zhixing_state() 返回 DataFrame，包含列：
        #   trend_above      : bool，短期趋势线是否高于多空线（看多信号）
        #   near_short_trend : bool，当前收盘价是否贴近短期趋势线（回调未破支撑）
        #   bull_bear_line   : float，多空线数值（主力成本线）
        #   short_term_trend : float，短期趋势线数值（短期支撑/压力位）
        try:
            state_df = calculate_zhixing_state(df_asc)
        except Exception as e:
            logger.warning("[B2] %s 计算双线状态失败: %s", code, e)
            return None

        # ── 计算 KDJ 随机指标 ───────────────────────────────────────────────────
        # KDJ() 返回 DataFrame，包含列：K、D、J
        # J = 3K - 2D，是超买/超卖的最灵敏指标：
        #   J < 0  : 极度超卖（短期底部区，极少见）
        #   J < 13 : 深度超卖（B1前提阈值，本策略使用）
        #   J < 20 : 超卖区（B2前一日过滤阈值）
        #   J = 50 : 中性
        #   J > 80 : 超买区（不建议追高区间）
        #   J > 100: 极度超买（极少见）
        try:
            kdj_df = KDJ(df_asc)
        except Exception as e:
            logger.warning("[B2] %s 计算KDJ失败: %s", code, e)
            return None

        # ── 合并所有字段到统一的 working_df ─────────────────────────────────────
        # 使用独立的 working_df（基于 state_df），保留双线指标列，
        # 追加 KDJ + 原始行情数据，形成统一的分析视图。
        working_df = state_df.copy()
        working_df["K"]      = kdj_df["K"].values
        working_df["D"]      = kdj_df["D"].values
        working_df["J"]      = kdj_df["J"].values
        working_df["date"]   = df_asc["date"].values
        working_df["close"]  = df_asc["close"].values
        working_df["volume"] = df_asc["volume"].values
        # 高低价：若 CSV 中缺失则用收盘价兜底（避免 KeyError）
        working_df["high"]   = df_asc["high"].values   if "high"  in df_asc.columns else df_asc["close"].values
        working_df["low"]    = df_asc["low"].values    if "low"   in df_asc.columns else df_asc["close"].values

        # 涨幅（%）：优先使用 CSV 中预计算的 pct_chg 列（精度更高）；
        # 若 CSV 中没有此列，则从 close 序列计算日涨幅（精度差一阶）
        if "pct_chg" in df_asc.columns:
            working_df["pct_chg"] = df_asc["pct_chg"].values
        else:
            working_df["pct_chg"] = df_asc["close"].pct_change().fillna(0) * 100

        # 换手率：列名在不同数据源有差异（turnover / turnover_rate），做兼容处理；
        # 无换手率数据时设为 NaN，后续检查会宽松通过（不强制拒绝）
        if "turnover" in df_asc.columns:
            working_df["turnover"] = df_asc["turnover"].values
        elif "turnover_rate" in df_asc.columns:
            working_df["turnover"] = df_asc["turnover_rate"].values
        else:
            working_df["turnover"] = float("nan")

        # ─────────────────────────────────────────────────────────────────────
        # 步骤 1：B1 前提检查（确认趋势 + J值低位 + 贴近支撑）
        # ─────────────────────────────────────────────────────────────────────
        b1_result = self._check_b1_precondition(working_df, case_cfg)
        if b1_result is None:
            # 没有找到满足 B1 前提的交易日，跳过此股票
            return None
        b1_idx = b1_result["idx"]

        # ─────────────────────────────────────────────────────────────────────
        # 步骤 2：大阳线验证（确认主力攻击波质量）
        # ─────────────────────────────────────────────────────────────────────
        big_up_result = self._check_big_up_candles(working_df, b1_idx)
        if big_up_result is None:
            return None

        # ─────────────────────────────────────────────────────────────────────
        # 步骤 3：整理区间识别（确定突破的"关口价"）
        # ─────────────────────────────────────────────────────────────────────
        consolidation = self._identify_consolidation(
            working_df,
            case_cfg.get("consolidation_start"),  # 配置中的盘整起始日期，如 "2025-10-28"
            case_cfg.get("consolidation_end"),    # 配置中的盘整结束日期，如 "2025-12-04"
        )
        if consolidation is None:
            return None

        # ─────────────────────────────────────────────────────────────────────
        # 步骤 4+5：B2 突破 + 放量确认（核心买点信号）
        # ─────────────────────────────────────────────────────────────────────
        b2_result = self._detect_b2_breakout(working_df, b1_idx, consolidation)
        if b2_result is None:
            return None
        b2_idx = b2_result["idx"]

        # ─────────────────────────────────────────────────────────────────────
        # 步骤 6：站稳多空线（确认突破有效，主力护盘）
        # ─────────────────────────────────────────────────────────────────────
        if not self._check_hold_above_bullbear(working_df, b2_idx):
            logger.debug("[B2] %s B2突破后未持续站稳多空线", code)
            return None

        # ─────────────────────────────────────────────────────────────────────
        # 后置过滤1：B2 日 J < 60（防止在超买区追高）
        # ─────────────────────────────────────────────────────────────────────
        # 即使突破了整理区间并放量，如果 J 值已经高于 60，说明短期动能已经过热，
        # 买入将承受较大的回调风险。以 688663 为例，B2 日 J 约为 45，处于合理区间。
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
            "big_up_count":        big_up_result["count"],          # 大阳线根数（3~5）
            "big_up_turnover_sum": big_up_result["turnover_sum"],   # 大阳线换手率总和（%）
            # B1 日 J 值（反映调整充分程度）
            "j_at_b1":             b1_result["j_val"],
            # 匹配的经典案例信息
            "matched_case_name":   case_cfg.get("name", ""),
            "matched_case_id":     case_cfg.get("id", ""),
            # 止损参考：B2 突破日最低价（若破位则确认突破失败，应止损离场）
            "stop_loss_price":     round(_safe_float(b2_row["low"]), 4),
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
             688663 案例中：B1 日 J = 0.67，几乎触底，极度充分。

          c. near_short_trend = True  ← 收盘价贴近短期趋势线
             含义：价格虽然回调，但始终没有跌破短期趋势支撑，说明主力在该位置有
             护盘意愿（见比较常见的"踩线不破"形态）。

        扫描方式：
          从 working_df 最后 lookback_days 行内，由新到旧逆向扫描，
          取第一个满足条件的日期作为 B1 触发日（最近的才最相关）。

        Args:
            case_cfg : 提供 lookback_days（默认 40 个交易日，约 2 个自然月）
        """
        j_thresh   = self.params["b1_kdj_threshold"]   # 默认 13
        lookback   = int(case_cfg.get("lookback_days", 40))
        scan_slice = working_df.iloc[-lookback:].copy()  # 只取最近 N 行，节省遍历开销

        # 从最新到最旧扫描：最近的 B1 点才与最新的 B2 突破相关
        for idx in range(len(scan_slice) - 1, -1, -1):
            row         = scan_slice.iloc[idx]
            # 将局部索引 idx 转换为 working_df 全局索引
            global_idx  = len(working_df) - lookback + idx
            trend_above = bool(row.get("trend_above", False))
            near_short  = bool(row.get("near_short_trend", False))
            j_val       = _safe_float(row.get("J", float("nan")))

            # 三个条件必须同时成立（AND）
            if trend_above and (j_val < j_thresh) and near_short:
                return {
                    "idx":         global_idx,            # 全局索引，供后续步骤定位
                    "date":        str(row["date"])[:10], # 格式：YYYY-MM-DD
                    "j_val":       round(j_val, 2),       # B1 日 J 值（供结果输出参考）
                    "short_trend": round(_safe_float(row["short_term_trend"]), 4),
                    "bull_bear":   round(_safe_float(row["bull_bear_line"]), 4),
                }

        # 在回溯窗口内未找到符合条件的 B1 日
        return None

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

        688663 案例中：
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

        688663 案例中：
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

        688663 案例（2025-12-15 突破日）：
          - 收盘价突破了 2025-10-28 ~ 2025-12-04 盘整区间的最高价
          - 当日涨幅约 5.1%，有力突破
          - 成交量约为 10 日均量的 1.94 倍，主力放量明显

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
                    # 量比（突破日量 / 10日均量），688663 约为 1.94
                }

        # 未在 B1 日之后找到任何有效突破日
        return None

    # ──────────────── 步骤6：站稳多空线 ──────────────────────────────────────

    def _check_hold_above_bullbear(self, working_df: pd.DataFrame, b2_idx: int) -> bool:
        """
        步骤6：验证 B2 突破后连续站稳多空线（主力护盘确认）。

        为什么需要验证站稳多空线？
        ──────────────────────────
        单日放量突破有时是"假突破"或"一日游行情"，主力在拉高后立即出货。
        真实的 B2 信号中，主力在突破后会持续护盘，维持股价在多空线（主力成本线）
        上方，以保护自身的浮动利润，并为后续更大级别的拉升蓄势。

        多空线（bull_bear_line）的含义：
          多空线是长期加权均线，可理解为"主力平均持仓成本线"。
          收盘价持续在多空线上方，说明大多数持仓者处于浮盈状态，
          主力没有动力出货，整体处于强势格局。

        实现细节：
          检查 [b2_idx, b2_idx + hold_days) 内每一根 K 线的收盘价 > 多空线。
          若 B2 日为最新数据（后续数据不足 hold_days 根），
          已有数据全部满足即视为通过，兼容实时扫描场景。

        Args:
            b2_idx    : B2 突破日在 working_df 中的全局索引
        """
        hold_days = self.params["b2_hold_days"]   # 默认连续 3 天
        # 取 B2 日起的 hold_days 根 K 线（末尾不足则取到最后一行）
        end_idx   = min(b2_idx + hold_days, len(working_df))
        window    = working_df.iloc[b2_idx:end_idx]
        if window.empty:
            return False
        # 全部收盘价须高于对应日期的多空线值（所有行均满足 AND）
        return bool((window["close"] > window["bull_bear_line"]).all())


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

        # 经典案例列表：当前仅有 688663（星环科技），后续可追加
        self.cases = B2_PERFECT_CASES

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

    # ────────────────── 全市场扫描 ───────────────────────────────────────────

    def scan_all(self, stock_list: list, cm, progress_callback=None) -> list:
        """
        对给定股票列表执行 B2 扫描。

        扫描流程
        ────────
        对每只股票：
          1. 从 CSVManager 读取 K 线数据（DataFrame）
          2. 遍历所有经典案例（目前仅 688663 一个），调用 analyzer.analyze()
          3. 命中则记录结果并保存 DataFrame（用于后续生成 K 线图）
          4. 全部扫描结束后按 B2 日期倒序排列（最新命中的在最前面）

        Args:
            stock_list        : 待扫描的股票代码列表（如 ["000001", "688663", ...]）
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

            # 遍历所有经典案例（OR 逻辑：任一案例命中即记录）
            # 目前只有 688663 一个案例，未来可添加更多
            for case_cfg in self.cases:
                try:
                    result = self.analyzer.analyze(code, df, case_cfg)
                    if result:
                        results.append(result)
                        # 保存 DataFrame 以便后续生成 K 线图（内存中保留，不重复读盘）
                        self._stock_data_dict[code] = df
                        logger.info(
                            "[B2] %s 命中！突破日=%s 涨幅=%.1f%% 量比=%.1fx",
                            code,
                            result["b2_date"],
                            result["b2_pct_chg"],
                            result["b2_vol_ratio"],
                        )
                except Exception as e:
                    # 单股异常不中断整体流程，记录日志后继续
                    logger.warning("[B2] 分析 %s 时发生异常: %s", code, e)

        # 按 B2 突破日倒序排列：最新日期的命中结果排在前面，方便快速查阅
        results.sort(key=lambda x: x.get("b2_date", ""), reverse=True)
        self._results = results

        logger.info("[B2] 扫描完成，命中 %d / %d", len(results), total)
        return results

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
           仅包含 "SH688663" / "SZ000001" 格式的代码列表，
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
          [1] 688663 星环科技
              B1 触发日   : 2025-12-14  J值=0.67
              B2 突破日   : 2025-12-15  涨幅=5.1%  量比=1.94x
              整理区间    : 2025-10-28 ~ 2025-12-04
              区间最高价  : 47.82
              大阳线      : 3 根  换手率总和=28.5%
              止损价      : 46.50（B2突破日最低价）
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

            lines += [
                f"[{i}] {code} {name}\n",
                f"    B1 触发日   : {b1_d}  J值={j_val}\n",
                f"    B2 突破日   : {b2_d}  涨幅={pct}%  量比={vol_r}x\n",
                f"    整理区间    : {c_s} ~ {c_e}\n",
                f"    区间最高价  : {c_hi}\n",
                f"    大阳线      : {big_n} 根  换手率总和={t_sum}%\n",
                f"    止损价      : {stop}（B2突破日最低价）\n",
                f"    匹配案例    : {case_name} ({case_id})\n",
                "\n",
            ]

        with open(fname, "w", encoding="utf-8") as f:
            f.writelines(lines)

        return str(fname)

    def _export_tdx_txt(self, results: list) -> None:
        """
        将命中股票导出为通达信（TDX）格式的代码列表 TXT。

        格式说明：
          - 上交所股票（代码以 6 开头）→ "SH688663"
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
