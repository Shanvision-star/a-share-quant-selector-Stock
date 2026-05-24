import asyncio
from datetime import datetime as real_datetime

from web.backend.services import data_service
from web.backend.services import strategy_service


def test_run_data_update_uses_actual_update_target_for_rebuild(monkeypatch):
    """更新器回退到最近完成交易日后，策略重建也必须使用同一个日期。"""
    monkeypatch.setattr(data_service.csv_manager, "list_all_stocks", lambda: ["000001"])
    monkeypatch.setattr(strategy_service, "get_latest_trade_date", lambda: "2026-05-07")

    def fake_daily_update(**kwargs):
        return {
            "status": "done",
            "message": "2026-05-06 数据更新完成",
            "target_date": "2026-05-06",
            "completed": 1,
            "cache_hit": False,
            "fast_path_total": 1,
            "slow_path_total": 0,
        }

    monkeypatch.setattr(data_service.fetcher, "daily_update", fake_daily_update)

    snapshot_dates = []

    def fake_build_snapshot(target_date, strategy_filter, progress_callback, run_id):
        snapshot_dates.append(target_date)
        return {
            "trade_date": target_date,
            "total": 0,
            "groups": {},
        }

    monkeypatch.setattr(strategy_service, "build_strategy_result_snapshot", fake_build_snapshot)

    update_run_calls = []
    monkeypatch.setattr(data_service.repo, "generate_run_id", lambda: "run-test")
    monkeypatch.setattr(data_service.repo, "create_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        data_service.repo,
        "update_run",
        lambda run_id, **kwargs: update_run_calls.append(kwargs),
    )
    monkeypatch.setattr(data_service.repo, "finish_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.repo, "insert_event", lambda *args, **kwargs: None)

    async def collect_events():
        return [
            event
            async for event in data_service.run_data_update(
                auto_rebuild=True,
                target_date="2026-05-07",
                pipeline=False,
                init_if_empty=True,
            )
        ]

    events = asyncio.run(collect_events())

    assert snapshot_dates == ["2026-05-06"]
    assert any(call.get("trade_date") == "2026-05-06" for call in update_run_calls)
    assert any(
        event["event"] == "rebuild_start"
        and event["data"]["trade_date"] == "2026-05-06"
        for event in events
    )


def test_run_data_update_preopen_intraday_fast_uses_latest_completed_trade_date(monkeypatch):
    """开盘前勾选盘中快路径时，统一作业仍应使用最近已完成交易日。"""
    class FakeDateTime(real_datetime):
        @classmethod
        def now(cls):
            return cls(2026, 5, 14, 7, 30, 0)

    monkeypatch.setattr(data_service, "datetime", FakeDateTime)
    monkeypatch.setattr(data_service.csv_manager, "list_all_stocks", lambda: ["000001"])
    monkeypatch.setattr(strategy_service, "get_latest_trade_date", lambda: "2026-05-13")
    monkeypatch.setattr(data_service.repo, "generate_run_id", lambda: "run-preopen")
    monkeypatch.setattr(data_service.repo, "create_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.repo, "finish_run", lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.repo, "insert_event", lambda *args, **kwargs: None)

    update_calls = []

    def fake_daily_update(**kwargs):
        update_calls.append(kwargs)
        return {
            "status": "done",
            "message": "2026-05-13 数据更新完成",
            "target_date": "2026-05-13",
            "completed": 1,
            "cache_hit": False,
            "fast_path_total": 1,
            "slow_path_total": 0,
        }

    monkeypatch.setattr(data_service.fetcher, "daily_update", fake_daily_update)

    async def collect_events():
        return [
            event
            async for event in data_service.run_data_update(
                auto_rebuild=False,
                target_date=None,
                allow_intraday_fast=True,
                pipeline=False,
                init_if_empty=True,
            )
        ]

    events = asyncio.run(collect_events())

    assert update_calls[0]["date"] == "2026-05-13"
    assert update_calls[0]["allow_intraday_fast"] is True
    assert any(
        event["event"] == "job_start"
        and event["data"]["trade_date"] == "2026-05-13"
        for event in events
    )


def test_run_data_update_rejects_overlapping_jobs(monkeypatch):
    """已有更新任务运行时，后端必须拒绝重复启动，避免多个任务并发写同一批 CSV。"""
    acquired = data_service._UPDATE_JOB_LOCK.acquire(blocking=False)
    assert acquired
    data_service._UPDATE_JOB_STATE.update({
        "is_running": True,
        "run_id": "run-active",
        "trade_date": "2026-05-22",
    })

    async def collect_events():
        return [
            event
            async for event in data_service.run_data_update(
                auto_rebuild=True,
                target_date="2026-05-22",
                pipeline=False,
                init_if_empty=True,
            )
        ]

    try:
        events = asyncio.run(collect_events())
    finally:
        data_service._UPDATE_JOB_STATE.clear()
        data_service._UPDATE_JOB_LOCK.release()

    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert events[0]["data"]["status"] == "busy"
    assert events[0]["data"]["active_run_id"] == "run-active"
    assert "已有数据更新任务正在运行" in events[0]["data"]["message"]


def test_mark_stale_update_runs_interrupted(monkeypatch):
    """后端重启后遗留的 running 更新任务应标记中断，避免页面误判仍在运行。"""
    monkeypatch.setattr(
        data_service.repo,
        "list_runs",
        lambda **kwargs: {
            "items": [
                {
                    "run_id": "old-update",
                    "run_type": "update_and_rebuild",
                    "started_at": "2000-01-01 00:00:00",
                    "status": "running",
                },
                {
                    "run_id": "old-rebuild",
                    "run_type": "rebuild_only",
                    "started_at": "2000-01-01 00:00:00",
                    "status": "running",
                },
            ]
        },
    )
    finished = []
    events = []
    monkeypatch.setattr(data_service.repo, "finish_run", lambda *args, **kwargs: finished.append(args))
    monkeypatch.setattr(data_service.repo, "insert_event", lambda *args, **kwargs: events.append(args))

    marked = data_service.mark_stale_update_runs_interrupted()

    assert marked == 1
    assert finished[0][0] == "old-update"
    assert finished[0][1] == "error"
    assert events[0][0] == "old-update"
