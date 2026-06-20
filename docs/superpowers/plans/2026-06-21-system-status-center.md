# System Status Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only system status center that explains why the Web workspace has or does not have usable data.

**Architecture:** Add one backend aggregation service and one `/api/system/status` route that normalize existing data, strategy cache, update pipeline, tracking, and integration health into a stable payload. Add one Vue route `/status` that displays the payload and links users to existing update or strategy pages without automatically triggering writes.

**Tech Stack:** Python 3, FastAPI, pytest, Vue 3, TypeScript, Element Plus, Vitest.

---

## Scope Check

The approved spec contains a broad architecture blueprint and a P0 subproject. This plan implements only the P0 subproject: system status center.

The plan does not implement schema migrations, trading objects, Tracking-Agent lifecycle changes, Zettaranc promotion, QMT, or broader navigation redesign. Those remain separate future specs.

## File Structure

- Create: `web/backend/services/system_status_service.py`
  - One read-only aggregation service.
  - Normalizes module status blocks.
  - Uses injectable dependencies for deterministic tests.

- Create: `web/backend/routers/system_status.py`
  - FastAPI router for `GET /api/system/status`.
  - No writes, no update trigger, no provider smoke.

- Modify: `web/backend/main.py`
  - Import and include the new router before frontend fallback.

- Create: `tests/test_system_status_service.py`
  - Unit tests for ready, missing cache, partial update, submodule error, and secret masking.

- Create: `tests/test_system_status_router.py`
  - API route smoke test.

- Modify: `web/frontend/src/api/index.ts`
  - Add system status TypeScript types and `getSystemStatus()`.

- Create: `web/frontend/src/api/__tests__/systemStatusApi.spec.ts`
  - Vitest test for API wrapper path.

- Create: `web/frontend/src/views/SystemStatusView.vue`
  - Status center page.
  - Shows overall status, module cards, diagnostics, and safe navigation links.

- Modify: `web/frontend/src/router/index.ts`
  - Add `/status` route.

- Modify: `web/frontend/src/components/AppSidebar.vue`
  - Add sidebar entry.

- Modify: `web/frontend/src/views/HomeView.vue`
  - Add visible link from cache status card to system status.

- Modify: `README.md`
  - Add `/status` to Web workspace page table.

---

### Task 1: Backend Status Service Tests And Core Aggregator

**Files:**
- Create: `tests/test_system_status_service.py`
- Create: `web/backend/services/system_status_service.py`

- [ ] **Step 1: Write failing backend service tests**

Create `tests/test_system_status_service.py`:

