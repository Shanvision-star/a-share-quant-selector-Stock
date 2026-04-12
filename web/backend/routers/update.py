"""数据更新接口"""
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
import json

router = APIRouter(prefix="/api", tags=["数据更新"])


@router.post("/update")
async def trigger_update():
    """触发数据更新（SSE 流式返回进度）"""
    from web.backend.services.data_service import run_data_update

    async def event_generator():
        async for msg in run_data_update():
            yield {"event": msg["event"], "data": json.dumps(msg["data"], ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.get("/data/status")
async def get_data_status():
    """获取数据新鲜度报告"""
    from web.backend.services.data_service import get_data_status
    status = get_data_status()
    return {"success": True, "data": status}
