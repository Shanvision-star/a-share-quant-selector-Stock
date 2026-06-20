"""系统状态中心聚合服务。

本模块只读取现有服务状态，不触发数据更新、策略重建、真实推送或交易动作。
它把数据 freshness、策略缓存 freshness、更新作业、Tracking 和集成配置归一化，
让前端能解释“为什么页面没有数据”。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
UPDATE_RUN_TYPES = {"update_and_rebuild", "update_only", "init_only"}
ACTIVE_TRACKING_STATUSES = ("watch_buy", "holding", "partial_sold")
CORE_STATUS_WEIGHT = {
    "ready": 0,
    "disabled": 0,
    "running": 1,
    "stale": 2,
    "missing": 3,
    "not_found": 3,
    "partial": 4,
    "error": 5,
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_bool(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _read_yaml_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _default_config_loader() -> dict:
    return {
        "config": _read_yaml_file(PROJECT_ROOT / "config" / "config.yaml"),
        "llm": _read_yaml_file(PROJECT_ROOT / "config" / "llm.yaml"),
    }


def _default_data_status_loader() -> dict:
    from web.backend.services.data_service import get_data_status

    return get_data_status()


def _default_strategy_cache_loader() -> dict:
    from web.backend.services.strategy_service import get_strategy_cache_status

    return get_strategy_cache_status("all")


def _default_runs_loader() -> dict:
    from web.backend.services import strategy_result_repository as repo

    return repo.list_runs(page=1, per_page=20)


def _default_tracking_items_loader(status: str, limit: int = 1000) -> list[dict]:
    from web.backend.services.tracking_service import tracking_service

    return tracking_service.list_items(status=status, limit=limit)


def _default_alerts_loader(ui_status: str, limit: int = 1000) -> list[dict]:
    from web.backend.services.tracking_alert_service import tracking_alert_service

    return tracking_alert_service.list_alerts(ui_status=ui_status, limit=limit)


@dataclass(frozen=True)
class StatusBlock:
    status: str
    message: str
    checked_at: str
    next_action: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "checked_at": self.checked_at,
            "next_action": self.next_action,
            "details": self.details,
        }


class SystemStatusService:
    """聚合系统状态，提供给 `/api/system/status` 使用。"""

    def __init__(
        self,
        *,
        now_provider: Callable[[], str] = _now_iso,
        data_status_loader: Callable[[], dict] = _default_data_status_loader,
        strategy_cache_loader: Callable[[], dict] = _default_strategy_cache_loader,
        runs_loader: Callable[[], dict] = _default_runs_loader,
        tracking_items_loader: Callable[[str, int], list[dict]] = _default_tracking_items_loader,
        alerts_loader: Callable[[str, int], list[dict]] = _default_alerts_loader,
        config_loader: Callable[[], dict] = _default_config_loader,
    ) -> None:
        self.now_provider = now_provider
        self.data_status_loader = data_status_loader
        self.strategy_cache_loader = strategy_cache_loader
        self.runs_loader = runs_loader
        self.tracking_items_loader = tracking_items_loader
        self.alerts_loader = alerts_loader
        self.config_loader = config_loader

    def build_status(self) -> dict[str, Any]:
        checked_at = self.now_provider()
        backend = self._backend_block(checked_at)
        data = self._guarded_block("data", checked_at, self._data_block)
        strategy_cache = self._guarded_block("strategy_cache", checked_at, self._strategy_cache_block)
        update_pipeline = self._guarded_block("update_pipeline", checked_at, self._update_pipeline_block)
        tracking = self._guarded_block("tracking", checked_at, self._tracking_block, core_block=False)
        integrations = self._guarded_block("integrations", checked_at, self._integrations_block, core_block=False)
        blocks = {
            "backend": backend,
            "data": data,
            "strategy_cache": strategy_cache,
            "update_pipeline": update_pipeline,
            "tracking": tracking,
            "integrations": integrations,
        }
        overall = self._overall_status(blocks)
        return {
            "checked_at": checked_at,
            "overall_status": overall,
            **{key: value.to_dict() for key, value in blocks.items()},
            "frontend_hints": self._frontend_hints(blocks, overall),
        }

    def _backend_block(self, checked_at: str) -> StatusBlock:
        return StatusBlock(
            status="ready",
            message="后端 API 可用。",
            checked_at=checked_at,
            next_action="继续检查数据和策略缓存状态。",
            details={
                "api_version": "2.0.0",
                "service": "FastAPI",
            },
        )

    def _guarded_block(
        self,
        name: str,
        checked_at: str,
        builder: Callable[[str], StatusBlock],
        *,
        core_block: bool = True,
    ) -> StatusBlock:
        try:
            return builder(checked_at)
        except Exception as exc:
            action = "先查看后端日志，再重试状态检查。" if core_block else "该模块不阻断数据和策略主链路。"
            return StatusBlock(
                status="error",
                message=f"{name} 状态读取失败: {exc}",
                checked_at=checked_at,
                next_action=action,
                details={"error_type": type(exc).__name__},
            )

    def _data_block(self, checked_at: str) -> StatusBlock:
        raw = self.data_status_loader() or {}
        total = int(raw.get("total_stocks") or 0)
        latest_date = raw.get("latest_date") or "-"
        is_fresh = bool(raw.get("is_fresh"))
        if total <= 0:
            status = "missing"
            message = "本地行情 CSV 不存在或未被识别。"
            action = "进入数据更新页执行首次初始化。"
        elif not is_fresh:
            status = "stale"
            message = f"本地行情存在，但抽样显示最新日期 {latest_date} 未达到预期。"
            action = "进入数据更新页执行 update+rebuild。"
        else:
            status = "ready"
            message = f"本地行情数据可用，最新样本日期 {latest_date}。"
            action = "继续检查策略缓存是否与行情日期一致。"
        return StatusBlock(
            status=status,
            message=message,
            checked_at=checked_at,
            next_action=action,
            details={
                "total_stocks": total,
                "latest_date": latest_date,
                "stale_count": raw.get("stale_count", 0),
                "checked_count": raw.get("checked_count", 0),
                "is_fresh": is_fresh,
                "boards": raw.get("boards", {}),
            },
        )

    def _strategy_cache_block(self, checked_at: str) -> StatusBlock:
        raw = self.strategy_cache_loader() or {}
        raw_status = str(raw.get("status") or "missing")
        status = "missing" if raw_status == "not_found" else raw_status
        trade_date = raw.get("trade_date")
        requested_date = raw.get("requested_date")
        is_latest = bool(raw.get("is_latest"))
        if status == "ready" and requested_date and trade_date and requested_date != trade_date:
            status = "stale"
        if status == "ready" and not is_latest:
            status = "stale"

        if status == "ready":
            message = f"策略缓存可用，缓存日期 {trade_date}。"
            action = "可以查看策略结果。"
        elif status == "running":
            message = raw.get("message") or "策略缓存正在重建。"
            action = "等待重建完成，或进入数据更新页查看进度。"
        elif status == "partial":
            message = raw.get("message") or "策略缓存部分可用，但缺少策略分组。"
            action = "进入策略结果页或数据更新页重建全部策略缓存。"
        elif status == "stale":
            message = raw.get("message") or f"策略缓存日期 {trade_date} 与目标日期 {requested_date} 不一致。"
            action = "进入数据更新页执行 update+rebuild。"
        else:
            status = "missing"
            message = raw.get("message") or "策略缓存缺失。"
            action = "进入数据更新页生成策略缓存。"

        return StatusBlock(
            status=status,
            message=message,
            checked_at=checked_at,
            next_action=action,
            details={
                "requested_date": requested_date,
                "trade_date": trade_date,
                "generated_at": raw.get("generated_at"),
                "total": raw.get("total", 0),
                "unique_total": raw.get("unique_total", 0),
                "available_groups": raw.get("available_groups", []),
                "missing_groups": raw.get("missing_groups", []),
                "latest_run_status": raw.get("latest_run_status"),
                "last_run_id": raw.get("last_run_id"),
                "rebuild": raw.get("rebuild", {}),
            },
        )

    def _update_pipeline_block(self, checked_at: str) -> StatusBlock:
        runs = (self.runs_loader() or {}).get("items", [])
        update_runs = [run for run in runs if run.get("run_type") in UPDATE_RUN_TYPES]
        latest = update_runs[0] if update_runs else None
        if not latest:
            return StatusBlock(
                status="missing",
                message="尚未找到数据更新作业记录。",
                checked_at=checked_at,
                next_action="如果页面无数据，进入数据更新页执行一次 update+rebuild。",
                details={"latest_run": None},
            )

        raw_status = str(latest.get("status") or "missing")
        if raw_status == "done":
            status = "ready"
            action = "继续检查策略缓存是否 ready。"
        elif raw_status == "running":
            status = "running"
            action = "进入数据更新页查看实时进度。"
        elif raw_status == "partial":
            status = "partial"
            action = "不要直接信任当前结果；检查失败股票后重新执行 update+rebuild。"
        else:
            status = "error"
            action = "查看最近更新错误并重新执行 update+rebuild。"

        return StatusBlock(
            status=status,
            message=latest.get("message") or f"最近更新作业状态: {raw_status}",
            checked_at=checked_at,
            next_action=action,
            details={
                "latest_run": {
                    "run_id": latest.get("run_id"),
                    "run_type": latest.get("run_type"),
                    "trade_date": latest.get("trade_date"),
                    "status": latest.get("status"),
                    "matched_count": latest.get("matched_count"),
                    "processed_count": latest.get("processed_count"),
                    "total_count": latest.get("total_count"),
                    "started_at": latest.get("started_at"),
                    "completed_at": latest.get("completed_at"),
                }
            },
        )

    def _tracking_block(self, checked_at: str) -> StatusBlock:
        counts: dict[str, int] = {}
        total_active = 0
        for status in ACTIVE_TRACKING_STATUSES:
            items = self.tracking_items_loader(status, 1000)
            counts[status] = len(items)
            total_active += len(items)
        pending_alerts = self.alerts_loader("pending", 1000)
        return StatusBlock(
            status="ready",
            message=f"Tracking 活跃记录 {total_active} 条，待处理告警 {len(pending_alerts)} 条。",
            checked_at=checked_at,
            next_action="Tracking 状态不影响数据和策略主链路。",
            details={
                "active_count": total_active,
                "status_counts": counts,
                "pending_alert_count": len(pending_alerts),
            },
        )

    def _integrations_block(self, checked_at: str) -> StatusBlock:
        raw = self.config_loader() or {}
        app_config = raw.get("config") or raw
        llm_config = raw.get("llm") or {}
        dingtalk = app_config.get("dingtalk", {}) if isinstance(app_config, dict) else {}
        qmt = app_config.get("qmt", {}) if isinstance(app_config, dict) else {}
        deepseek = llm_config.get("deepseek", {}) if isinstance(llm_config, dict) else {}

        # 集成区只暴露布尔状态，避免 webhook、api_key、账户号和本机路径进入前端 payload。
        dingtalk_configured = _safe_bool(dingtalk.get("webhook_url"))
        llm_configured = _safe_bool(deepseek.get("api_key"))
        qmt_enabled = bool(qmt.get("enabled", False))
        any_configured = dingtalk_configured or llm_configured or qmt_enabled
        return StatusBlock(
            status="ready" if any_configured else "disabled",
            message="外部集成配置已脱敏汇总。" if any_configured else "外部集成未配置或当前不启用。",
            checked_at=checked_at,
            next_action="集成配置不影响数据和策略主链路。",
            details={
                "dingtalk": {
                    "configured": dingtalk_configured,
                    "signed": _safe_bool(dingtalk.get("secret")),
                },
                "llm": {
                    "deepseek_configured": llm_configured,
                    "provider": "deepseek" if llm_configured else "",
                },
                "qmt": {
                    "enabled": qmt_enabled,
                    "mode": qmt.get("mode") or "disabled",
                    "reserved_only": bool(qmt.get("reserved_only", True)),
                },
            },
        )

    def _overall_status(self, blocks: dict[str, StatusBlock]) -> str:
        core_blocks = [blocks["data"], blocks["strategy_cache"]]
        update_status = blocks["update_pipeline"].status
        if update_status in {"running", "partial", "error"}:
            core_blocks.append(blocks["update_pipeline"])
        worst = max(core_blocks, key=lambda block: CORE_STATUS_WEIGHT.get(block.status, 5))
        return "missing" if worst.status == "not_found" else worst.status

    def _frontend_hints(self, blocks: dict[str, StatusBlock], overall: str) -> list[str]:
        hints: list[str] = []
        data = blocks["data"]
        strategy = blocks["strategy_cache"]
        update = blocks["update_pipeline"]
        if data.status in {"missing", "stale", "error"}:
            hints.append(data.next_action)
        if strategy.status in {"missing", "stale", "partial", "running", "error"}:
            hints.append(strategy.next_action)
        if update.status == "running":
            hints.append("有数据更新任务正在运行，当前页面可能显示旧缓存。")
        if update.status == "partial":
            hints.append("最近更新是 partial/局部完成，不建议把当前结果当作完整结果。")
        if update.status == "error":
            hints.append("最近更新失败，请先查看更新页错误信息。")
        if overall == "ready" and not hints:
            hints.append("数据和策略缓存均可用，可以查看策略结果。")
        return list(dict.fromkeys(hints))


system_status_service = SystemStatusService()
