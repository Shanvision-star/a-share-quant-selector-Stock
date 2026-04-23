"""配置管理接口"""
from fastapi import APIRouter, HTTPException
from web.backend.models.schemas import ConfigUpdateRequest

router = APIRouter(prefix="/api", tags=["配置管理"])


@router.get("/config")
async def get_config():
    """获取所有策略配置（含参数元数据用于旋钮渲染）"""
    from web.backend.services.strategy_service import get_strategies_config
    return get_strategies_config()


@router.post("/config")
async def update_config(req: ConfigUpdateRequest):
    """更新策略配置"""
    from web.backend.services.strategy_service import ConfigRefreshError, update_strategy_config
    try:
        success, revision = update_strategy_config(req.strategy_name, req.params, req.expected_revision)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConfigRefreshError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=409, detail="配置版本冲突，请刷新后重试")
    return {"success": True, "data": {"revision": revision}}
