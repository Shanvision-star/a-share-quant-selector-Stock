"""
Zettaranc 组合策略
====================

把 zettaranc-skill（third_party/zettaranc/SKILL.md）核心入场规则固化为一个
独立策略，便于在 ``backtest_engine`` 中作为一个独立信号源跑历史验证。

为什么单独建一个类，不直接复用 BowlReboundStrategy：
  1) bowl_rebound 已经在线上承担 B1 选股职责，参数和阈值是为 LLM 提示与前端展示
     调过的，直接挂规则会污染既有结果与缓存。
  2) zettaranc 把「量比攻击日 + KDJ 翘头 + 站 BBI」当作强约束，bowl_rebound 并没
     有同时强制，需要独立策略以保证回测口径一致。
  3) 独立类便于后续按 ``config/strategy_params.yaml`` 单独调参，不影响其他战法。

约束：
  * 本文件不修改任何现有策略文件；仅复用 utils.technical 的纯函数。
  * 数据按现有约定为 **倒序**（最新一根在 ``df.iloc[0]``），所有 MA/EMA/REF 已
    在 utils.technical 内部正确处理倒序。
  * 历史回看至少 ``MIN_HISTORY=120`` 根（MA114 + BBI24 + KDJ9 安全余量）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from strategy.base_strategy import BaseStrategy
from utils.technical import (
    EXIST,
    KDJ,
    MA,
    REF,
    calculate_zhixing_position_state,
    calculate_zhixing_state,
    has_cached_kdj,
    has_cached_zhixing,
)


# 历史最小长度：MA114 需 114 根，再留 6 根余量给 BBI/J 翘头判定，定 120。
MIN_HISTORY = 120


class ZettarancComboStrategy(BaseStrategy):
    """Zettaranc 完整入场规则组合策略。

    入场（同时满足）：
      E1 双线成形：``len(df) >= MIN_HISTORY`` 且知行短期/多空线非 NaN
      E2 价格在「碗」内：``between_lines`` 或 ``near_duokong`` 或 ``near_short_trend``
      E3 KDJ 低位回升：``J <= J_BUY`` 且 ``J > REF(J,1)``（J 从底部翘起）
      E4 量比攻击：``volume / MA(volume,5) >= VOL_RATIO_MIN``
      E5 收盘站上 BBI：``close > (MA3+MA6+MA12+MA24)/4``
      E6 阳线确认：``close > open``
      E7 市值门槛：复用 ``bowl_rebound`` 的逻辑（≥ ``CAP``）

    阈值默认值与 ``config/strategy_params.yaml`` 的 P1 参数扫描结论保持一致：
      * ``J_BUY=0``：相比初始 ``-5`` 放宽一档，保留低位回升含义并提升样本量。
      * ``VOL_RATIO_MIN=1.3``：相比初始 ``2.0`` 放宽到常态攻击日阈值，避免样本过少。
    """

    DEFAULT_PARAMS: dict[str, Any] = {
        # 与 config/strategy_params.yaml 的优化选型保持一致；yaml 仍是运行期可调来源。
        "J_BUY": 0,             # E3 J 值入场阈值
        "VOL_RATIO_MIN": 1.3,   # E4 量比下限（相对 5 日均量）
        "CAP": 4_000_000_000,   # E7 总市值门槛（40 亿）
        # 知行双线参数（与 utils.technical.calculate_zhixing_state 默认一致）
        "M1": 14,
        "M2": 28,
        "M3": 57,
        "M4": 114,
        # 距离判定百分比
        "duokong_pct": 3,
        "short_pct": 2,
    }

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        merged = dict(self.DEFAULT_PARAMS)
        if params:
            merged.update(params)
        super().__init__("ZettarancCombo", merged)

    # ------------------------------------------------------------------
    # 指标计算
    # ------------------------------------------------------------------
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """在 df 副本上补齐 BBI/KDJ/量比/知行双线等指标。

        注意：必须保持「不原地修改 df」语义（base_strategy 调用方依赖这个不变量）。
        """
        result = df.copy()
        # 去重列名，防止上游缓存把同名列追加多次（来自 bowl_rebound 的实战经验）
        result = result.loc[:, ~result.columns.duplicated()].copy()

        # 1) 知行短期/多空线 —— 复用 utils.technical
        zhixing_params = (
            self.params["M1"],
            self.params["M2"],
            self.params["M3"],
            self.params["M4"],
        )
        if has_cached_zhixing(result, zhixing_params):
            zx_df = calculate_zhixing_position_state(
                result,
                result["short_term_trend"],
                result["bull_bear_line"],
                duokong_pct=self.params["duokong_pct"],
                short_pct=self.params["short_pct"],
            )
        else:
            zx_df = calculate_zhixing_state(
                result,
                m1=self.params["M1"],
                m2=self.params["M2"],
                m3=self.params["M3"],
                m4=self.params["M4"],
                duokong_pct=self.params["duokong_pct"],
                short_pct=self.params["short_pct"],
            )
        for col in zx_df.columns:
            result[col] = zx_df[col]

        # 2) KDJ
        if not has_cached_kdj(result, (9, 3, 3)):
            kdj_df = KDJ(result, n=9, m1=3, m2=3)
            result["K"] = kdj_df["K"]
            result["D"] = kdj_df["D"]
            result["J"] = kdj_df["J"]

        # 3) BBI = (MA3 + MA6 + MA12 + MA24) / 4 —— zettaranc 标志性均线
        result["bbi"] = (
            MA(result["close"], 3)
            + MA(result["close"], 6)
            + MA(result["close"], 12)
            + MA(result["close"], 24)
        ) / 4.0
        # close 高于 BBI（用于回测时按行查询）
        result["above_bbi"] = result["close"] > result["bbi"]

        # 4) 量比（相对 5 日均量），用 MA5(volume) 作为基线
        vol_ma5 = MA(result["volume"], 5)
        result["vol_ratio_5"] = result["volume"] / vol_ma5.replace(0, pd.NA)
        result["vol_attack"] = result["vol_ratio_5"] >= self.params["VOL_RATIO_MIN"]

        # 5) 阳线
        result["positive_candle"] = result["close"] > result["open"]

        # 6) J 翘头：当前 J 大于前一日 J（REF 在倒序数据上拿"前一天"）
        result["j_prev"] = REF(result["J"], 1)
        result["j_lift"] = result["J"] > result["j_prev"]
        result["j_low_enter"] = result["J"] <= self.params["J_BUY"]

        # 7) 市值
        result["market_cap_ok"] = self._check_market_cap(result)

        # 8) 位置满足：碗内 / 贴近多空线 / 贴近短期趋势线 任一即可
        result["in_bowl_zone"] = (
            result["between_lines"]
            | result["near_duokong"]
            | result["near_short_trend"]
        )

        return result

    def _check_market_cap(self, df: pd.DataFrame) -> pd.Series:
        """市值过滤：复用 bowl_rebound 的策略。

        若 ``market_cap`` 列缺失或全部异常（< 1e8），退化为全部放行，避免本地
        历史 CSV 没有市值字段时整个回测变成空集。
        """
        if df.empty:
            return pd.Series(dtype=bool)
        if "market_cap" in df.columns:
            cap = pd.to_numeric(df["market_cap"], errors="coerce")
            valid = cap.dropna()
            if not valid.empty and valid.iloc[-1] > 1e8:
                return cap > self.params["CAP"]
        return pd.Series([True] * len(df), index=df.index)

    # ------------------------------------------------------------------
    # 选股（最新一根）—— 复用 strategy_registry 现有调用
    # ------------------------------------------------------------------
    def select_stocks(self, df: pd.DataFrame, stock_name: str = "") -> list[dict]:
        if df is None or df.empty or len(df) < MIN_HISTORY:
            return []

        # ST/退市过滤（保持与 bowl_rebound 一致）
        if stock_name:
            for kw in ("退", "未知", "退市", "已退"):
                if kw in stock_name:
                    return []
            if stock_name.startswith(("ST", "*ST")):
                return []

        latest = df.iloc[0]
        if not self._row_signal(latest):
            return []

        return [self._build_signal_info(latest, df)]

    # ------------------------------------------------------------------
    # 回测扫描：枚举每一根历史 K 线，输出所有命中的入场点
    # ------------------------------------------------------------------
    def scan_history(
        self,
        df: pd.DataFrame,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """枚举历史每根 K 线，返回所有命中入场规则的信号。

        与 ``select_stocks`` 仅看最新一根不同，回测验证需要枚举每个交易日。
        日期范围 ``[start_date, end_date]``（YYYY-MM-DD）可选；缺省则不限。

        返回的 dict 字段贴近 ``bowl_rebound`` 信号格式，便于复用现有
        ``SignalCandidate.from_mapping``。
        """
        if df is None or df.empty or len(df) < MIN_HISTORY:
            return []

        # CSV 是倒序的（新→旧），这里不重排，直接按行遍历；对每一行复用 _row_signal
        # 优势：所有指标已在 calculate_indicators 算好，scan 只做行级判定，O(N)。
        signals: list[dict] = []
        for idx in range(len(df) - MIN_HISTORY + 1):  # 留出足够历史给指标
            row = df.iloc[idx]
            row_date = str(row.get("date", ""))[:10]
            if start_date and row_date < start_date:
                continue
            if end_date and row_date > end_date:
                continue
            if not self._row_signal(row):
                continue
            signals.append(self._build_signal_info(row, df))
        return signals

    # ------------------------------------------------------------------
    # 行级判定（提取出来便于在 select 和 scan 之间复用）
    # ------------------------------------------------------------------
    def _row_signal(self, row: pd.Series) -> bool:
        """单行（单个交易日）是否命中 zettaranc 全部入场条件。"""
        try:
            # 任何 NaN 都视为指标未就绪
            if pd.isna(row.get("short_term_trend")) or pd.isna(row.get("bull_bear_line")):
                return False
            if pd.isna(row.get("J")) or pd.isna(row.get("j_prev")):
                return False
            if pd.isna(row.get("bbi")) or pd.isna(row.get("vol_ratio_5")):
                return False
            # 异常 J 值（停牌或除权数据脏）
            if abs(float(row["J"])) > 200:
                return False
        except (TypeError, ValueError):
            return False

        return bool(
            row.get("in_bowl_zone", False)
            and row.get("j_low_enter", False)
            and row.get("j_lift", False)
            and row.get("vol_attack", False)
            and row.get("above_bbi", False)
            and row.get("positive_candle", False)
            and row.get("market_cap_ok", True)
        )

    def _build_signal_info(self, row: pd.Series, df: pd.DataFrame) -> dict:
        """统一构造信号 dict。

        ``stop_loss`` 直接取当日最低价（zettaranc 「只输一根 K 线」纪律）。
        ``category`` 按位置标签给一个最优先的命中类型，便于看板分组统计。
        """
        if bool(row.get("between_lines", False)):
            category = "bowl_center"
        elif bool(row.get("near_duokong", False)):
            category = "near_duokong"
        else:
            category = "near_short_trend"

        market_cap = row.get("market_cap")
        market_cap_yi = round(float(market_cap) / 1e8, 2) if pd.notna(market_cap) else None

        return {
            "strategy_name": "zettaranc_combo",
            "date": str(row.get("date", ""))[:10],
            "signal_date": str(row.get("date", ""))[:10],
            "close": round(float(row["close"]), 2),
            "open": round(float(row["open"]), 2),
            "high": round(float(row["high"]), 2),
            "low": round(float(row["low"]), 2),
            "stop_loss": round(float(row["low"]), 2),  # 止损 = 当日最低
            "J": round(float(row["J"]), 2),
            "bbi": round(float(row["bbi"]), 2),
            "vol_ratio": round(float(row["vol_ratio_5"]), 2),
            "short_term_trend": round(float(row["short_term_trend"]), 2),
            "bull_bear_line": round(float(row["bull_bear_line"]), 2),
            "market_cap_yi": market_cap_yi,
            "category": category,
            "reasons": ["碗底攻击日（zettaranc）"],
        }
