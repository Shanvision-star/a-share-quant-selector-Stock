import json

import pytest

from web.backend.services import system_status_service as svc_mod
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


def test_default_strategy_cache_loader_is_read_only(monkeypatch, tmp_path):
    def forbidden_call(*args, **kwargs):
        raise AssertionError("system status must not call write-capable strategy cache status")

    from web.backend.services import strategy_result_repository as repo
    from web.backend.services import strategy_service

    monkeypatch.setattr(strategy_service, "get_strategy_cache_status", forbidden_call)
    monkeypatch.setattr(repo, "finish_run", forbidden_call)
    monkeypatch.setattr(repo, "insert_event", forbidden_call)
    monkeypatch.setattr(svc_mod, "WEB_STRATEGY_RESULTS_FILE", tmp_path / "missing_strategy_cache.json", raising=False)
    monkeypatch.setattr(svc_mod, "_default_requested_trade_date", lambda: "2026-06-19", raising=False)

    payload = svc_mod._default_strategy_cache_loader()

    assert payload["status"] == "missing"
    assert payload["requested_date"] == "2026-06-19"
