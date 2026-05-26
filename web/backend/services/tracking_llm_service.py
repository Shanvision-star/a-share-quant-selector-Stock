"""P6 LLM 建议服务：确定性 mock 实现。

设计要点（参考 docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md 与 B2_STRATEGY.md）：
- 上线初期不接入真实 LLM，仅返回基于告警优先级和持仓状态的确定性建议；
- 输出结构对齐未来真实 LLM 接入：decision/confidence/rationale/suggested_action/suggested_intent；
- suggested_intent 预留给 P7 的 OrderIntent 流程（confirm/reject），此处不直接落库。

优先级阈值与 tracking_alert_service 一致：
- <30 必发 → 建议清仓 (cut / SELL)
- 30~60 → 建议减仓 (reduce / SELL 半仓)
- >=60 或无告警 → 持有/观望
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

# 与 tracking_alert_service 保持一致的阈值
_PRIORITY_MUST_SEND_BELOW = 30
_PRIORITY_AGGREGATE_AT_OR_ABOVE = 60


class TrackingLLMService:
    """确定性的 LLM 建议桩；后续可被真实 LLM 客户端替换。"""

    def propose_action(
        self,
        item: dict,
        alerts: list[dict],
        frame: Optional[pd.DataFrame] = None,
    ) -> dict[str, Any]:
        """根据持仓状态和告警优先级给出建议。

        Args:
            item: tracking_items 记录（含 status / code / name / current_qty 等）
            alerts: 最近告警列表，每项至少含 priority / rule_id / message
            frame: 行情 DataFrame（占位，mock 不使用，未来真实 LLM 会注入）

        Returns:
            标准建议结构（见模块 docstring）。
        """
        status = (item.get("status") or "").lower()
        code = item.get("code", "")
        current_qty = int(item.get("current_qty") or 0)

        # 提取最高优先级（数字越小越紧急）
        min_priority = None
        triggering_alert: dict | None = None
        for alert in alerts:
            try:
                prio = int(alert.get("priority", 100))
            except (TypeError, ValueError):
                continue
            if min_priority is None or prio < min_priority:
                min_priority = prio
                triggering_alert = alert

        # ---- 决策分支 ----
        if min_priority is not None and min_priority < _PRIORITY_MUST_SEND_BELOW:
            # 必发档：清仓
            rationale = (
                f"触发高优先级告警 {triggering_alert.get('rule_id') if triggering_alert else ''}"
                f"（priority={min_priority}），建议清仓避免进一步亏损。"
            )
            return {
                "decision": "cut",
                "confidence": 0.85,
                "rationale": rationale,
                "suggested_action": "SELL",
                "suggested_intent": {
                    "code": code,
                    "side": "SELL",
                    "qty_hint": current_qty,
                    "reason": "high_priority_alert",
                },
                "alerts_summary": {
                    "count": len(alerts),
                    "min_priority": min_priority,
                    "triggering_rule": triggering_alert.get("rule_id") if triggering_alert else None,
                },
            }

        if (
            min_priority is not None
            and min_priority < _PRIORITY_AGGREGATE_AT_OR_ABOVE
        ):
            # 中等档：减仓一半
            half_qty = max(0, current_qty // 2)
            rationale = (
                f"中等优先级告警 {triggering_alert.get('rule_id') if triggering_alert else ''}"
                f"（priority={min_priority}），建议先减仓一半观察后续走势。"
            )
            return {
                "decision": "reduce",
                "confidence": 0.65,
                "rationale": rationale,
                "suggested_action": "REDUCE",
                "suggested_intent": {
                    "code": code,
                    "side": "SELL",
                    "qty_hint": half_qty,
                    "reason": "mid_priority_alert",
                },
                "alerts_summary": {
                    "count": len(alerts),
                    "min_priority": min_priority,
                    "triggering_rule": triggering_alert.get("rule_id") if triggering_alert else None,
                },
            }

        # 无告警或仅聚合档：根据持仓状态返回观望/持有
        if status == "watch_buy":
            return {
                "decision": "watch",
                "confidence": 0.50,
                "rationale": "尚未建仓，无明显风险信号，继续观察买点。",
                "suggested_action": "WAIT",
                "suggested_intent": {
                    "code": code,
                    "side": "BUY",
                    "qty_hint": 0,
                    "reason": "awaiting_entry",
                },
                "alerts_summary": {"count": len(alerts), "min_priority": min_priority},
            }

        return {
            "decision": "hold",
            "confidence": 0.70,
            "rationale": "暂无高/中优先级告警，维持当前持仓。",
            "suggested_action": "HOLD",
            "suggested_intent": {
                "code": code,
                "side": "HOLD",
                "qty_hint": current_qty,
                "reason": "no_alerts",
            },
            "alerts_summary": {"count": len(alerts), "min_priority": min_priority},
        }


# 模块级单例，供路由/编排层引用；测试可通过 monkeypatch 替换。
tracking_llm_service = TrackingLLMService()
