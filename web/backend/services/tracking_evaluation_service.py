"""P5 跟踪规则评估编排服务。

职责：
- 拉取活跃跟踪项（status ∈ watch_buy/holding/partial_sold）
- 加载升序 OHLC 数据（默认从 utils.csv_manager 读取，可注入桩用于测试）
- 注入 P3 模板服务的 params_overrides + enabled_rules
- 调用 tracking_rule_engine.evaluate_rules
- 借 tracking_alert_service 幂等落库
- 返回评估摘要 {evaluated, alerts_created, alerts_skipped_dup, items_with_alerts}

设计约束（参考 tracking_agent_plan.md §5）：
- 单条 item 异常不阻断整体流程；记入 errors 列表并继续。
- frame_loader 返回空 DataFrame → evaluated 仍计数，alerts_created 不增。
- 不直接发钉钉：分发由 tracking_alert_service.dispatch_pending_alerts 处理。
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

import pandas as pd

ACTIVE_TRACKING_STATUS = ("watch_buy", "holding", "partial_sold")


def _default_frame_loader(code: str) -> pd.DataFrame:
    """生产环境的默认 frame 加载器：读取 CSV 并升序排序。

    延迟导入 utils.csv_manager 避免测试环境强依赖。
    """
    try:
        from utils.csv_manager import CSVManager  # type: ignore

        df = CSVManager().read_stock(code, parse_dates=False)
        if df is None or df.empty or "date" not in df.columns:
            return pd.DataFrame()
        return df.sort_values("date").reset_index(drop=True)
    except Exception:
        return pd.DataFrame()


class TrackingEvaluationService:
    """编排活跃跟踪项的规则评估流程。"""

    def __init__(
        self,
        tracking_service=None,
        template_service=None,
        alert_service=None,
        frame_loader: Optional[Callable[[str], pd.DataFrame]] = None,
    ) -> None:
        # 延迟解析单例，便于测试通过 monkeypatch 替换
        if tracking_service is None:
            from web.backend.services.tracking_service import tracking_service as _ts

            tracking_service = _ts
        if template_service is None:
            from web.backend.services.tracking_rule_templates import (
                tracking_rule_template_service as _tts,
            )

            template_service = _tts
        if alert_service is None:
            from web.backend.services.tracking_alert_service import (
                tracking_alert_service as _as,
            )

            alert_service = _as

        self.tracking_service = tracking_service
        self.template_service = template_service
        self.alert_service = alert_service
        self.frame_loader = frame_loader or _default_frame_loader

    # ------------------------------------------------------------------
    def evaluate_active_items(
        self,
        eval_date: Optional[str] = None,
        only_codes: Optional[Iterable[str]] = None,
    ) -> dict:
        """评估所有活跃跟踪项；按 only_codes 可缩小范围。"""
        from web.backend.services.tracking_rule_engine import evaluate_rules

        engine_inputs = self.template_service.build_engine_inputs()
        params_overrides = engine_inputs.get("params_overrides") or {}
        enabled_rules = engine_inputs.get("enabled_rules")

        only_set = {str(c) for c in only_codes} if only_codes else None

        evaluated = 0
        created_total = 0
        skipped_total = 0
        items_with_alerts: list[str] = []
        errors: list[dict] = []

        # 逐状态拉取，避免一次性把 closed 也带回来
        candidates: list[dict] = []
        for status in ACTIVE_TRACKING_STATUS:
            candidates.extend(self.tracking_service.list_items(status=status, limit=1000))

        for item in candidates:
            code = item.get("code")
            if only_set is not None and code not in only_set:
                continue
            try:
                frame = self.frame_loader(code)
            except Exception as exc:  # 加载失败不阻断其它 item
                errors.append({"tracking_id": item.get("tracking_id"), "error": str(exc)})
                continue

            evaluated += 1
            if frame is None or getattr(frame, "empty", True):
                continue

            try:
                alerts = evaluate_rules(
                    item,
                    frame,
                    eval_date=eval_date,
                    params_overrides=params_overrides,
                    enabled_rules=enabled_rules,
                )
            except Exception as exc:
                errors.append({"tracking_id": item.get("tracking_id"), "error": str(exc)})
                continue

            if not alerts:
                continue

            result = self.alert_service.persist_alerts(alerts)
            created_total += result.get("created", 0)
            skipped_total += result.get("skipped_dup", 0)
            if result.get("created", 0) > 0:
                items_with_alerts.append(item.get("tracking_id", ""))

        return {
            "evaluated": evaluated,
            "alerts_created": created_total,
            "alerts_skipped_dup": skipped_total,
            "items_with_alerts": items_with_alerts,
            "errors": errors,
        }


tracking_evaluation_service = TrackingEvaluationService()
