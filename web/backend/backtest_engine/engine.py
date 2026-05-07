"""回测编排器。"""

from __future__ import annotations

from web.backend.backtest_engine.analyzer import build_result
from web.backend.backtest_engine.data_portal import DailyDataPortal, MinuteDataPortal
from web.backend.backtest_engine.execution import DailyExecutionSimulator, MinuteExecutionSimulator
from web.backend.backtest_engine.models import BacktestParams
from web.backend.backtest_engine.signal_source import SignalSource, cap_positions_per_day


class BacktestEngine:
    """组合信号源、行情源和执行器，保持 API 层之外的回测核心稳定。"""

    def __init__(
        self,
        *,
        signal_source: SignalSource,
        daily_portal: DailyDataPortal | None = None,
        minute_portal: MinuteDataPortal | None = None,
    ):
        self.signal_source = signal_source
        self.daily_portal = daily_portal
        self.minute_portal = minute_portal

    def run(self, params: BacktestParams) -> dict:
        if params.get("timeframe", "daily") == "minute":
            return self.run_minute(params)
        return self.run_daily(params)

    def run_daily(self, params: BacktestParams) -> dict:
        if self.daily_portal is None:
            raise ValueError("daily_portal is required for daily backtest")
        candidates = self._fetch_capped_candidates(params)
        trades, skipped, intents = DailyExecutionSimulator(self.daily_portal).run(candidates, params)
        return build_result(
            params=params,
            candidates=candidates,
            trades=trades,
            skipped=skipped,
            order_intents=intents,
        )

    def run_minute(self, params: BacktestParams) -> dict:
        if self.minute_portal is None:
            raise ValueError("minute_portal is required for minute backtest")
        candidates = self._fetch_capped_candidates(params)
        trades, skipped, intents = MinuteExecutionSimulator(self.minute_portal).run(candidates, params)
        return build_result(
            params=params,
            candidates=candidates,
            trades=trades,
            skipped=skipped,
            order_intents=intents,
        )

    def _fetch_capped_candidates(self, params: BacktestParams):
        candidates = self.signal_source.fetch(params)
        return cap_positions_per_day(candidates, int(params.get("max_positions_per_day", 10)))
