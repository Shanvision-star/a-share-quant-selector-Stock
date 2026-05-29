"""任务 D：通用诊断接口（不依赖具体 tracking_id）。

POST /api/tracking-llm/diagnose-stock
- 用于股票详情页"诊断视角"面板
- 调用方传入 code/价格/信号/告警，服务端拼成 pseudo tracking item 后复用 propose_action
- 与 /api/tracking/{id}/llm-advice 共用同一份 LLM schema 与 mock/deepseek 回退
- profile: default | zettaranc_style
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from web.backend.services.tracking_llm_service import tracking_llm_service


router = APIRouter(prefix="/api/tracking-llm", tags=["跟踪 LLM 建议"])


class DiagnoseStockPayload(BaseModel):
    """诊断输入：除 code 外其余皆可选，给出多少分析多少。"""

    code: str = Field(..., description="股票代码")
    profile: Optional[str] = Field(default=None, description="default | zettaranc_style")
    signals: Optional[list[dict[str, Any]]] = None
    price_info: Optional[dict[str, Any]] = None
    alerts: Optional[list[dict[str, Any]]] = None
    tracking_item: Optional[dict[str, Any]] = None


@router.post("/diagnose-stock")
async def diagnose_stock(payload: DiagnoseStockPayload):
    """根据传入上下文给出"分析建议"。

    重要约定：本接口只负责生成建议，不写库不下单；前端必须在 UI 上明确标注
    "分析建议，非自动交易"。
    """
    # 构造 pseudo tracking item，缺省字段统一回退，保证 propose_action 不踩 KeyError
    pseudo_item: dict[str, Any] = {
        "code": payload.code,
        "tracking_id": f"diagnose:{payload.code}",
        "status": "diagnose",
        "entry_price": None,
        "current_price": None,
        "position_pct": 0.0,
    }
    if payload.tracking_item:
        pseudo_item.update(payload.tracking_item)
        pseudo_item["code"] = payload.code  # code 以 payload 为准
    if payload.price_info:
        # 兼容前端可能传 last/close/current 三种命名
        for key in ("current_price", "last_price", "close", "entry_price"):
            value = payload.price_info.get(key)
            if value is not None and pseudo_item.get(key) in (None, 0):
                pseudo_item[key] = value
    if payload.signals:
        pseudo_item["signals"] = payload.signals

    alerts = payload.alerts or []

    advice = tracking_llm_service.propose_action(
        pseudo_item,
        alerts,
        frame=None,
        profile=payload.profile,
    )
    advice["code"] = payload.code
    advice["diagnose"] = True
    return {"success": True, "data": advice}