```python
import json

import pytest

from web.backend.services.system_status_service import SystemStatusService


NOW = "2026-06-21T10:00:00+08:00"


def build_service(
    *,
    data_status=None,
    strategy_status=None,
    runs=None,
    tracking_items=None,
    alerts=None,
    config=None,
):
    tracking_items = tracking_items or {}
    alerts = alerts or []
    config = config or {}

    return SystemStatusService(
        now_provider=lambda: NOW,
        data_status_loader=lambda: data_status or {
            "total_stocks": 5100,
            "latest_date": "2026-06-19",
            "stale_count": 0,
            "checked_count": 40,
            "is_fresh": True,
            "boards": {},
        },
        strategy_cache_loader=lambda: strategy_status or {
            "status": "ready",
            "requested_date": "2026-06-19",
            "trade_date": "2026-06-19",
            "is_latest": True,
            "total": 120,
            "unique_total": 98,
            "latest_run_status": "done",
            "last_run_id": "run_ready",
            "message": "当日策略缓存可直接复用。",
        },
        runs_loader=lambda: {"items": runs or []},
        tracking_items_loader=lambda status, limit=1000: tracking_items.get(status, []),
        alerts_loader=lambda ui_status, limit=1000: alerts,
        config_loader=lambda: config,
    )


def test_system_status_ready_when_data_and_strategy_cache_ready():
    service = build_service(
        runs=[
            {
                "run_id": "run_ready",
                "run_type": "update_and_rebuild",
                "trade_date": "2026-06-19",
                "status": "done",
                "matched_count": 120,
                "completed_at": "2026-06-19 15:40:00",
                "message": "统一作业完成",
            }
        ],
        tracking_items={
            "watch_buy": [{"tracking_id": "trk_1"}, {"tracking_id": "trk_2"}],
            "holding": [{"tracking_id": "trk_3"}],
            "partial_sold": [],
        },
        alerts=[{"alert_id": 1, "ui_status": "pending"}],
        config={
            "config": {"dingtalk": {"webhook_url": "https://example.invalid/token", "secret": "secret-value"}},
            "llm": {"deepseek": {"api_key": "llm-secret", "model": "deepseek-chat"}},
        },
    )

    payload = service.build_status()

    assert payload["overall_status"] == "ready"
    assert payload["data"]["status"] == "ready"
    assert payload["strategy_cache"]["status"] == "ready"
    assert payload["update_pipeline"]["status"] == "ready"
    assert payload["tracking"]["details"]["active_count"] == 3
    assert payload["tracking"]["details"]["pending_alert_count"] == 1
    assert payload["integrations"]["details"]["dingtalk"]["configured"] is True
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "secret-value" not in serialized
    assert "llm-secret" not in serialized
    assert "access_token" not in serialized


def test_system_status_reports_missing_when_data_ready_but_strategy_cache_missing():
    service = build_service(
        strategy_status={
            "status": "missing",
            "requested_date": "2026-06-19",
            "trade_date": None,
            "is_latest": False,
            "total": 0,
            "unique_total": 0,
            "message": "策略缓存文件不存在，请先手动重建。",
        }
    )

    payload = service.build_status()

    assert payload["overall_status"] == "missing"
    assert payload["strategy_cache"]["status"] == "missing"
    assert any("策略缓存" in hint for hint in payload["frontend_hints"])


def test_system_status_keeps_partial_update_from_looking_ready():
    service = build_service(
        runs=[
            {
                "run_id": "run_partial",
                "run_type": "update_and_rebuild",
                "trade_date": "2026-06-19",
                "status": "partial",
                "matched_count": 0,
                "completed_at": "2026-06-19 15:30:00",
                "message": "数据更新未全量完成",
            }
        ]
    )

    payload = service.build_status()

    assert payload["overall_status"] == "partial"
    assert payload["update_pipeline"]["status"] == "partial"
    assert any("partial" in hint or "局部" in hint for hint in payload["frontend_hints"])


def test_system_status_marks_submodule_error_without_raising():
    service = SystemStatusService(
        now_provider=lambda: NOW,
        data_status_loader=lambda: (_ for _ in ()).throw(RuntimeError("csv broken")),
        strategy_cache_loader=lambda: {"status": "ready", "trade_date": "2026-06-19", "requested_date": "2026-06-19"},
        runs_loader=lambda: {"items": []},
        tracking_items_loader=lambda status, limit=1000: [],
        alerts_loader=lambda ui_status, limit=1000: [],
        config_loader=lambda: {},
    )

    payload = service.build_status()

    assert payload["overall_status"] == "error"
    assert payload["data"]["status"] == "error"
    assert "csv broken" in payload["data"]["message"]


def test_system_status_does_not_let_tracking_or_integrations_block_core_ready():
    service = SystemStatusService(
        now_provider=lambda: NOW,
        data_status_loader=lambda: {
            "total_stocks": 5100,
            "latest_date": "2026-06-19",
            "stale_count": 0,
            "checked_count": 40,
            "is_fresh": True,
        },
        strategy_cache_loader=lambda: {
            "status": "ready",
            "requested_date": "2026-06-19",
            "trade_date": "2026-06-19",
            "is_latest": True,
            "total": 120,
            "unique_total": 98,
            "message": "当日策略缓存可直接复用。",
        },
        runs_loader=lambda: {"items": []},
        tracking_items_loader=lambda status, limit=1000: (_ for _ in ()).throw(RuntimeError("tracking unavailable")),
        alerts_loader=lambda ui_status, limit=1000: [],
        config_loader=lambda: {},
    )

    payload = service.build_status()

    assert payload["overall_status"] == "ready"
    assert payload["tracking"]["status"] == "error"
    assert payload["integrations"]["status"] == "disabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pytest tests/test_system_status_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'web.backend.services.system_status_service'`.

- [ ] **Step 3: Implement the backend status service**

Create `web/backend/services/system_status_service.py`:

```python
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
```

- [ ] **Step 4: Run service tests**

Run:

