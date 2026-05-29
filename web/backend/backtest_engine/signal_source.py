"""信号入口。

Web 层可以继续从人工选股池或策略结果库查询候选，回测引擎只依赖
SignalSource 协议，因此后续可替换成文件、数据库、消息队列或 QMT 观察列表。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Protocol

from web.backend.backtest_engine.models import BacktestParams, SignalCandidate


class SignalSource(Protocol):
    """候选信号读取协议。"""

    def fetch(self, params: BacktestParams) -> list[SignalCandidate]:
        """返回候选信号。"""


class StaticSignalSource:
    """用已查询好的候选列表构造信号源。"""

    def __init__(self, candidates: list[SignalCandidate]):
        self.candidates = list(candidates)

    def fetch(self, params: BacktestParams) -> list[SignalCandidate]:
        return list(self.candidates)


def cap_positions_per_day(candidates: list[SignalCandidate], max_positions: int) -> list[SignalCandidate]:
    """按信号日限制每日最大候选数量，保持旧回测 max_positions_per_day 语义。"""
    if max_positions <= 0:
        return candidates
    grouped: dict[str, list[SignalCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.signal_date or candidate.trade_date or ""].append(candidate)

    capped: list[SignalCandidate] = []
    for trade_date in sorted(grouped):
        capped.extend(sorted(grouped[trade_date], key=lambda item: item.code)[:max_positions])
    return capped


# 任务 C：组合策略 / 多战法融合所需的辅助函数
# 设计动机：
# 1) 单只股票同日可能被 b1 / bowl / brick 多个策略选出，原引擎会把它们当作独立候选反复回测，
#    造成同股重复持仓。引入 merge_same_day_signals 后可按 (code, signal_date) 合并为一笔。
# 2) zettaranc 项目的 Priority 排序存在已知 bug：使用 .value 升序排时 OBSERVE(1) 会先于 CRITICAL(3)。
#    本项目采用显式的 PRIORITY_RANK / ACTION_RANK 字典，按"数值越小越优先"原则正向排序，杜绝该陷阱。
# 3) max_weight_per_code 用于在 weight_cap 组合模式下避免单只股票占用过多权重。

ACTION_RANK = {"SELL": 0, "BUY": 1, "WATCH": 2, "HOLD": 3}
PRIORITY_RANK = {"CRITICAL": 0, "OPPORTUNITY": 1, "OBSERVE": 2}

_BUY_KEYWORDS = ("b1", "b2", "bowl", "brick", "buy")
_SELL_KEYWORDS = ("s1", "s2", "s3", "sell", "exit")
_CRITICAL_KEYWORDS = ("s1", "s2", "s3", "critical", "stop", "exit")


def _classify_candidate(candidate: SignalCandidate) -> tuple[str, str]:
    """根据 strategy_name 启发式判定 action 与 priority。

    不修改候选自身，仅供合并时排序使用。无法识别时退化为 WATCH/OBSERVE。
    """
    name = (candidate.strategy_name or "").lower()
    action = "WATCH"
    for kw in _SELL_KEYWORDS:
        if kw in name:
            action = "SELL"
            break
    else:
        for kw in _BUY_KEYWORDS:
            if kw in name:
                action = "BUY"
                break
    priority = "OBSERVE"
    if any(kw in name for kw in _CRITICAL_KEYWORDS):
        priority = "CRITICAL"
    elif action == "BUY":
        priority = "OPPORTUNITY"
    return action, priority


def _priority_sort_key(candidate: SignalCandidate, priority_mode: str) -> tuple:
    action, priority = _classify_candidate(candidate)
    if priority_mode == "buy_first":
        return (0 if action == "BUY" else 1, ACTION_RANK.get(action, 9), PRIORITY_RANK.get(priority, 9), candidate.code)
    if priority_mode == "sell_first":
        return (0 if action == "SELL" else 1, ACTION_RANK.get(action, 9), PRIORITY_RANK.get(priority, 9), candidate.code)
    # critical_first 默认：先按 priority，再按 action，再按 code 稳定
    return (PRIORITY_RANK.get(priority, 9), ACTION_RANK.get(action, 9), candidate.code)


def merge_same_day_signals(
    candidates: Iterable[SignalCandidate],
    priority_mode: str = "critical_first",
) -> list[SignalCandidate]:
    """合并同股同日的多战法信号，按 priority_mode 选择代表性候选。

    返回顺序按 signal_date 升序、然后按 code 升序，保持回测可复现。
    """
    grouped: dict[tuple[str, str], list[SignalCandidate]] = defaultdict(list)
    for candidate in candidates:
        key = (candidate.code, candidate.signal_date or candidate.trade_date or "")
        grouped[key].append(candidate)
    merged: list[SignalCandidate] = []
    for items in grouped.values():
        # 显式比较函数避免 zettaranc 项目里 enum.value 升序导致 OBSERVE 被错选为首位的 bug
        items.sort(key=lambda c: _priority_sort_key(c, priority_mode))
        merged.append(items[0])
    merged.sort(key=lambda c: (c.signal_date or c.trade_date or "", c.code))
    return merged


def apply_max_weight_per_code(
    candidates: list[SignalCandidate],
    max_weight_pct: float,
    position_pct: float,
) -> tuple[list[SignalCandidate], int]:
    """按单股最大权重过滤候选。

    - max_weight_pct <= 0 时不限制；
    - position_pct 表示每笔交易占用的目标权重；
    - 当同一 code 累计权重超过 max_weight_pct 时丢弃多余信号。
    """
    if max_weight_pct <= 0 or position_pct <= 0:
        return candidates, 0
    accumulated: dict[str, float] = defaultdict(float)
    kept: list[SignalCandidate] = []
    dropped = 0
    for candidate in candidates:
        future = accumulated[candidate.code] + position_pct
        if future > max_weight_pct + 1e-9:
            dropped += 1
            continue
        accumulated[candidate.code] = future
        kept.append(candidate)
    return kept, dropped

