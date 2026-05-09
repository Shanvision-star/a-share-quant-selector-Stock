"""backtest_lab 固定样本数据。

样本使用 1 只股票、1 个信号、20 个交易日，便于对比不同回测模型。
"""

from __future__ import annotations

import pandas as pd

from web.backend.backtest_engine.models import BacktestParams, SignalCandidate

SAMPLE_CODE = "000001"
SAMPLE_NAME = "平安银行"
SIGNAL_DATE = "2026-04-01"


def build_sample_frame() -> pd.DataFrame:
    """生成 20 个交易日的确定性 OHLCV 样本。"""
    dates = pd.bdate_range("2026-04-01", periods=20)
    closes = [
        10.00, 10.10, 10.25, 10.55, 10.76,
        10.82, 10.90, 10.70, 10.88, 11.02,
        11.10, 11.25, 11.18, 11.35, 11.42,
        11.55, 11.62, 11.50, 11.70, 11.88,
    ]
    rows = []
    for index, date in enumerate(dates):
        close = closes[index]
        open_price = round(close - 0.04, 2)
        rows.append(
            {
                "date": pd.Timestamp(date),
                "open": open_price,
                "high": round(close + 0.12, 2),
                "low": round(open_price - 0.10, 2),
                "close": close,
                "volume": 1_000_000 + index * 10_000,
            }
        )
    return pd.DataFrame(rows)


def build_sample_candidate() -> SignalCandidate:
    """生成唯一测试信号。"""
    return SignalCandidate(
        code=SAMPLE_CODE,
        name=SAMPLE_NAME,
        strategy_name="lab_signal",
        trade_date=SIGNAL_DATE,
        signal_date=SIGNAL_DATE,
        source="backtest_lab",
    )


def build_sample_params() -> BacktestParams:
    """生成与外部对比一致的回测参数。"""
    return BacktestParams.from_mapping(
        {
            "start_date": SIGNAL_DATE,
            "end_date": SIGNAL_DATE,
            "simulation_end_date": "2026-04-28",
            "holding_days": 3,
            "buy_offset_days": 1,
            "buy_price": "close",
            "sell_price": "close",
            "fee_rate": 0,
            "slippage_rate": 0,
            "take_profit_pct": 0,
            "stop_loss_pct": 0,
            "max_positions_per_day": 20,
            "profit_run_enabled": False,
            "enable_no_gain_exit": False,
            "exit_on_bull_bear_break": False,
            "exit_on_short_trend_break": False,
            "exit_on_short_trend_drawdown": False,
            "intent_quantity": 100,
        }
    )

