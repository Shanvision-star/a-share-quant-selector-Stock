"""P6 LLM 建议 REST 接口。

POST /api/tracking/{tracking_id}/llm-advice
- 加载 tracking_items + 最近告警，调用 tracking_llm_service.propose_action
- 返回包含 decision/confidence/rationale/suggested_action/suggested_intent 的建议
- 未找到 tracking_id 时返回 404
- 任务 D：支持 profile 字段（default | zettaranc_style），只切口吻不改 schema
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException

from web.backend.services.tracking_alert_service import tracking_alert_service
from web.backend.services.tracking_llm_service import tracking_llm_service
from web.backend.services.tracking_service import tracking_service


router = APIRouter(prefix="/api/tracking", tags=["跟踪 LLM 建议"])
logger = logging.getLogger(__name__)


@router.post("/{tracking_id}/llm-advice")
async def get_llm_advice(
    tracking_id: str,
    payload: Optional[dict] = Body(default=None),
):
    """对指定跟踪项给出 LLM 行为建议（mock/deepseek）。

    payload 可选字段：
    - profile: default | zettaranc_style
    """
    item = tracking_service.get_item(tracking_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"tracking_id 不存在: {tracking_id}")

    alerts = tracking_alert_service.list_alerts(tracking_id=tracking_id, limit=20)
    profile = None
    if isinstance(payload, dict):
        profile = payload.get("profile")

    advice = tracking_llm_service.propose_action(item, alerts, frame=None, profile=profile)
    advice.setdefault("provider", "mock")
    advice.setdefault("provider_fallback", False)
    advice.setdefault("profile", "default")
    mismatch = advice.get("llm_mismatch")
    if isinstance(mismatch, dict) and mismatch:
        try:
            tracking_service.add_event(
                tracking_id=tracking_id,
                event_type="llm_mismatch",
                event_date=item.get("last_eval_date"),
                action=str(advice.get("suggested_action") or "RULE"),
                message="LLM/Zettaranc 建议与规则告警冲突，已按规则引擎覆盖。",
                payload={
                    "mismatch": mismatch,
                    "profile": advice.get("profile"),
                    "provider": advice.get("provider"),
                    "rule_action_label": advice.get("rule_action_label"),
                },
            )
        except Exception as exc:  # pragma: no cover - 审计失败不能阻断用户查看建议
            logger.warning("[tracking_llm] llm_mismatch 审计事件写入失败: %s", exc)
            advice["llm_mismatch_event_error"] = str(exc)
    advice["tracking_id"] = tracking_id
    return {"success": True, "data": advice}
