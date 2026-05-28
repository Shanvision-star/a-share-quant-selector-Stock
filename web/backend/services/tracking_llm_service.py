"""P6 LLM 建议服务：支持 mock / DeepSeek 双 provider。

设计要点（参考 docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md 与 B2_STRATEGY.md）：
- 上层接口 `propose_action` 输出结构稳定不变，供路由与编排层依赖；
- provider 由 config/llm.yaml 控制：mock（确定性桩）/ deepseek（线上）；
- DeepSeek 调用任何异常都会回退到 mock，并在返回结果中添加 `provider` 与
  `provider_fallback` 字段，便于前端/日志区分；
- suggested_intent 预留给 P7 的 OrderIntent 流程，此处不直接落库。

mock 决策阈值（与 tracking_alert_service 一致）：
- <30 必发 → 建议清仓 (cut / SELL)
- 30~60 → 建议减仓 (reduce / SELL 半仓)
- >=60 或无告警 → 持有/观望
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import pandas as pd

from .llm_providers import call_deepseek, load_llm_config
from .llm_providers.deepseek_provider import DeepSeekError

logger = logging.getLogger(__name__)

# 与 tracking_alert_service 保持一致的阈值
_PRIORITY_MUST_SEND_BELOW = 30
_PRIORITY_AGGREGATE_AT_OR_ABOVE = 60

_ALLOWED_DECISIONS = {"cut", "reduce", "hold", "watch", "add"}
_ALLOWED_ACTIONS = {"SELL", "REDUCE", "HOLD", "WAIT", "BUY"}


def _extract_min_priority(alerts: list[dict]) -> tuple[Optional[int], Optional[dict]]:
    """提取告警列表中最紧急（priority 数值最小）的一条。"""
    min_priority: Optional[int] = None
    triggering_alert: Optional[dict] = None
    for alert in alerts:
        try:
            prio = int(alert.get("priority", 100))
        except (TypeError, ValueError):
            continue
        if min_priority is None or prio < min_priority:
            min_priority = prio
            triggering_alert = alert
    return min_priority, triggering_alert


def _propose_mock(item: dict, alerts: list[dict]) -> dict[str, Any]:
    """确定性桩：在没有真实 LLM 或 LLM 失败时使用。"""
    status = (item.get("status") or "").lower()
    code = item.get("code", "")
    current_qty = int(item.get("current_qty") or 0)

    min_priority, triggering_alert = _extract_min_priority(alerts)
    triggering_rule = (
        triggering_alert.get("rule_id") if triggering_alert else None
    )

    if min_priority is not None and min_priority < _PRIORITY_MUST_SEND_BELOW:
        rationale = (
            f"触发高优先级告警 {triggering_rule or ''}"
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
                "triggering_rule": triggering_rule,
            },
        }

    if (
        min_priority is not None
        and min_priority < _PRIORITY_AGGREGATE_AT_OR_ABOVE
    ):
        half_qty = max(0, current_qty // 2)
        rationale = (
            f"中等优先级告警 {triggering_rule or ''}"
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
                "triggering_rule": triggering_rule,
            },
        }

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


_SYSTEM_PROMPT = (
    "你是 A 股短线持仓助理。基于持仓状态与最近告警列表，给出极简交易建议。"
    "必须返回严格 JSON 对象，字段如下：\n"
    "- decision: 字符串，取值 cut|reduce|hold|watch|add\n"
    "- confidence: 0~1 浮点\n"
    "- rationale: 简体中文一句话（<=80 字）解释依据\n"
    "- suggested_action: 字符串，取值 SELL|REDUCE|HOLD|WAIT|BUY\n"
    "- suggested_intent: 对象，含 code/side/qty_hint/reason\n"
    "规则：priority<30 必清仓 (cut/SELL)；30~60 减仓一半 (reduce/REDUCE)；"
    "无告警时根据 status 选 watch 或 hold。"
)


def _build_user_prompt(item: dict, alerts: list[dict]) -> str:
    """组装 DeepSeek 的 user message，只暴露必要字段，避免上下文膨胀。"""
    item_view = {
        "code": item.get("code"),
        "name": item.get("name"),
        "status": item.get("status"),
        "strategy_name": item.get("strategy_name"),
        "signal_date": item.get("signal_date"),
        "entry_date": item.get("entry_date"),
        "entry_price": item.get("entry_price"),
        "latest_return_pct": item.get("latest_return_pct"),
        "current_qty": item.get("current_qty"),
        "remaining_pct": item.get("remaining_pct"),
        "next_action": item.get("next_action"),
    }
    alert_view = [
        {
            "rule_id": a.get("rule_id"),
            "priority": a.get("priority"),
            "message": a.get("message"),
            "ts": a.get("ts") or a.get("created_at"),
        }
        for a in alerts[:20]
    ]
    return (
        "持仓:\n"
        + json.dumps(item_view, ensure_ascii=False)
        + "\n告警(最多20条):\n"
        + json.dumps(alert_view, ensure_ascii=False)
        + "\n请按系统提示输出严格 JSON。"
    )


def _normalize_deepseek_payload(raw: dict, item: dict, alerts: list[dict]) -> dict[str, Any]:
    """把 DeepSeek 返回的 JSON 规整成标准建议结构；非法字段抛 ValueError。"""
    decision = str(raw.get("decision", "")).lower()
    if decision not in _ALLOWED_DECISIONS:
        raise ValueError(f"非法 decision: {decision!r}")

    action = str(raw.get("suggested_action", "")).upper()
    if action not in _ALLOWED_ACTIONS:
        raise ValueError(f"非法 suggested_action: {action!r}")

    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    rationale = str(raw.get("rationale") or "").strip() or "（无）"

    intent_raw = raw.get("suggested_intent") or {}
    if not isinstance(intent_raw, dict):
        intent_raw = {}
    suggested_intent = {
        "code": str(intent_raw.get("code") or item.get("code") or ""),
        "side": str(intent_raw.get("side") or action).upper(),
        "qty_hint": int(intent_raw.get("qty_hint") or 0),
        "reason": str(intent_raw.get("reason") or "llm_advice"),
    }

    min_priority, triggering_alert = _extract_min_priority(alerts)
    return {
        "decision": decision,
        "confidence": confidence,
        "rationale": rationale,
        "suggested_action": action,
        "suggested_intent": suggested_intent,
        "alerts_summary": {
            "count": len(alerts),
            "min_priority": min_priority,
            "triggering_rule": (
                triggering_alert.get("rule_id") if triggering_alert else None
            ),
        },
    }


class TrackingLLMService:
    """LLM 建议服务：支持 provider 切换。"""

    def propose_action(
        self,
        item: dict,
        alerts: list[dict],
        frame: Optional[pd.DataFrame] = None,
    ) -> dict[str, Any]:
        """根据持仓 + 告警给出建议，输出结构稳定。

        - provider=mock：直接走确定性桩；
        - provider=deepseek：调用线上接口，异常时回退 mock 并标记 fallback。

        Args:
            item: tracking_items 记录
            alerts: 最近告警列表
            frame: 行情 DataFrame（占位）

        Returns:
            标准建议结构，附 provider/provider_fallback 字段。
        """
        cfg = load_llm_config()
        provider = str(cfg.get("provider") or "mock").lower()

        if provider == "deepseek":
            ds_cfg = cfg.get("deepseek") or {}
            try:
                raw = call_deepseek(
                    api_key=str(ds_cfg.get("api_key") or ""),
                    base_url=str(ds_cfg.get("base_url") or "https://api.deepseek.com/v1"),
                    model=str(ds_cfg.get("model") or "deepseek-chat"),
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=_build_user_prompt(item, alerts),
                    temperature=float(ds_cfg.get("temperature", 0.2)),
                    timeout_seconds=float(ds_cfg.get("timeout_seconds", 20)),
                    max_output_tokens=int(ds_cfg.get("max_output_tokens", 600)),
                )
                normalized = _normalize_deepseek_payload(raw, item, alerts)
                normalized["provider"] = "deepseek"
                normalized["provider_fallback"] = False
                return normalized
            except (DeepSeekError, ValueError) as exc:
                # 关键路径：网络/响应异常都不应阻塞 P6 评估
                logger.warning(
                    "[tracking_llm] DeepSeek 调用失败，回退 mock: %s", exc
                )
                fallback = _propose_mock(item, alerts)
                fallback["provider"] = "mock"
                fallback["provider_fallback"] = True
                fallback["provider_error"] = str(exc)
                return fallback

        # 默认 mock 分支
        out = _propose_mock(item, alerts)
        out["provider"] = "mock"
        out["provider_fallback"] = False
        return out


# 模块级单例，供路由/编排层引用；测试可通过 monkeypatch 替换。
tracking_llm_service = TrackingLLMService()
