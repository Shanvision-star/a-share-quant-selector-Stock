"""回测引擎数据结构。

这些结构只描述回测内部边界，不直接绑定 FastAPI、数据库或券商接口。
实盘接入时也应先生成 OrderIntent，再由独立执行适配器决定是否发送到 QMT。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from uuid import uuid4

import pandas as pd


def _format_timestamp(value: Any) -> str:
    ts = pd.to_datetime(value)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class SignalCandidate:
    """策略或人工池产出的单个候选信号。"""

    code: str
    name: str = ""
    strategy_name: str = ""
    trade_date: str = ""
    signal_date: str = ""
    source: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "SignalCandidate":
        signal_date = str(data.get("signal_date") or data.get("trade_date") or "")
        return cls(
            code=str(data.get("code") or ""),
            name=str(data.get("name") or ""),
            strategy_name=str(data.get("strategy_name") or ""),
            trade_date=str(data.get("trade_date") or signal_date),
            signal_date=signal_date,
            source=str(data.get("source") or ""),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "strategy_name": self.strategy_name,
            "trade_date": self.trade_date,
            "signal_date": self.signal_date,
            "source": self.source,
        }


@dataclass(frozen=True)
class BacktestParams:
    """回测参数只做轻量封装，保持旧 API 的 dict 入参兼容。"""

    values: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "BacktestParams":
        return cls(dict(data))

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def to_mapping(self) -> dict[str, Any]:
        return dict(self.values)


@dataclass(frozen=True)
class MinuteBar:
    """1 分钟 K 线结构，用于分钟级回测和后续分时买点验证。"""

    code: str
    timestamp: Any
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    amount: float = 0.0

    @property
    def ts(self) -> pd.Timestamp:
        return pd.to_datetime(self.timestamp)

    @classmethod
    def from_mapping(cls, code: str, data: Mapping[str, Any]) -> "MinuteBar":
        timestamp = data.get("timestamp") or data.get("datetime") or data.get("time")
        if timestamp is None and data.get("date") and data.get("minute"):
            timestamp = f"{data.get('date')} {data.get('minute')}"
        return cls(
            code=code,
            timestamp=timestamp,
            open=float(data.get("open") or 0),
            high=float(data.get("high") or 0),
            low=float(data.get("low") or 0),
            close=float(data.get("close") or 0),
            volume=int(float(data.get("volume") or 0)),
            amount=float(data.get("amount") or 0),
        )

    def price(self, field_name: str) -> float:
        if field_name not in {"open", "high", "low", "close"}:
            field_name = "close"
        return float(getattr(self, field_name))


@dataclass(frozen=True)
class OrderIntent:
    """下单意图。

    OrderIntent 是“准备下单”的结构化记录，不等于实盘订单。
    broker_order_id 必须由券商适配器回填，回测引擎永远不直接写入。
    """

    code: str
    side: str
    planned_at: Any
    strategy_name: str = ""
    signal_date: str = ""
    source: str = ""
    price_type: str = "market"
    target_price: Optional[float] = None
    quantity: int = 0
    execution_mode: str = "backtest"
    status: str = "generated"
    broker_order_id: Optional[str] = None
    intent_id: str = field(default_factory=lambda: f"oi_{uuid4().hex[:12]}")

    @classmethod
    def from_candidate(
        cls,
        candidate: SignalCandidate,
        *,
        side: str,
        planned_at: Any,
        price_type: str,
        target_price: Optional[float],
        quantity: int = 0,
    ) -> "OrderIntent":
        return cls(
            code=candidate.code,
            side=side,
            planned_at=planned_at,
            strategy_name=candidate.strategy_name,
            signal_date=candidate.signal_date,
            source=candidate.source,
            price_type=price_type,
            target_price=target_price,
            quantity=quantity,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "code": self.code,
            "side": self.side,
            "planned_at": _format_timestamp(self.planned_at),
            "strategy_name": self.strategy_name,
            "signal_date": self.signal_date,
            "source": self.source,
            "price_type": self.price_type,
            "target_price": round(float(self.target_price), 3) if self.target_price is not None else None,
            "quantity": self.quantity,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "broker_order_id": self.broker_order_id,
        }
