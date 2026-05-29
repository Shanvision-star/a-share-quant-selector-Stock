"""回测接口。"""
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from web.backend.services.backtest_job_service import backtest_job_manager
from web.backend.services.backtest_service import run_backtest as run_backtest_service

router = APIRouter(prefix="/api", tags=["回测"])

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


class BacktestCandidate(BaseModel):
    code: str = Field(..., pattern=r"^\d{6}$")
    name: str = ''
    strategy_name: str = ''
    trade_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)
    signal_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)


class BacktestRequest(BaseModel):
    start_date: str = Field(..., pattern=DATE_PATTERN)
    end_date: str = Field(..., pattern=DATE_PATTERN)
    simulation_end_date: Optional[str] = Field(default=None, pattern=DATE_PATTERN)
    timeframe: Literal['daily', 'minute'] = 'daily'
    source: Literal['manual', 'strategy', 'codes'] = 'strategy'
    strategy: Literal['all', 'b1', 'b2', 'bowl', 'brick'] = 'all'
    selected_codes: list[str] = Field(default_factory=list)
    selected_candidates: list[BacktestCandidate] = Field(default_factory=list)
    input_codes: list[str] = Field(default_factory=list)
    holding_days: int = Field(default=5, ge=1, le=120)
    buy_offset_days: int = Field(default=1, ge=0, le=20)
    buy_price: Literal['open', 'close'] = 'open'
    sell_price: Literal['open', 'close'] = 'close'
    fee_rate: float = Field(default=0.0003, ge=0, le=0.02)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.02)
    take_profit_pct: Optional[float] = Field(default=0, ge=0, le=200)
    stop_loss_pct: Optional[float] = Field(default=0, ge=0, le=100)
    max_positions_per_day: int = Field(default=10, ge=0, le=500)
    max_candidates: int = Field(default=1000, ge=0, le=100000)
    max_signals_per_code: int = Field(default=120, ge=0, le=10000)
    max_runtime_seconds: float = Field(default=30, ge=0, le=600)
    codes_fallback_to_start_date: bool = False
    profit_run_enabled: bool = True
    profit_trigger_pct: float = Field(default=5, ge=0, le=200)
    profit_step_pct: float = Field(default=10, ge=0, le=200)
    profit_sell_pct: float = Field(default=25, ge=0, le=100)
    profit_keep_pct: float = Field(default=0, ge=0, le=100)
    hold_above_short_trend_after_trigger: bool = True
    enable_no_gain_exit: bool = True
    no_gain_days: int = Field(default=3, ge=1, le=30)
    exit_on_bull_bear_break: bool = True
    exit_on_short_trend_break: bool = True
    short_trend_break_days: int = Field(default=2, ge=1, le=20)
    exit_on_short_trend_drawdown: bool = True
    short_trend_drawdown_pct: float = Field(default=5, ge=0, le=50)
    minute_buy_time: str = Field(default='09:35', pattern=r"^\d{2}:\d{2}$")
    minute_sell_time: str = Field(default='14:55', pattern=r"^\d{2}:\d{2}$")
    minute_buy_price: Literal['open', 'close', 'high', 'low'] = 'open'
    minute_sell_price: Literal['open', 'close', 'high', 'low'] = 'close'
    intent_quantity: int = Field(default=0, ge=0, le=100000000)
    lot_size: int = Field(default=100, ge=1, le=10000)
    allow_st_buy: bool = False
    # 任务 C：组合策略 / 多战法融合参数。默认值保持旧行为，不影响现有调用方。
    signal_merge_mode: Literal['single', 'multi_strategy'] = 'single'
    signal_priority_mode: Literal['critical_first', 'buy_first', 'sell_first'] = 'critical_first'
    portfolio_mode: Literal['fixed_slots', 'weight_cap'] = 'fixed_slots'
    position_pct: float = Field(default=0, ge=0, le=100)
    max_weight_per_code: float = Field(default=0, ge=0, le=100)


def _payload_to_dict(payload: BacktestRequest) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


@router.post("/backtest")
async def run_backtest(payload: BacktestRequest):
    """同步回测：返回摘要、交易明细和资金曲线。"""
    if payload.start_date > payload.end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")
    result = await run_in_threadpool(run_backtest_service, _payload_to_dict(payload))
    return {"success": True, "data": result}


@router.post("/backtest/tasks")
async def submit_backtest_task(payload: BacktestRequest):
    """异步回测：立即返回 task_id，前端用查询接口轮询结果。"""
    if payload.start_date > payload.end_date:
        raise HTTPException(status_code=400, detail="start_date 不能晚于 end_date")
    task = backtest_job_manager.submit(_payload_to_dict(payload))
    return {"success": True, "data": task}


@router.get("/backtest/tasks")
async def list_backtest_tasks(limit: int = Query(default=20, ge=1, le=200)):
    """查询最近回测任务。"""
    return {"success": True, "data": {"items": backtest_job_manager.list_recent(limit)}}


@router.get("/backtest/tasks/{task_id}/events")
async def list_backtest_task_events(
    task_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
):
    """查询回测任务事件流，用于前端进度展示。"""
    task = backtest_job_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"回测任务不存在或已过期: {task_id}")
    return {"success": True, "data": {"items": backtest_job_manager.list_events(task_id, limit)}}


@router.post("/backtest/tasks/{task_id}/cancel")
async def cancel_backtest_task(task_id: str):
    """请求取消异步回测任务。"""
    task = backtest_job_manager.cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"回测任务不存在或已过期: {task_id}")
    return {"success": True, "data": task}


@router.get("/backtest/tasks/{task_id}")
async def get_backtest_task(task_id: str):
    """查询异步回测任务状态。"""
    task = backtest_job_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"回测任务不存在或已过期: {task_id}")
    return {"success": True, "data": task}


@router.get("/backtest/{task_id}")
async def get_backtest_result(task_id: str):
    """兼容旧路径的异步任务查询。"""
    task = backtest_job_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"回测任务不存在或已过期: {task_id}")
    return {"success": True, "data": task}
