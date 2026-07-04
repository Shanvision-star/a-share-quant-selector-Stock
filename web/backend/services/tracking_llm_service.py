"""P6 LLM 建议服务：支持 mock / DeepSeek / Codex CLI provider。

设计要点（参考 docs/PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md 与 B2_STRATEGY.md）：
- 上层接口 `propose_action` 输出结构稳定不变，供路由与编排层依赖；
- provider 由 config/llm.yaml 控制：mock（确定性桩）/ deepseek（线上）/ codex_cli（本地 smoke）；
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

from .llm_providers import CodexCLIError, call_codex_cli, call_deepseek, load_llm_config
from .llm_providers.deepseek_provider import DeepSeekError
from . import zettaranc_adapter

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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rule_authority_from_alert(item: dict, alert: Optional[dict]) -> Optional[dict[str, Any]]:
    """把规则告警转换成 advice 可执行边界，避免 provider 覆盖规则权威。"""
    if not alert:
        return None

    action_label = str(alert.get("action_label") or "").strip().upper()
    try:
        priority = int(alert.get("priority", 100))
    except (TypeError, ValueError):
        priority = 100

    current_qty = max(0, _safe_int(item.get("current_qty") or item.get("quantity"), 0))
    half_qty = max(0, current_qty // 2)
    if action_label == "STOP_LOSS":
        decision, suggested_action, intent_side, qty_hint = "cut", "SELL", "SELL", current_qty
    elif action_label == "SELL_PARTIAL":
        decision, suggested_action, intent_side, qty_hint = "reduce", "REDUCE", "SELL", half_qty
    elif action_label == "WAIT_BUY":
        decision, suggested_action, intent_side, qty_hint = "watch", "WAIT", "BUY", 0
    elif action_label == "BUY_READY":
        decision, suggested_action, intent_side, qty_hint = "add", "BUY", "BUY", 0
    elif action_label == "HOLD":
        decision, suggested_action, intent_side, qty_hint = "hold", "HOLD", "HOLD", current_qty
    elif action_label == "TREND_BREAK" and priority < _PRIORITY_MUST_SEND_BELOW:
        decision, suggested_action, intent_side, qty_hint = "cut", "SELL", "SELL", current_qty
    elif action_label == "TREND_BREAK":
        decision, suggested_action, intent_side, qty_hint = "reduce", "REDUCE", "SELL", half_qty
    elif priority < _PRIORITY_MUST_SEND_BELOW:
        decision, suggested_action, intent_side, qty_hint = "cut", "SELL", "SELL", current_qty
    elif priority < _PRIORITY_AGGREGATE_AT_OR_ABOVE:
        decision, suggested_action, intent_side, qty_hint = "reduce", "REDUCE", "SELL", half_qty
    else:
        decision, suggested_action, intent_side, qty_hint = "hold", "HOLD", "HOLD", current_qty

    return {
        "action_label": action_label or None,
        "priority": priority,
        "decision": decision,
        "suggested_action": suggested_action,
        "intent_side": intent_side,
        "qty_hint": qty_hint,
    }


def _apply_rule_authority(
    result: dict[str, Any],
    item: dict,
    triggering_alert: Optional[dict],
) -> dict[str, Any]:
    """规则告警与 provider advice 冲突时，以规则为准并保留审计证据。"""
    authority = _rule_authority_from_alert(item, triggering_alert)
    if not authority:
        result["authority"] = "advice"
        return result

    result["authority"] = "rule_engine"
    result["rule_action_label"] = authority["action_label"]
    result["alerts_summary"]["triggering_action_label"] = authority["action_label"]

    original_action = str(result.get("suggested_action") or "").upper()
    intent = dict(result.get("suggested_intent") or {})
    original_side = str(intent.get("side") or "").upper()
    expected_action = str(authority["suggested_action"])
    expected_side = str(authority["intent_side"])
    if original_action == expected_action and original_side == expected_side:
        return result

    result["llm_mismatch"] = {
        "rule_action_label": authority["action_label"],
        "rule_priority": authority["priority"],
        "expected_suggested_action": expected_action,
        "expected_intent_side": expected_side,
        "original_suggested_action": original_action,
        "original_intent_side": original_side,
    }
    result["decision"] = authority["decision"]
    result["suggested_action"] = expected_action
    intent["code"] = str(intent.get("code") or item.get("code") or "")
    intent["side"] = expected_side
    if _safe_int(intent.get("qty_hint"), 0) <= 0 and _safe_int(authority.get("qty_hint"), 0) > 0:
        intent["qty_hint"] = int(authority["qty_hint"])
    intent["reason"] = f"rule_authority:{authority['action_label'] or 'priority'}"
    result["suggested_intent"] = intent
    result["rationale"] = (
        f"规则引擎 {authority['action_label'] or authority['priority']} 为权威，已覆盖模型建议。"
        + str(result.get("rationale") or "")
    )
    return result


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

# 任务 D：zettaranc 风格系统提示词。只换口吻不改 schema，不引入 zettaranc 的 Tushare/SQLite 依赖。
# 口吻参考：A 股手游操盘手、止损优先、杀伐果断、不绕弯；输出仍为严格 JSON。
_SYSTEM_PROMPT_ZETTARANC_FALLBACK = (
    "你是一位崩盘阅历丰富的 A 股手游操盘手，不讲情怀只讲纪律：止损优先、杀伐果断、不绕弯。"
    "面对持仓与告警时，你的金句是：「见坏就走，别依赖反弹」、「什么是仓位？仓位是阳光，不是赔钱的抽屉」。"
    "必须返回严格 JSON 对象，字段同默认提示词：decision/confidence/rationale/suggested_action/suggested_intent。"
    "rationale 请用“拍桌式”中文，一句话说清「为什么买/为什么跳/为什么耔」，<=80 字。"
    "低优先级告警 (priority<30) 一律 cut/SELL，中优 (30~60) reduce/REDUCE，无告警看 status 决 watch/hold。"
    "不要猜价不要谈宏观，只看赋予的数据。"
)

# 把上游 SKILL.md 拼到 fallback 短提示之后：先角色协议，再覆盖输出 schema 要求，
# 防止 LLM 沉浸 Z 哥角色后丢失结构化字段（这是 zettaranc-skill 原本不存在的约束）。
_ZETTARANC_SCHEMA_APPENDIX = (
    "\n\n# 输出格式硬约束（覆盖所有 Z 哥习惯）\n"
    "必须返回严格 JSON 对象，字段：\n"
    "- decision: cut|reduce|hold|watch|add\n"
    "- confidence: 0~1 浮点\n"
    "- rationale: 简体中文（<=400 字），用 Z 哥本人语气，必须包含三段推导：\n"
    "    ① 知行/趋势：短期趋势线、多空线、当前位置（碗底/贴线/多头/空头/震荡）一句话定位；\n"
    "    ② 量价/指标：KDJ（J 值/金叉死叉）、MACD（DIF-DEA/柱）、BBI/MA 多空头排列、RSI、量比 至少各点评一项；\n"
    "    ③ 纪律层：止损线、加减仓阈值、仓位上限（呼应 sell-discipline / position-management）。\n"
    "- analysis: 可选对象 {technical: string[], discipline: string[], risk: string[], next_step: string[]}\n"
    "    每段 2~4 条，每条 30~80 字；不会破坏老客户端兼容。\n"
    "- suggested_action: SELL|REDUCE|HOLD|WAIT|BUY\n"
    "- suggested_intent: {code, side, qty_hint, reason}\n"
    "不输出 markdown、不输出多余解释、不要 ```json 代码块包裹。"
)


def _build_zettaranc_system_prompt() -> str:
    """运行时拼装 zettaranc system prompt：SKILL.md 角色协议 + schema 约束。

    单独抽函数是为了让测试可 monkeypatch zettaranc_adapter.load_skill_md_role，
    无需读上游 600+ 行 markdown 也能验证 schema 接入路径。
    """
    try:
        role = zettaranc_adapter.load_skill_md_role()
    except Exception as exc:  # pragma: no cover - 防御性
        logger.warning("[tracking_llm] 加载 SKILL.md 失败，回退短提示: %s", exc)
        role = _SYSTEM_PROMPT_ZETTARANC_FALLBACK
    return role + _ZETTARANC_SCHEMA_APPENDIX


_PROFILE_PROMPTS = {
    "default": _SYSTEM_PROMPT,
    # zettaranc_style 不预先固化，运行时拼装（读 SKILL.md）。这里挂一个标记位，
    # 真正的 system_prompt 在 propose_action 里通过 _build_zettaranc_system_prompt() 取。
    "zettaranc_style": "__zettaranc_runtime__",
}
_ALLOWED_PROFILES = set(_PROFILE_PROMPTS.keys())


def _resolve_profile(profile: Optional[str]) -> str:
    """未知 profile 静默退回 default，避免 400。"""
    if not profile:
        return "default"
    name = str(profile).lower()
    return name if name in _ALLOWED_PROFILES else "default"



def _build_user_prompt(
    item: dict,
    alerts: list[dict],
    zettaranc_context: Optional[dict] = None,
) -> str:
    """组装 DeepSeek 的 user message，只暴露必要字段，避免上下文膨胀。

    zettaranc_context: 由 zettaranc_adapter.prepare_context 产出，
        ``{"source": "cli|local_csv|none", "text": ..., "error": ...}``。
        非空且 source != "none" 时，作为「行情快照」段落附在最前面，让 LLM
        基于真实数据回答，而不是只看持仓 JSON。
    """
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
            "action_label": a.get("action_label"),
            "message": a.get("message"),
            "ts": a.get("ts") or a.get("created_at"),
        }
        for a in alerts[:20]
    ]
    parts: list[str] = []
    if zettaranc_context and zettaranc_context.get("source") not in (None, "none"):
        parts.append(
            "## 行情快照（来源："
            + str(zettaranc_context.get("source"))
            + "）\n"
            + str(zettaranc_context.get("text") or "")
        )
    parts.append("## 持仓\n" + json.dumps(item_view, ensure_ascii=False))
    parts.append("## 告警（最多20条）\n" + json.dumps(alert_view, ensure_ascii=False))
    parts.append("请按系统提示输出严格 JSON。")
    return "\n\n".join(parts)


def _build_codex_cli_prompt(system_prompt: str, user_prompt: str) -> str:
    """Codex CLI 没有 chat role 参数，这里把 system/user 边界显式写入单段 prompt。"""
    return "\n\n".join(
        [
            "# 系统角色与规则",
            system_prompt,
            "# 输入数据",
            user_prompt,
            "# 输出要求",
            "只输出严格 JSON 对象，不要 markdown，不要解释，不要代码块。"
            "必须包含 analysis={technical:[], discipline:[], risk:[], next_step:[]}；"
            "没有额外分析时四个数组返回空数组。",
        ]
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
    result: dict[str, Any] = {
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
    _apply_rule_authority(result, item, triggering_alert)
    # 可选 analysis 段：zettaranc_style 用，dict 才透传，避免任意类型污染响应
    analysis_raw = raw.get("analysis")
    if isinstance(analysis_raw, dict) and analysis_raw:
        cleaned: dict[str, list[str]] = {}
        for key in ("technical", "discipline", "risk", "next_step"):
            val = analysis_raw.get(key)
            if isinstance(val, list):
                cleaned[key] = [str(x).strip() for x in val if str(x).strip()]
        if cleaned:
            result["analysis"] = cleaned
    return result


class TrackingLLMService:
    """LLM 建议服务：支持 provider 切换。"""

    def propose_action(
        self,
        item: dict,
        alerts: list[dict],
        frame: Optional[pd.DataFrame] = None,
        profile: Optional[str] = None,
    ) -> dict[str, Any]:
        """根据持仓 + 告警给出建议，输出结构稳定。

        - provider=mock：直接走确定性桩；profile 仅影响返回的 ``profile`` 标记。
        - provider=deepseek：调用线上接口，异常时回退 mock 并标记 fallback。
        - profile：default | zettaranc_style，只切换 system prompt 口吻，不改 JSON schema。

        Args:
            item: tracking_items 记录
            alerts: 最近告警列表
            frame: 行情 DataFrame（占位）
            profile: 提示词风格（default/zettaranc_style）

        Returns:
            标准建议结构，附 provider/provider_fallback/profile 字段。
        """
        cfg = load_llm_config()
        provider = str(cfg.get("provider") or "mock").lower()
        resolved_profile = _resolve_profile(profile)

        # 任务 C 档：zettaranc_style 时拉真行情快照 + 拼 SKILL.md 角色协议。
        # 注意：以下两步均允许失败（adapter 内部已自我降级），失败时 zettaranc_context
        # 仍是 {"source": "none", ...}，user prompt 不附行情段，行为退回纯 schema 路径。
        zettaranc_context: Optional[dict] = None
        if resolved_profile == "zettaranc_style":
            try:
                code = str(item.get("code") or "").strip()
                if code:
                    zettaranc_context = zettaranc_adapter.prepare_context(code)
            except Exception as exc:  # 防御性：adapter 任何异常都不影响主链路
                logger.warning("[tracking_llm] zettaranc 上下文准备失败: %s", exc)
                zettaranc_context = {"source": "none", "text": "", "error": str(exc)}

        # zettaranc_style 走运行时拼装的 system prompt（SKILL.md + schema 约束）
        if resolved_profile == "zettaranc_style":
            system_prompt = _build_zettaranc_system_prompt()
        else:
            system_prompt = _PROFILE_PROMPTS[resolved_profile]

        if provider == "codex_cli":
            cli_cfg = cfg.get("codex_cli") or {}
            try:
                raw = call_codex_cli(
                    command=str(cli_cfg.get("command") or "codex"),
                    model=str(cli_cfg.get("model") or "").strip() or None,
                    prompt=_build_codex_cli_prompt(
                        system_prompt,
                        _build_user_prompt(item, alerts, zettaranc_context),
                    ),
                    cwd=str(cli_cfg.get("cwd") or "").strip() or None,
                    timeout_seconds=float(
                        cli_cfg.get("timeout_seconds")
                        or cli_cfg.get("timeout_sec")
                        or 60
                    ),
                )
                normalized = _normalize_deepseek_payload(raw, item, alerts)
                normalized["provider"] = "codex_cli"
                normalized["provider_fallback"] = False
                normalized["profile"] = resolved_profile
                if zettaranc_context is not None:
                    normalized["zettaranc_data_source"] = zettaranc_context.get("source")
                return normalized
            except (CodexCLIError, ValueError) as exc:
                logger.warning(
                    "[tracking_llm] Codex CLI 调用失败，回退 mock: %s", exc
                )
                fallback = _propose_mock(item, alerts)
                _apply_rule_authority(fallback, item, _extract_min_priority(alerts)[1])
                fallback["provider"] = "mock"
                fallback["provider_fallback"] = True
                fallback["provider_error"] = str(exc)
                fallback["profile"] = resolved_profile
                if zettaranc_context is not None:
                    fallback["zettaranc_data_source"] = zettaranc_context.get("source")
                return fallback

        if provider == "deepseek":
            ds_cfg = cfg.get("deepseek") or {}
            # zettaranc_style 需要更长输出空间承载三段推导 + analysis 段，单独上调上限
            base_max_out = int(ds_cfg.get("max_output_tokens", 600))
            max_out = max(base_max_out, 1600) if resolved_profile == "zettaranc_style" else base_max_out
            try:
                raw = call_deepseek(
                    api_key=str(ds_cfg.get("api_key") or ""),
                    base_url=str(ds_cfg.get("base_url") or "https://api.deepseek.com/v1"),
                    model=str(ds_cfg.get("model") or "deepseek-chat"),
                    system_prompt=system_prompt,
                    user_prompt=_build_user_prompt(item, alerts, zettaranc_context),
                    temperature=float(ds_cfg.get("temperature", 0.2)),
                    timeout_seconds=float(ds_cfg.get("timeout_seconds", 20)),
                    max_output_tokens=max_out,
                )
                normalized = _normalize_deepseek_payload(raw, item, alerts)
                normalized["provider"] = "deepseek"
                normalized["provider_fallback"] = False
                normalized["profile"] = resolved_profile
                if zettaranc_context is not None:
                    normalized["zettaranc_data_source"] = zettaranc_context.get("source")
                return normalized
            except (DeepSeekError, ValueError) as exc:
                logger.warning(
                    "[tracking_llm] DeepSeek 调用失败，回退 mock: %s", exc
                )
                fallback = _propose_mock(item, alerts)
                _apply_rule_authority(fallback, item, _extract_min_priority(alerts)[1])
                fallback["provider"] = "mock"
                fallback["provider_fallback"] = True
                fallback["provider_error"] = str(exc)
                fallback["profile"] = resolved_profile
                if zettaranc_context is not None:
                    fallback["zettaranc_data_source"] = zettaranc_context.get("source")
                return fallback

        # 默认 mock 分支
        out = _propose_mock(item, alerts)
        _apply_rule_authority(out, item, _extract_min_priority(alerts)[1])
        out["provider"] = "mock"
        out["provider_fallback"] = False
        out["profile"] = resolved_profile
        if zettaranc_context is not None:
            out["zettaranc_data_source"] = zettaranc_context.get("source")
        return out


# 模块级单例，供路由/编排层引用；测试可通过 monkeypatch 替换。
tracking_llm_service = TrackingLLMService()
