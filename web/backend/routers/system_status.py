"""系统状态中心接口。"""

from fastapi import APIRouter

from web.backend.services.system_status_service import system_status_service


router = APIRouter(prefix="/api", tags=["系统状态"])


@router.get("/system/status")
def get_system_status():
    """返回只读系统状态聚合结果。"""
    # CSV/SQLite 聚合是同步 I/O，不能占住 SSE 和 Agent 共用的事件循环。
    return {"success": True, "data": system_status_service.build_status()}
