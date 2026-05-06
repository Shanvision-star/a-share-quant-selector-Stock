"""配置管理接口"""
from fastapi import APIRouter, HTTPException
from web.backend.models.schemas import ConfigUpdateRequest

router = APIRouter(prefix="/api", tags=["配置管理"])

_FORBIDDEN_CONFIG_KEYS = {
    "data_dir",
    "dingtalk",
    "dingtalk.secret",
    "dingtalk.webhook_url",
}


def _normalize_config_key(key: str) -> str:
    return str(key).strip().lower()


def _assert_safe_config_update(req: ConfigUpdateRequest) -> None:
    blocked_keys = []
    for key in req.params:
        normalized_key = _normalize_config_key(key)
        if normalized_key in _FORBIDDEN_CONFIG_KEYS or normalized_key.startswith("dingtalk."):
            blocked_keys.append(str(key))

    if blocked_keys:
        blocked_text = ", ".join(sorted(blocked_keys))
        raise HTTPException(status_code=422, detail=f"禁止写入配置项: {blocked_text}")


@router.get("/config")
async def get_config():
    """获取所有策略配置（含参数元数据用于旋钮渲染）"""
    from web.backend.services.strategy_service import get_strategies_config
    return get_strategies_config()


@router.post("/config")
async def update_config(req: ConfigUpdateRequest):
    """更新策略配置"""
    _assert_safe_config_update(req)
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