```bash
pytest tests/test_system_status_service.py -q
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit backend service**

Run:

```bash
git add tests/test_system_status_service.py web/backend/services/system_status_service.py
git commit -m "feat: add system status aggregation service"
```

Expected: commit contains only the service and its unit tests.

---

### Task 2: Backend Router And App Registration

**Files:**
- Create: `web/backend/routers/system_status.py`
- Create: `tests/test_system_status_router.py`
- Modify: `web/backend/main.py`

- [ ] **Step 1: Write failing router test**

Create `tests/test_system_status_router.py`:

```python
from fastapi.testclient import TestClient

from web.backend import main
from web.backend.routers import system_status


class FakeSystemStatusService:
    def build_status(self):
        return {
            "checked_at": "2026-06-21T10:00:00+08:00",
            "overall_status": "ready",
            "backend": {"status": "ready"},
            "data": {"status": "ready"},
            "strategy_cache": {"status": "ready"},
            "update_pipeline": {"status": "missing"},
            "tracking": {"status": "ready"},
            "integrations": {"status": "disabled"},
            "frontend_hints": ["数据和策略缓存均可用，可以查看策略结果。"],
        }


def test_system_status_route_returns_payload(monkeypatch):
    monkeypatch.setattr(system_status, "system_status_service", FakeSystemStatusService())
    client = TestClient(main.app)

    response = client.get("/api/system/status")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["overall_status"] == "ready"
```

- [ ] **Step 2: Run router test to verify it fails**

Run:

```bash
pytest tests/test_system_status_router.py -q
```

Expected: FAIL because `web.backend.routers.system_status` does not exist or route is not registered.

- [ ] **Step 3: Create the route**

Create `web/backend/routers/system_status.py`:

```python
"""系统状态中心接口。"""

from fastapi import APIRouter

from web.backend.services.system_status_service import system_status_service


router = APIRouter(prefix="/api", tags=["系统状态"])


@router.get("/system/status")
async def get_system_status():
    """返回只读系统状态聚合结果。"""
    return {"success": True, "data": system_status_service.build_status()}
```

- [ ] **Step 4: Register the route in FastAPI app**

Modify `web/backend/main.py`.

In the router import tuple, add `system_status` after `strategy_docs`:

```python
from web.backend.routers import (
    kline,
    strategy,
    stock,
    update,
    config_api,
    backtest,
    trajectory,
    txt_export,
    manual_selection,
    strategy_docs,
    system_status,
    tracking,
    tracking_rule_template,
    tracking_alert,
    tracking_evaluation,
    tracking_llm,
    tracking_llm_diagnose,
    tracking_intent,
    zettaranc,
)
```

Register it after `strategy_docs.router` and before the Tracking fixed route block:

```python
app.include_router(strategy_docs.router)
# 系统状态中心：只读聚合数据、策略缓存、更新作业和集成健康，不触发写操作。
app.include_router(system_status.router)
```

- [ ] **Step 5: Run router test and import smoke**

Run:

```bash
pytest tests/test_system_status_router.py -q
python -c "from web.backend.main import app; print('import-ok')"
```

Expected:

```text
1 passed
import-ok
```

- [ ] **Step 6: Run backend focused tests**

Run:

```bash
pytest tests/test_system_status_service.py tests/test_system_status_router.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit backend route**

Run:

```bash
git add web/backend/routers/system_status.py web/backend/main.py tests/test_system_status_router.py
git commit -m "feat: expose system status API"
```

Expected: commit contains router registration and route test only.

---

### Task 3: Frontend API Types And Wrapper

**Files:**
- Modify: `web/frontend/src/api/index.ts`
- Create: `web/frontend/src/api/__tests__/systemStatusApi.spec.ts`

- [ ] **Step 1: Write failing API wrapper test**

Create `web/frontend/src/api/__tests__/systemStatusApi.spec.ts`:

```typescript
import { afterEach, describe, expect, it, vi } from 'vitest'
import api, { getSystemStatus, type SystemStatusPayload } from '@/api'

describe('system status API', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('requests the system status endpoint', async () => {
    const payload: SystemStatusPayload = {
      checked_at: '2026-06-21T10:00:00+08:00',
      overall_status: 'ready',
      backend: { status: 'ready', message: 'ok', checked_at: 'now', next_action: '', details: {} },
      data: { status: 'ready', message: 'ok', checked_at: 'now', next_action: '', details: {} },
      strategy_cache: { status: 'ready', message: 'ok', checked_at: 'now', next_action: '', details: {} },
      update_pipeline: { status: 'missing', message: 'none', checked_at: 'now', next_action: '', details: {} },
      tracking: { status: 'ready', message: 'ok', checked_at: 'now', next_action: '', details: {} },
      integrations: { status: 'disabled', message: 'off', checked_at: 'now', next_action: '', details: {} },
      frontend_hints: [],
    }
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ data: { success: true, data: payload } } as any)

    await getSystemStatus()

    expect(getSpy).toHaveBeenCalledWith('/system/status')
  })
})
```

