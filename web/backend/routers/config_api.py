"""配置管理接口"""
from fastapi import APIRouter, HTTPException
from web.backend.models.schemas import ConfigUpdateRequest

router = APIRouter(prefix="/api", tags=["配置管理"])


@router.get("/config")
async def get_config():
    """获取所有策略配置（含参数元数据用于旋钮渲染）"""
    from web.backend.services.strategy_service import get_strategies_config
    configs = get_strategies_config()
    return {"success": True, "data": configs}


@router.post("/config")
async def update_config(req: ConfigUpdateRequest):
    """更新策略配置"""
    from web.backend.services.strategy_service import update_strategy_config
    success = update_strategy_config(req.strategy_name, req.params)
    if not success:
        raise HTTPException(status_code=400, detail="更新失败")
    return {"success": True}
