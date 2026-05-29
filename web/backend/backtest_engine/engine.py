"""回测编排器。"""

from __future__ import annotations

from collections import defaultdict

from web.backend.backtest_engine.analyzer import build_result
from web.backend.backtest_engine.data_portal import DailyDataPortal, MinuteDataPortal
from web.backend.backtest_engine.execution import DailyExecutionSimulator, MinuteExecutionSimulator
from web.backend.backtest_engine.models import BacktestParams
from web.backend.backtest_engine.signal_source import (
    SignalSource,
    apply_max_weight_per_code,
    cap_positions_per_day,
    merge_same_day_signals,
)


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

    def run(self, params: BacktestParams, progress_callback=None) -> dict:
        if params.get("timeframe", "daily") == "minute":
            return self.run_minute(params, progress_callback=progress_callback)
        return self.run_daily(params, progress_callback=progress_callback)

    def run_daily(self, params: BacktestParams, progress_callback=None) -> dict:
        if self.daily_portal is None:
            raise ValueError("daily_portal is required for daily backtest")
        candidates, candidate_runtime = self._fetch_capped_candidates(params)
        trades, skipped, intents, execution_runtime = DailyExecutionSimulator(self.daily_portal).run(
            candidates,
            params,
            progress_callback=progress_callback,
        )
        return build_result(
            params=params,
            candidates=candidates,
            trades=trades,
            skipped=skipped,
            order_intents=intents,
            runtime=_merge_runtime(candidate_runtime, execution_runtime),
        )

    def run_minute(self, params: BacktestParams, progress_callback=None) -> dict:
        if self.minute_portal is None:
            raise ValueError("minute_portal is required for minute backtest")
        candidates, candidate_runtime = self._fetch_capped_candidates(params)
        trades, skipped, intents, execution_runtime = MinuteExecutionSimulator(self.minute_portal).run(
            candidates,
            params,
            progress_callback=progress_callback,
        )
        return build_result(
            params=params,
            candidates=candidates,
            trades=trades,
            skipped=skipped,
            order_intents=intents,
            runtime=_merge_runtime(candidate_runtime, execution_runtime),
        )

    def _fetch_capped_candidates(self, params: BacktestParams):
        candidates = self.signal_source.fetch(params)
        runtime = {
            "raw_candidate_count": len(candidates),
            "candidate_limit_applied": False,
            "warnings": [],
        }

        # 任务 C：多战法融合 —— 在限流前先按 (code, signal_date) 合并，避免同股同日被重复计费
        if str(params.get("signal_merge_mode") or "single") == "multi_strategy":
            before_merge = len(candidates)
            priority_mode = str(params.get("signal_priority_mode") or "critical_first")
            candidates = merge_same_day_signals(candidates, priority_mode=priority_mode)
            merged = before_merge - len(candidates)
            if merged > 0:
                runtime["warnings"].append(
                    f"多战法融合已合并 {merged} 条同股同日重复信号 (priority={priority_mode})"
                )
            runtime["signal_merge_mode"] = "multi_strategy"
            runtime["signal_priority_mode"] = priority_mode
        else:
            runtime["signal_merge_mode"] = "single"
            runtime["signal_priority_mode"] = "n/a"

        candidates = _limit_signals_per_code(candidates, int(params.get("max_signals_per_code", 0) or 0), runtime)

        before_day_cap = len(candidates)
        candidates = cap_positions_per_day(candidates, int(params.get("max_positions_per_day", 10)))
        if len(candidates) < before_day_cap:
            runtime["candidate_limit_applied"] = True
            runtime["warnings"].append(
                f"每日候选上限已触发，截断 {before_day_cap - len(candidates)} 条候选"
            )

        # 任务 C：weight_cap 组合模式下额外按单股最大权重过滤；fixed_slots 默认不动
        position_pct = float(params.get("position_pct") or 0)
        max_weight = float(params.get("max_weight_per_code") or 0)
        portfolio_mode = str(params.get("portfolio_mode") or "fixed_slots")
        if portfolio_mode == "weight_cap" and position_pct > 0 and max_weight > 0:
            candidates, dropped = apply_max_weight_per_code(candidates, max_weight, position_pct)
            if dropped > 0:
                runtime["candidate_limit_applied"] = True
                runtime["warnings"].append(
                    f"单股权重上限 {max_weight}% 已触发，丢弃 {dropped} 条候选"
                )
        runtime["portfolio_mode"] = portfolio_mode

        max_candidates = int(params.get("max_candidates", 0) or 0)
        if max_candidates > 0 and len(candidates) > max_candidates:
            truncated_count = len(candidates) - max_candidates
            candidates = candidates[:max_candidates]
            runtime["candidate_limit_applied"] = True
            runtime["warnings"].append(
                f"总候选上限 {max_candidates} 已触发，截断 {truncated_count} 条候选"
            )

        runtime["candidate_count"] = len(candidates)
        return candidates, runtime


def _limit_signals_per_code(candidates, max_signals_per_code: int, runtime: dict):
    if max_signals_per_code <= 0:
        return candidates
    kept = []
    counts: dict[str, int] = defaultdict(int)
    truncated_by_code: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        if counts[candidate.code] < max_signals_per_code:
            kept.append(candidate)
            counts[candidate.code] += 1
        else:
            truncated_by_code[candidate.code] += 1

    truncated_total = sum(truncated_by_code.values())
    if truncated_total:
        runtime["candidate_limit_applied"] = True
        runtime["warnings"].append(
            f"单股信号上限 {max_signals_per_code} 已触发，截断 {truncated_total} 条候选"
        )
    return kept


def _merge_runtime(candidate_runtime: dict, execution_runtime: dict) -> dict:
    warnings = []
    warnings.extend(candidate_runtime.get("warnings") or [])
    warnings.extend(execution_runtime.get("warnings") or [])
    return {
        **candidate_runtime,
        **execution_runtime,
        "warnings": warnings,
        "candidate_limit_applied": bool(candidate_runtime.get("candidate_limit_applied")),
    }
