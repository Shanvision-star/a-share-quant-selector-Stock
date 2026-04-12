"""回测接口（预留）"""
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["回测"])


@router.post("/backtest")
async def run_backtest():
    """回测接口 — 预留，返回 501"""
    raise HTTPException(status_code=501, detail="回测功能即将上线")


@router.get("/backtest/{task_id}")
async def get_backtest_result(task_id: str):
    """查询回测任务 — 预留，返回 501"""
    raise HTTPException(status_code=501, detail="回测功能即将上线")