- [ ] **Step 2: Run frontend API test to verify it fails**

Run:

```bash
cd web/frontend
npm run test -- src/api/__tests__/systemStatusApi.spec.ts
```

Expected: FAIL because `getSystemStatus` and `SystemStatusPayload` are not exported.

- [ ] **Step 3: Add TypeScript types and API function**

Modify `web/frontend/src/api/index.ts`.

Insert after `export const healthCheck = () => api.get('/health')`:

```typescript
// ─── 系统状态中心 ───
export type SystemStatusKind = 'ready' | 'stale' | 'missing' | 'running' | 'partial' | 'error' | 'disabled'

export interface SystemStatusBlock {
  status: SystemStatusKind | string
  message: string
  checked_at: string
  next_action: string
  details: Record<string, any>
}

export interface SystemStatusPayload {
  checked_at: string
  overall_status: SystemStatusKind | string
  backend: SystemStatusBlock
  data: SystemStatusBlock
  strategy_cache: SystemStatusBlock
  update_pipeline: SystemStatusBlock
  tracking: SystemStatusBlock
  integrations: SystemStatusBlock
  frontend_hints: string[]
}

export const getSystemStatus = () =>
  api.get<{ success: boolean; data: SystemStatusPayload }>('/system/status')
```

- [ ] **Step 4: Run frontend API test**

Run:

```bash
cd web/frontend
npm run test -- src/api/__tests__/systemStatusApi.spec.ts
```

Expected: PASS.

- [ ] **Step 5: Commit frontend API wrapper**

Run:

```bash
git add web/frontend/src/api/index.ts web/frontend/src/api/__tests__/systemStatusApi.spec.ts
git commit -m "feat: add system status frontend API"
```

Expected: commit contains API wrapper and test only.

---

### Task 4: System Status Page, Route, And Sidebar Entry

**Files:**
- Create: `web/frontend/src/views/SystemStatusView.vue`
- Modify: `web/frontend/src/router/index.ts`
- Modify: `web/frontend/src/components/AppSidebar.vue`

- [ ] **Step 1: Create the status page**

Create `web/frontend/src/views/SystemStatusView.vue`:

