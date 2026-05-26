"""P6 LLM 建议 REST 接口。

POST /api/tracking/{tracking_id}/llm-advice
- 加载 tracking_items + 最近告警，调用 tracking_llm_service.propose_action
- 返回包含 decision/confidence/rationale/suggested_action/suggested_intent 的建议
- 未找到 tracking_id 时返回 404
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from web.backend.services.tracking_alert_service import tracking_alert_service
from web.backend.services.tracking_llm_service import tracking_llm_service
from web.backend.services.tracking_service import tracking_service


router = APIRouter(prefix="/api/tracking", tags=["跟踪 LLM 建议"])


@router.post("/{tracking_id}/llm-advice")
async def get_llm_advice(tracking_id: str):
    """对指定跟踪项给出 LLM 行为建议（当前为确定性 mock）。"""
    item = tracking_service.get_item(tracking_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"tracking_id 不存在: {tracking_id}")

    # 最近告警，按优先级排序限定 20 条，作为 LLM 判定的主要输入
    alerts = tracking_alert_service.list_alerts(tracking_id=tracking_id, limit=20)

    # frame 暂传 None；未来接入真实 LLM 可在此加载日线 + 指标
    advice = tracking_llm_service.propose_action(item, alerts, frame=None)
    advice["tracking_id"] = tracking_id
    return {"success": True, "data": advice}
