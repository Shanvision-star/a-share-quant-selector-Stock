"""P3 跟踪告警规则模板 REST 接口。

提供模板的 CRUD + 元信息查询。元信息端点 `/rules` 暴露引擎注册表，
前端可据此渲染"选择规则 + 编辑参数"表单。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from web.backend.services.tracking_rule_engine import DEFAULT_PARAMS, RULE_META
from web.backend.services.tracking_rule_templates import tracking_rule_template_service


router = APIRouter(prefix="/api/tracking/rule-templates", tags=["跟踪规则模板"])


class RuleTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    rule_id: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    note: str = ""


class RuleTemplateUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    rule_id: Optional[str] = None
    params: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    note: Optional[str] = None


@router.get("/rules")
async def list_rule_meta():
    """返回引擎注册表 + 默认参数，前端用作模板编辑器的下拉数据源。"""
    rules = []
    for rule_id, meta in RULE_META.items():
        rules.append(
            {
                "rule_id": rule_id,
                "name": meta.get("name", rule_id),
                "category": meta.get("category"),
                "priority": meta.get("priority"),
                "action_label": meta.get("action_label"),
                "default_params": DEFAULT_PARAMS.get(rule_id, {}),
            }
        )
    return {"success": True, "data": {"rules": rules}}


@router.get("")
async def list_templates(rule_id: Optional[str] = None, enabled_only: bool = False):
    items = tracking_rule_template_service.list(rule_id=rule_id, enabled_only=enabled_only)
    return {"success": True, "data": {"items": items}}


@router.post("")
async def create_template(payload: RuleTemplateCreateRequest):
    try:
        record = tracking_rule_template_service.create(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "data": record}


@router.get("/{template_id}")
async def get_template(template_id: str):
    record = tracking_rule_template_service.get(template_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return {"success": True, "data": record}


@router.put("/{template_id}")
async def update_template(template_id: str, payload: RuleTemplateUpdateRequest):
    changes = {k: v for k, v in payload.model_dump().items() if v is not None}
    try:
        record = tracking_rule_template_service.update(template_id, changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return {"success": True, "data": record}


@router.delete("/{template_id}")
async def delete_template(template_id: str):
    ok = tracking_rule_template_service.delete(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"模板不存在: {template_id}")
    return {"success": True, "data": {"deleted": True}}
