import asyncio

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
