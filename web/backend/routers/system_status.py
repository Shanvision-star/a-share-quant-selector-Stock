"""系统状态中心接口。"""

from fastapi import APIRouter

from web.backend.services.system_status_service import system_status_service


router = APIRouter(prefix="/api", tags=["系统状态"])


@router.get("/system/status")
async def get_system_status():
    """返回只读系统状态聚合结果。"""
    return {"success": True, "data": system_status_service.build_status()}
