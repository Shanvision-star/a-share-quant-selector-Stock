"""数据更新接口"""
from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse
import json

router = APIRouter(prefix="/api", tags=["数据更新"])


@router.post("/update")
async def trigger_update(
    auto_rebuild: bool = Query(True),
    date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    pipeline: bool = Query(False),
):
    """触发数据更新（SSE 流式返回进度）
    auto_rebuild=True 时，更新完成后自动执行全策略缓存重建
    pipeline=True 时，更新阶段即内联执行策略扫描并实时推送命中结果
    """
    from web.backend.services.data_service import run_data_update

    async def event_generator():
        async for msg in run_data_update(auto_rebuild=auto_rebuild, target_date=date, pipeline=pipeline):
            yield {"event": msg["event"], "data": json.dumps(msg["data"], ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.get("/data/status")
async def get_data_status():
    """获取数据新鲜度报告"""
    from web.backend.services.data_service import get_data_status
    status = get_data_status()
    return {"success": True, "data": status}
