"""
StrategyExtractor - 量化交易策略提取器
================================================
【填补的缺口】
现有论文阅读工具（PaperQA2/GPT-Researcher/Paper-Reading-Agent）
能总结论文内容，但缺少"量化策略专项提取"：
  - 无法从论文中识别"买入信号"/"卖出信号"条件
  - 无法提取止损/止盈规则
  - 无法识别持仓周期/资金管理规则
  - 无法将自然语言策略描述转化为结构化信号定义
  - 无法与现有选股框架对接

本模块实现以上缺失功能：
  1. 信号识别：从论文文本识别买入/卖出/过滤条件
  2. 参数提取：lookback/threshold/period 等关键参数
  3. 因子识别：技术因子/基本面因子/情绪因子分类
  4. 策略模板生成：将提取结果转为结构化 StrategySpec
  5. A 股适配：自动映射到 A 股常用指标（KDJ/MACD/量比等）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

from research.paper_parser import ParsedPaper, Section


# ─────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────

@dataclass
class SignalCondition:
    """单个信号条件"""
    description: str            # 原文描述
    condition_type: str         # "buy" / "sell" / "filter" / "exit"
    indicator: str              # 涉及的技术/基本面指标
    direction: str              # "above" / "below" / "cross_up" / "cross_down" / "unknown"
    threshold: Optional[float]  # 阈值（如有）
    confidence: float = 0.5     # 识别置信度 0~1


@dataclass
class StrategySpec:
    """
    从论文中提取的完整策略规格

    这是现有工具缺失的核心输出：
    一个可直接用于构建量化策略的结构化描述
    """
    name: str                                       # 策略名称
    paper_title: str                                # 来源论文
    strategy_type: str                              # "trend" / "mean_reversion" / "factor" / "ml" / "mixed"
    universe: str                                   # 适用标的 "a_share" / "us_stock" / "all"
    holding_period: str                             # 持仓周期 "intraday" / "short" / "medium" / "long"
    buy_conditions: List[SignalCondition]           # 买入条件列表
    sell_conditions: List[SignalCondition]          # 卖出条件列表
    filter_conditions: List[SignalCondition]        # 过滤条件列表
    key_params: Dict[str, float]                    # 关键参数
    factors: List[str]                              # 使用的因子/指标
    backtest_metrics: Dict[str, str]               # 论文中的回测指标
    raw_description: str                            # 原文策略描述
    confidence: float = 0.5                         # 整体提取置信度


# ─────────────────────────────────────────────────
# 规则库
# ─────────────────────────────────────────────────

# 买入信号关键词（中英文）
_BUY_KEYWORDS = [
    "买入", "做多", "开多", "入场", "建仓", "信号触发", "满足条件",
    "buy", "long", "enter", "open position", "signal triggered",
    "突破", "金叉", "放量上涨", "站上", "突破均线",
    "breakout", "golden cross", "volume surge",
]

# 卖出信号关键词
_SELL_KEYWORDS = [
    "卖出", "做空", "平仓", "出场", "止损", "止盈", "离场",
    "sell", "short", "exit", "close position", "stop loss", "take profit",
    "死叉", "跌破", "破位", "缩量",
    "death cross", "break down",
]

# 过滤条件关键词
_FILTER_KEYWORDS = [
    "排除", "过滤", "不含", "剔除", "市值", "流通", "ST",
    "exclude", "filter", "universe", "market cap", "liquidity",
    "仅限", "只考虑", "筛选",
]

# A 股常用技术指标映射（论文描述 → 系统指标名）
_INDICATOR_MAP: Dict[str, str] = {
    # 均线类
    "moving average": "MA",
    "均线": "MA",
    "均移平均": "MA",
    "ma": "MA",
    "ema": "EMA",
    "指数移动平均": "EMA",
    "sma": "SMA",
    # 动量类
    "kdj": "KDJ",
    "kd": "KDJ",
    "随机指标": "KDJ",
    "macd": "MACD",
    "dif": "MACD",
    "rsi": "RSI",
    "相对强弱": "RSI",
    "momentum": "MOMENTUM",
    "动量": "MOMENTUM",
    # 成交量类
    "volume": "VOLUME",
    "成交量": "VOLUME",
    "量比": "VOLUME_RATIO",
    "换手率": "TURNOVER",
    "turnover": "TURNOVER",
    # 布林带
    "bollinger": "BOLL",
    "布林": "BOLL",
    "boll": "BOLL",
    # 趋势类
    "trend": "TREND",
    "趋势": "TREND",
    "atr": "ATR",
    "平均真实波幅": "ATR",
    # 市场宽度
    "涨跌幅": "PCT_CHANGE",
    "return": "PCT_CHANGE",
    "收益率": "PCT_CHANGE",
}

# 持仓周期关键词
_HOLDING_PERIOD_MAP = {
    "intraday": "intraday",
    "日内": "intraday",
    "当天": "intraday",
    "短期": "short",
    "short": "short",
    "几天": "short",
    "1-5": "short",
    "中期": "medium",
    "medium": "medium",
    "数周": "medium",
    "长期": "long",
    "long": "long",
    "数月": "long",
    "季度": "long",
}

# 策略类型关键词
_STRATEGY_TYPE_MAP = {
    "trend following": "trend",
    "趋势跟踪": "trend",
    "momentum": "trend",
    "动量": "trend",
    "mean reversion": "mean_reversion",
    "均值回归": "mean_reversion",
    "反转": "mean_reversion",
    "factor": "factor",
    "因子": "factor",
    "alpha": "factor",
    "machine learning": "ml",
    "deep learning": "ml",
    "神经网络": "ml",
    "lstm": "ml",
    "transformer": "ml",
}


class StrategyExtractor:
    """
    量化策略提取器

    从结构化论文（ParsedPaper）或原始文本中提取完整的量化交易策略规格。

    相比现有工具（GPT-Researcher / Paper-Reading-Agent）：
      1. 专为量化金融域设计，理解买卖信号语义
      2. 输出结构化 StrategySpec，可直接用于策略开发
      3. 自动映射到 A 股技术指标体系
      4. 支持从多篇论文中对比策略（通过 KnowledgeBase 联动）
    """

    def extract_from_paper(self, paper: ParsedPaper) -> StrategySpec:
        """
        从解析后的论文提取策略规格

        参数:
            paper: PaperParser 返回的 ParsedPaper 对象

        返回:
            StrategySpec 结构化策略规格
        """
        # 优先从方法/信号章节提取
        strategy_text = self._get_strategy_text(paper)
        return self.extract_from_text(strategy_text, paper.title)

    def extract_from_text(self, text: str, paper_title: str = "") -> StrategySpec:
        """
        从原始文本提取策略规格

        参数:
            text:        论文全文或策略相关章节
            paper_title: 论文标题（用于记录来源）

        返回:
            StrategySpec 结构化策略规格
        """
        buy_conditions = self._extract_conditions(text, "buy")
        sell_conditions = self._extract_conditions(text, "sell")
        filter_conditions = self._extract_conditions(text, "filter")
        key_params = self._extract_key_params(text)
        factors = self._extract_factors(text)
        backtest_metrics = self._extract_backtest_metrics(text)
        strategy_type = self._detect_strategy_type(text)
        holding_period = self._detect_holding_period(text)
        universe = self._detect_universe(text)
        name = self._generate_strategy_name(paper_title, strategy_type, factors)
        confidence = self._compute_confidence(buy_conditions, sell_conditions, key_params)

        return StrategySpec(
            name=name,
            paper_title=paper_title,
            strategy_type=strategy_type,
            universe=universe,
            holding_period=holding_period,
            buy_conditions=buy_conditions,
            sell_conditions=sell_conditions,
            filter_conditions=filter_conditions,
            key_params=key_params,
            factors=factors,
            backtest_metrics=backtest_metrics,
            raw_description=text[:2000],
            confidence=confidence,
        )

    # ── 内部提取方法 ──────────────────────────────

    def _get_strategy_text(self, paper: ParsedPaper) -> str:
        """优先提取信号/方法章节文本，否则用全文"""
        priority_types = ["signal", "methodology", "experiment"]
        parts = []
        for stype in priority_types:
            for sec in paper.sections:
                if sec.section_type == stype:
                    parts.append(f"[{sec.title}]\n{sec.content}")
        if parts:
            return "\n\n".join(parts)
        return paper.raw_text

    def _extract_conditions(self, text: str, condition_type: str) -> List[SignalCondition]:
        """提取指定类型的信号条件"""
        conditions: List[SignalCondition] = []
        keywords = {
            "buy": _BUY_KEYWORDS,
            "sell": _SELL_KEYWORDS,
            "filter": _FILTER_KEYWORDS,
        }.get(condition_type, [])

        sentences = re.split(r"[。；\n.;]", text)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 5 or len(sent) > 300:
                continue
            if any(kw.lower() in sent.lower() for kw in keywords):
                indicator = self._identify_indicator(sent)
                direction = self._identify_direction(sent)
                threshold = self._extract_threshold(sent)
                confidence = self._sentence_confidence(sent, condition_type)
                conditions.append(SignalCondition(
                    description=sent,
                    condition_type=condition_type,
                    indicator=indicator,
                    direction=direction,
                    threshold=threshold,
                    confidence=confidence,
                ))
        # 去重（相似度大于80%的合并）
        return self._deduplicate_conditions(conditions)

    def _identify_indicator(self, text: str) -> str:
        """识别文本中涉及的技术指标"""
        text_lower = text.lower()
        for pattern, indicator in _INDICATOR_MAP.items():
            if pattern in text_lower:
                return indicator
        return "UNKNOWN"

    def _identify_direction(self, text: str) -> str:
        """识别信号方向（突破/跌破/金叉/死叉等）"""
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["突破", "上穿", "金叉", "cross up", "breakout", "above"]):
            return "cross_up"
        if any(kw in text_lower for kw in ["跌破", "下穿", "死叉", "cross down", "breakdown", "below"]):
            return "cross_down"
        if any(kw in text_lower for kw in ["大于", "高于", "超过", "greater than", "above", ">"]):
            return "above"
        if any(kw in text_lower for kw in ["小于", "低于", "低过", "less than", "below", "<"]):
            return "below"
        return "unknown"

    def _extract_threshold(self, text: str) -> Optional[float]:
        """提取数值阈值"""
        m = re.search(r"(?:>|<|>=|<=|大于|小于|超过|低于|=)\s*(-?\d+\.?\d*%?)", text)
        if m:
            val_str = m.group(1).replace("%", "")
            try:
                val = float(val_str)
                if "%" in m.group(1):
                    val /= 100
                return val
            except ValueError:
                pass
        return None

    def _extract_key_params(self, text: str) -> Dict[str, float]:
        """提取量化参数"""
        params: Dict[str, float] = {}
        pattern = re.compile(
            r"(period|window|lookback|threshold|n|k|alpha|lambda|fast|slow|signal|"
            r"周期|窗口|阈值|回看|天数)\s*[=:：≈]\s*(\d+\.?\d*)",
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            key = m.group(1).lower()
            # 中文 → 英文 映射
            key_map = {"周期": "period", "窗口": "window", "阈值": "threshold",
                       "回看": "lookback", "天数": "period"}
            key = key_map.get(key, key)
            try:
                params[key] = float(m.group(2))
            except ValueError:
                pass
        return params

    def _extract_factors(self, text: str) -> List[str]:
        """提取策略使用的因子/指标列表"""
        factors = set()
        text_lower = text.lower()
        for pattern, indicator in _INDICATOR_MAP.items():
            if pattern in text_lower:
                factors.add(indicator)
        return sorted(factors)

    def _extract_backtest_metrics(self, text: str) -> Dict[str, str]:
        """提取论文中提到的回测指标"""
        metrics: Dict[str, str] = {}
        patterns = [
            (r"(?:夏普|sharpe)[\s比率:：]*([0-9.]+)", "sharpe_ratio"),
            (r"(?:年化|annualized)[收益率\s]*([0-9.]+%?)", "annual_return"),
            (r"(?:最大回撤|max drawdown)[:\s]*([0-9.]+%?)", "max_drawdown"),
            (r"(?:胜率|win rate)[:\s]*([0-9.]+%?)", "win_rate"),
            (r"(?:信息比|information ratio)[:\s]*([0-9.]+)", "information_ratio"),
            (r"(?:calmar)[:\s]*([0-9.]+)", "calmar_ratio"),
        ]
        for pat, key in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                metrics[key] = m.group(1)
        return metrics

    def _detect_strategy_type(self, text: str) -> str:
        """检测策略类型"""
        text_lower = text.lower()
        for kw, stype in _STRATEGY_TYPE_MAP.items():
            if kw in text_lower:
                return stype
        return "mixed"

    def _detect_holding_period(self, text: str) -> str:
        """检测持仓周期"""
        text_lower = text.lower()
        for kw, period in _HOLDING_PERIOD_MAP.items():
            if kw in text_lower:
                return period
        return "medium"

    def _detect_universe(self, text: str) -> str:
        """检测适用市场/标的"""
        text_lower = text.lower()
        if any(kw in text_lower for kw in ["a股", "a-share", "沪深", "上证", "深证", "沪市", "深市"]):
            return "a_share"
        if any(kw in text_lower for kw in ["us stock", "nasdaq", "nyse", "s&p", "美股"]):
            return "us_stock"
        return "all"

    def _generate_strategy_name(self, paper_title: str, strategy_type: str, factors: List[str]) -> str:
        """生成策略名称"""
        if paper_title:
            short_title = paper_title[:20].replace(" ", "_")
            return f"{short_title}_{strategy_type}"
        factor_str = "_".join(factors[:2]) if factors else "unknown"
        return f"extracted_{strategy_type}_{factor_str}"

    def _compute_confidence(
        self,
        buy_conds: List[SignalCondition],
        sell_conds: List[SignalCondition],
        params: Dict[str, float],
    ) -> float:
        """计算整体提取置信度"""
        score = 0.0
        if buy_conds:
            score += 0.4
        if sell_conds:
            score += 0.3
        if params:
            score += 0.2
        avg_cond_conf = (
            sum(c.confidence for c in buy_conds + sell_conds) / max(len(buy_conds + sell_conds), 1)
        )
        score = score * 0.7 + avg_cond_conf * 0.3
        return min(1.0, score)

    def _sentence_confidence(self, sentence: str, condition_type: str) -> float:
        """评估单个句子识别置信度"""
        score = 0.5
        # 有明确数值的条件置信度更高
        if re.search(r"\d+\.?\d*", sentence):
            score += 0.2
        # 有指标名称的置信度更高
        if self._identify_indicator(sentence) != "UNKNOWN":
            score += 0.2
        # 有方向词的置信度更高
        if self._identify_direction(sentence) != "unknown":
            score += 0.1
        return min(1.0, score)

    def _deduplicate_conditions(self, conditions: List[SignalCondition]) -> List[SignalCondition]:
        """简单去重：完全相同描述的只保留一个"""
        seen = set()
        result = []
        for c in conditions:
            key = c.description[:50]
            if key not in seen:
                seen.add(key)
                result.append(c)
        return result

    def compare_strategies(self, specs: List[StrategySpec]) -> List[Dict]:
        """
        跨论文策略对比（现有工具普遍缺失的功能）

        将多个 StrategySpec 按维度对比：
          - 策略类型分布
          - 使用因子重叠度
          - 回测指标对比
          - 参数范围汇总

        参数:
            specs: 多篇论文提取的 StrategySpec 列表

        返回:
            对比报告列表，每项为一个维度的对比字典
        """
        if not specs:
            return []

        report = []

        # 1. 策略类型分布
        type_dist: Dict[str, int] = {}
        for s in specs:
            type_dist[s.strategy_type] = type_dist.get(s.strategy_type, 0) + 1
        report.append({"dimension": "strategy_type_distribution", "data": type_dist})

        # 2. 因子使用频率
        factor_freq: Dict[str, int] = {}
        for s in specs:
            for f in s.factors:
                factor_freq[f] = factor_freq.get(f, 0) + 1
        report.append({"dimension": "factor_frequency", "data": factor_freq})

        # 3. 回测指标汇总
        metric_summary: Dict[str, List[str]] = {}
        for s in specs:
            for k, v in s.backtest_metrics.items():
                metric_summary.setdefault(k, []).append(f"{s.name}: {v}")
        report.append({"dimension": "backtest_metrics", "data": metric_summary})

        # 4. 参数范围
        param_ranges: Dict[str, Tuple[float, float]] = {}
        for s in specs:
            for k, v in s.key_params.items():
                if k not in param_ranges:
                    param_ranges[k] = (v, v)
                else:
                    lo, hi = param_ranges[k]
                    param_ranges[k] = (min(lo, v), max(hi, v))
        report.append({
            "dimension": "parameter_ranges",
            "data": {k: {"min": v[0], "max": v[1]} for k, v in param_ranges.items()},
        })

        # 5. Universe 分布
        universe_dist: Dict[str, int] = {}
        for s in specs:
            universe_dist[s.universe] = universe_dist.get(s.universe, 0) + 1
        report.append({"dimension": "universe_distribution", "data": universe_dist})

        return report
