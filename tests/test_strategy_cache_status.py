from datetime import timedelta

from web.backend.services import strategy_service


def test_cache_status_ignores_running_run_from_previous_backend_process(monkeypatch):
    """后端重启后，旧进程留下的 running 记录不能让前端继续转圈。"""
    target_date = "2026-05-06"
    stale_started_at = (
        strategy_service._PROCESS_STARTED_AT - timedelta(minutes=5)
    ).strftime("%Y-%m-%d %H:%M:%S")
    stale_run = {
        "run_id": "old-run",
        "run_type": "update_and_rebuild",
        "trade_date": target_date,
        "strategy_filter": "all",
        "status": "running",
        "started_at": stale_started_at,
        "completed_at": None,
        "message": "旧任务仍显示运行中",
        "processed_count": 0,
        "total_count": 0,
        "matched_count": 0,
    }
    snapshot = {
        "trade_date": target_date,
        "generated_at": "2026-05-07 05:38:10",
        "results": [
            {"code": "000001", "strategy_filter": "b1"},
        ],
        "groups": {
            "b1": {"total": 1},
        },
    }

    monkeypatch.setattr(strategy_service, "_read_strategy_snapshot", lambda: snapshot)
    monkeypatch.setattr(strategy_service, "_get_expected_strategy_filters", lambda: ["b1"])
    monkeypatch.setattr(strategy_service, "_get_rebuild_state", lambda: {"is_running": False})

    def fake_list_runs(**kwargs):
        if kwargs.get("status") == "running":
            return {"items": [stale_run]}
        return {"items": [stale_run]}

    finished = []
    monkeypatch.setattr(strategy_service.repo, "list_runs", fake_list_runs)
    monkeypatch.setattr(strategy_service.repo, "get_result_summary_for_date", lambda date: None)
    monkeypatch.setattr(
        strategy_service.repo,
        "finish_run",
        lambda run_id, status, message="", **kwargs: finished.append((run_id, status, message)),
    )
    monkeypatch.setattr(strategy_service.repo, "insert_event", lambda *args, **kwargs: None)

    status = strategy_service.get_strategy_cache_status("all", target_date)

    assert status["status"] == "ready"
    assert status["source"] == "file"
    assert status["rebuild"].get("is_running") is False
    assert status["latest_run_status"] == "error"
    assert finished and finished[0][0] == "old-run"


def test_cache_status_derives_progress_from_persisted_run_counts(monkeypatch):
    """统一作业不写高频事件时，刷新页面仍应看到可恢复的重建进度。"""
    target_date = "2026-05-06"
    running_run = {
        "run_id": "current-run",
        "run_type": "update_and_rebuild",
        "trade_date": target_date,
        "strategy_filter": "all",
        "status": "running",
        "stage": "rebuild",
        "started_at": (
            strategy_service._PROCESS_STARTED_AT + timedelta(seconds=1)
        ).strftime("%Y-%m-%d %H:%M:%S"),
        "completed_at": None,
        "message": "扫描中",
        "processed_count": 250,
        "total_count": 500,
        "matched_count": 12,
    }
    monkeypatch.setattr(strategy_service, "_read_strategy_snapshot", lambda: None)
    monkeypatch.setattr(strategy_service, "_get_expected_strategy_filters", lambda: ["b1"])
    monkeypatch.setattr(strategy_service, "_get_rebuild_state", lambda: {"is_running": False})
    monkeypatch.setattr(
        strategy_service.repo,
        "list_runs",
        lambda **kwargs: {"items": [running_run]},
    )
    monkeypatch.setattr(strategy_service.repo, "get_result_summary_for_date", lambda date: None)
    monkeypatch.setattr(strategy_service.repo, "get_run_events", lambda run_id, limit=50: [])

    status = strategy_service.get_strategy_cache_status("all", target_date)

    assert status["status"] == "running"
    assert status["rebuild"]["progress"] == 50
    assert status["rebuild"]["processed"] == 250
    assert status["rebuild"]["total"] == 500
    assert status["rebuild"]["matched"] == 12
