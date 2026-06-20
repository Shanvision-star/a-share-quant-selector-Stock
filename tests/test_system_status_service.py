import json
import sys
import types

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

    import web.backend.services as services_pkg

    fake_strategy_service = types.SimpleNamespace(get_strategy_cache_status=forbidden_call)
    fake_repo_module = types.SimpleNamespace(
        list_runs=forbidden_call,
        finish_run=forbidden_call,
        insert_event=forbidden_call,
    )
    monkeypatch.setitem(sys.modules, "web.backend.services.strategy_service", fake_strategy_service)
    monkeypatch.setitem(sys.modules, "web.backend.services.strategy_result_repository", fake_repo_module)
    monkeypatch.setattr(services_pkg, "strategy_service", fake_strategy_service, raising=False)
    monkeypatch.setattr(services_pkg, "strategy_result_repository", fake_repo_module, raising=False)
    monkeypatch.setattr(svc_mod, "WEB_STRATEGY_RESULTS_FILE", tmp_path / "missing_strategy_cache.json", raising=False)
    monkeypatch.setattr(svc_mod, "WEB_STRATEGY_CACHE_DB_FILE", tmp_path / "missing_web_strategy_cache.db", raising=False)
    monkeypatch.setattr(svc_mod, "_default_requested_trade_date", lambda: "2026-06-19", raising=False)

    payload = svc_mod._default_strategy_cache_loader()

    assert payload["status"] == "missing"
    assert payload["requested_date"] == "2026-06-19"


def test_default_tracking_loader_is_read_only(monkeypatch):
    def forbidden_list_items(*args, **kwargs):
        raise AssertionError("system status must not call tracking_service.list_items")

    fake_tracking_module = types.SimpleNamespace(
        tracking_service=types.SimpleNamespace(list_items=forbidden_list_items)
    )

    monkeypatch.setitem(sys.modules, "web.backend.services.tracking_service", fake_tracking_module)

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
        },
        runs_loader=lambda: {"items": []},
        alerts_loader=lambda ui_status, limit=1000: [],
        config_loader=lambda: {},
    )

    payload = service.build_status()

    assert payload["overall_status"] == "ready"
    assert payload["tracking"]["status"] == "ready"
    assert payload["tracking"]["details"]["active_count"] >= 0


def test_read_only_strategy_cache_marks_same_date_missing_groups_partial(monkeypatch, tmp_path):
    cache_file = tmp_path / "web_strategy_results.json"
    cache_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "trade_date": "2026-06-19",
                "generated_at": "2026-06-19T16:00:00+08:00",
                "groups": {
                    "b1": {"total": 2},
                    "b2": {"total": 1},
                },
                "results": [
                    {"code": "000001", "strategy_filter": "b1"},
                    {"code": "000002", "strategy_filter": "b2"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(svc_mod, "WEB_STRATEGY_RESULTS_FILE", cache_file)
    monkeypatch.setattr(svc_mod, "_default_requested_trade_date", lambda: "2026-06-19")
    monkeypatch.setattr(svc_mod, "_latest_strategy_run", lambda requested_date: None)

    service = SystemStatusService(
        now_provider=lambda: NOW,
        data_status_loader=lambda: {
            "total_stocks": 5100,
            "latest_date": "2026-06-19",
            "stale_count": 0,
            "checked_count": 40,
            "is_fresh": True,
        },
        runs_loader=lambda: {"items": []},
        tracking_items_loader=lambda status, limit=1000: [],
        alerts_loader=lambda ui_status, limit=1000: [],
        config_loader=lambda: {},
    )

    payload = service.build_status()

    assert payload["strategy_cache"]["status"] == "partial"
    assert payload["strategy_cache"]["details"]["missing_groups"] == ["bowl", "brick"]
    assert payload["overall_status"] == "partial"


def test_default_alerts_loader_is_read_only(monkeypatch):
    class ForbiddenAlertService:
        def __init__(self, *args, **kwargs):
            raise AssertionError("system status must not construct TrackingAlertService")

    class ForbiddenAlertSingleton:
        def list_alerts(self, *args, **kwargs):
            raise AssertionError("system status must not call tracking_alert_service.list_alerts")

    fake_alert_module = types.SimpleNamespace(
        TrackingAlertService=ForbiddenAlertService,
        tracking_alert_service=ForbiddenAlertSingleton(),
    )
    monkeypatch.setitem(sys.modules, "web.backend.services.tracking_alert_service", fake_alert_module)

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
        },
        runs_loader=lambda: {"items": []},
        tracking_counts_loader=lambda status: 0,
        config_loader=lambda: {},
    )

    payload = service.build_status()

    assert payload["overall_status"] == "ready"
    assert payload["tracking"]["status"] == "ready"
    assert payload["tracking"]["details"]["pending_alert_count"] >= 0


def test_default_db_reads_do_not_use_project_sqlite_helpers(monkeypatch, tmp_path):
    def forbidden_call(*args, **kwargs):
        raise AssertionError("system status must use its own read-only sqlite connection")

    import web.backend.services as services_pkg

    fake_sqlite_module = types.SimpleNamespace(get_connection=forbidden_call)
    fake_repo_module = types.SimpleNamespace(list_runs=forbidden_call)
    monkeypatch.setitem(sys.modules, "web.backend.services.sqlite_service", fake_sqlite_module)
    monkeypatch.setitem(sys.modules, "web.backend.services.strategy_result_repository", fake_repo_module)
    monkeypatch.setattr(services_pkg, "sqlite_service", fake_sqlite_module, raising=False)
    monkeypatch.setattr(services_pkg, "strategy_result_repository", fake_repo_module, raising=False)
    monkeypatch.setattr(svc_mod, "WEB_STRATEGY_RESULTS_FILE", tmp_path / "missing_strategy_cache.json")
    monkeypatch.setattr(svc_mod, "WEB_STRATEGY_CACHE_DB_FILE", tmp_path / "missing_web_strategy_cache.db", raising=False)
    monkeypatch.setattr(svc_mod, "_default_requested_trade_date", lambda: "2026-06-19")

    service = SystemStatusService(
        now_provider=lambda: NOW,
        data_status_loader=lambda: {
            "total_stocks": 5100,
            "latest_date": "2026-06-19",
            "stale_count": 0,
            "checked_count": 40,
            "is_fresh": True,
        },
        config_loader=lambda: {},
    )

    payload = service.build_status()

    assert payload["strategy_cache"]["status"] == "missing"
    assert payload["update_pipeline"]["status"] == "missing"
    assert payload["tracking"]["status"] == "ready"
    assert not svc_mod.WEB_STRATEGY_CACHE_DB_FILE.exists()