```vue
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { RefreshRight } from '@element-plus/icons-vue'
import { getSystemStatus, type SystemStatusBlock, type SystemStatusPayload } from '@/api'

const router = useRouter()
const loading = ref(false)
const errorMessage = ref('')
const statusPayload = ref<SystemStatusPayload | null>(null)

const coreBlocks = computed(() => {
  const payload = statusPayload.value
  if (!payload) return []
  return [
    { key: 'data', title: '行情数据', block: payload.data },
    { key: 'strategy_cache', title: '策略缓存', block: payload.strategy_cache },
    { key: 'update_pipeline', title: '更新作业', block: payload.update_pipeline },
  ]
})

const supportBlocks = computed(() => {
  const payload = statusPayload.value
  if (!payload) return []
  return [
    { key: 'tracking', title: '跟踪运营', block: payload.tracking },
    { key: 'integrations', title: '外部集成', block: payload.integrations },
    { key: 'backend', title: '后端服务', block: payload.backend },
  ]
})

function statusType(status?: string) {
  if (status === 'ready') return 'success'
  if (status === 'running') return 'primary'
  if (status === 'stale' || status === 'partial') return 'warning'
  if (status === 'missing' || status === 'error') return 'danger'
  return 'info'
}

function statusLabel(status?: string) {
  const labels: Record<string, string> = {
    ready: '可用',
    stale: '过期',
    missing: '缺失',
    running: '运行中',
    partial: '局部完成',
    error: '错误',
    disabled: '未启用',
  }
  return labels[status || ''] || status || '未知'
}

function formatDetails(block: SystemStatusBlock) {
  return JSON.stringify(block.details || {}, null, 2)
}

async function loadStatus() {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await getSystemStatus()
    statusPayload.value = response.data.data
  } catch (error: any) {
    statusPayload.value = null
    errorMessage.value = error?.message || '系统状态读取失败'
  } finally {
    loading.value = false
  }
}

function goToUpdate() {
  router.push('/update')
}

function goToStrategyResults() {
  router.push('/strategy-results')
}

onMounted(loadStatus)
</script>

<template>
  <div class="system-status-view">
    <div class="page-header">
      <div>
        <h2>系统状态</h2>
        <p>只读检查行情、策略缓存、更新作业和集成健康。</p>
      </div>
      <el-button :icon="RefreshRight" :loading="loading" @click="loadStatus">
        刷新
      </el-button>
    </div>

    <el-alert
      v-if="errorMessage"
      type="error"
      :closable="false"
      show-icon
      class="status-alert"
    >
      <template #title>
        后端不可达或代理异常：{{ errorMessage }}。请检查 FastAPI 后端是否运行在 localhost:8001。
      </template>
    </el-alert>

    <template v-if="statusPayload">
      <el-alert
        :type="statusType(statusPayload.overall_status)"
        :closable="false"
        show-icon
        class="status-alert"
      >
        <template #title>
          总体状态：{{ statusLabel(statusPayload.overall_status) }}
        </template>
        <div>检查时间：{{ statusPayload.checked_at }}</div>
      </el-alert>

      <div v-if="statusPayload.frontend_hints.length" class="hint-list">
        <el-alert
          v-for="hint in statusPayload.frontend_hints"
          :key="hint"
          type="info"
          :closable="false"
          show-icon
        >
          <template #title>{{ hint }}</template>
        </el-alert>
      </div>

      <div class="quick-actions">
        <el-button type="primary" @click="goToUpdate">前往数据更新</el-button>
        <el-button @click="goToStrategyResults">查看策略结果</el-button>
      </div>

      <h3>主链路</h3>
      <div class="status-grid">
        <el-card v-for="item in coreBlocks" :key="item.key" shadow="never" class="status-card">
          <template #header>
            <div class="card-head">
              <span>{{ item.title }}</span>
              <el-tag :type="statusType(item.block.status)">
                {{ statusLabel(item.block.status) }}
              </el-tag>
            </div>
          </template>
          <p class="message">{{ item.block.message }}</p>
          <p class="next-action">{{ item.block.next_action }}</p>
          <pre>{{ formatDetails(item.block) }}</pre>
        </el-card>
      </div>

      <h3>辅助模块</h3>
      <div class="status-grid">
        <el-card v-for="item in supportBlocks" :key="item.key" shadow="never" class="status-card">
          <template #header>
            <div class="card-head">
              <span>{{ item.title }}</span>
              <el-tag :type="statusType(item.block.status)">
                {{ statusLabel(item.block.status) }}
              </el-tag>
            </div>
          </template>
          <p class="message">{{ item.block.message }}</p>
          <p class="next-action">{{ item.block.next_action }}</p>
          <pre>{{ formatDetails(item.block) }}</pre>
        </el-card>
      </div>
    </template>

    <el-skeleton v-else-if="loading" :rows="8" animated />
  </div>
</template>

<style scoped>
.system-status-view {
  padding: 20px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.page-header h2 {
  margin: 0 0 6px;
}

.page-header p {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.status-alert {
  margin-bottom: 14px;
}

.hint-list {
  display: grid;
  gap: 8px;
  margin-bottom: 16px;
}

.quick-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

h3 {
  margin: 18px 0 10px;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}

.status-card {
  min-height: 220px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.message {
  margin: 0 0 8px;
  color: var(--el-text-color-primary);
  line-height: 1.6;
}

.next-action {
  margin: 0 0 10px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

pre {
  max-height: 180px;
  overflow: auto;
  padding: 10px;
  margin: 0;
  border-radius: 4px;
  background: var(--el-fill-color-lighter);
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.5;
}
</style>
```

- [ ] **Step 2: Add route**

Modify `web/frontend/src/router/index.ts`.

Insert after the `/settings` route:

```typescript
  {
    path: '/status',
    name: 'SystemStatus',
    component: () => import('@/views/SystemStatusView.vue'),
  },
```

- [ ] **Step 3: Add sidebar entry**

Modify `web/frontend/src/components/AppSidebar.vue`.

Keep existing imports unchanged because `Setting` is already available.

Insert after the 参数设置 item:

