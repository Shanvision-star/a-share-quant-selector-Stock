"""信号入口。

Web 层可以继续从人工选股池或策略结果库查询候选，回测引擎只依赖
SignalSource 协议，因此后续可替换成文件、数据库、消息队列或 QMT 观察列表。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Protocol

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
