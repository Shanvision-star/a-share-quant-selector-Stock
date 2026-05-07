"""回测引擎包：把 Web 入参、信号、行情、执行、组合和分析拆成可替换模块。"""

from web.backend.backtest_engine.engine import BacktestEngine
from web.backend.backtest_engine.models import BacktestParams, MinuteBar, OrderIntent, SignalCandidate

__all__ = [
    "BacktestEngine",
    "BacktestParams",
    "MinuteBar",
    "OrderIntent",
    "SignalCandidate",
]
