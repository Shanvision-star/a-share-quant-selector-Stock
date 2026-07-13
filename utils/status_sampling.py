"""为状态页提供稳定、均匀且无副作用的抽样规则。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar


T = TypeVar("T")


def select_status_sample(items: Sequence[T], sample_size: int = 10) -> list[T]:
    """按排序后等距索引采样，确保相同输入每次得到相同结果。"""
    ordered = sorted(items)
    if len(ordered) <= sample_size:
        return ordered
    if sample_size <= 1:
        return [ordered[0]]

    last_index = len(ordered) - 1
    indexes = [int(index * last_index / (sample_size - 1)) for index in range(sample_size)]
    return [ordered[index] for index in indexes]