```vue
      <el-menu-item index="/status">
        <el-icon><Setting /></el-icon>
        <template #title>系统状态</template>
      </el-menu-item>
```

- [ ] **Step 4: Run frontend type/build verification**

Run:

```bash
cd web/frontend
npm run build
```

Expected: `vue-tsc -b` and `vite build` both pass.

- [ ] **Step 5: Commit status page**

Run:

```bash
git add web/frontend/src/views/SystemStatusView.vue web/frontend/src/router/index.ts web/frontend/src/components/AppSidebar.vue
git commit -m "feat: add system status page"
```

Expected: commit contains the new page, route, and sidebar entry.

---

### Task 5: Home Page Entry Point

**Files:**
- Modify: `web/frontend/src/views/HomeView.vue`

- [ ] **Step 1: Add navigation helper**

Modify `web/frontend/src/views/HomeView.vue`.

In the script section near existing navigation helpers, add:

```typescript
function goToSystemStatus() { router.push('/status') }
```

- [ ] **Step 2: Add visible button in cache actions**

In the `<div class="cache-actions" v-if="cacheStatus">` block, add this button after the existing conditional buttons:

```vue
            <el-button
              size="small"
              @click="goToSystemStatus"
            >
              系统状态
            </el-button>
```

- [ ] **Step 3: Run frontend build**

Run:

```bash
cd web/frontend
npm run build
```

Expected: build passes.

- [ ] **Step 4: Commit home entry**

Run:

```bash
git add web/frontend/src/views/HomeView.vue
git commit -m "feat: link home cache state to system status"
```

Expected: commit contains only the HomeView navigation change.

---

### Task 6: README Update And Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update Web workspace route table**

Modify `README.md` in the “Web 工作台页面” table. Add this row after 参数设置:

```markdown
| **系统状态** | `/status` | 只读检查后端、数据新鲜度、策略缓存、更新作业、Tracking 与集成配置健康 |
```

- [ ] **Step 2: Run backend focused tests**

Run:

```bash
pytest tests/test_system_status_service.py tests/test_system_status_router.py -q
python -c "from web.backend.main import app; print('import-ok')"
```

Expected:

```text
6 passed
import-ok
```

- [ ] **Step 3: Run frontend focused tests and build**

Run:

```bash
cd web/frontend
npm run test -- src/api/__tests__/systemStatusApi.spec.ts
npm run build
```

Expected: API test passes and build completes.

- [ ] **Step 4: Optional local manual smoke**

Run backend and frontend:

```bash
cd web
npm run backend
```

In another terminal:

```bash
cd web
npm run dev
```

Open:

```text
http://localhost:5173/status
```

Expected:

- Page loads without blank state.
- Overall status appears.
- Data, strategy cache, update pipeline, tracking, integrations, backend blocks render.
- Quick action buttons navigate to `/update` and `/strategy-results`.

- [ ] **Step 5: Check diff hygiene**

Run:

```bash
git diff --check
git status --short --branch
```

Expected:

- `git diff --check` prints no errors.
- Only files from this plan are modified, aside from pre-existing unrelated workspace changes.

- [ ] **Step 6: Commit documentation and final verification note**

Run:

```bash
git add README.md
git commit -m "docs: document system status page"
```

Expected: commit contains README route table update only.

---

## Implementation Notes

- Keep `/api/system/status` read-only. It must not call `run_data_update`, `run_data_init`, `stream_strategy_cache_rebuild`, DingTalk send methods, LLM provider smoke, or broker adapters.
- Treat data freshness and strategy cache freshness as separate states.
- Do not expose `webhook_url`, `secret`, `api_key`, `account_id`, or local broker paths in the status payload.
- Keep Tracking and integrations outside the core `overall_status` decision. They may show `error` or `disabled` without blocking data and strategy readiness.
- If the worker sees `config/config.yaml` contains secrets, do not copy those values into tests, docs, logs, or commit messages.

## Final Verification Checklist

- [ ] `pytest tests/test_system_status_service.py tests/test_system_status_router.py -q`
- [ ] `python -c "from web.backend.main import app; print('import-ok')"`
- [ ] `cd web/frontend && npm run test -- src/api/__tests__/systemStatusApi.spec.ts`
- [ ] `cd web/frontend && npm run build`
- [ ] `git diff --check`
- [ ] Manual smoke at `http://localhost:5173/status` if local servers are available
