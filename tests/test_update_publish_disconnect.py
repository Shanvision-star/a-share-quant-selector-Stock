"""使用真实内存仓储验证行情流断连发生在权威发布前后的运行终态。"""

import asyncio
import sqlite3

import pytest

from web.backend.services import data_service
from web.backend.services import sqlite_service as db
from web.backend.services import strategy_result_repository as repo
from web.backend.services import strategy_scan as runtime
from web.backend.services import strategy_service


@pytest.fixture
def publication_store(monkeypatch, tmp_path):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    monkeypatch.setattr(db, "get_connection", lambda: connection)
    monkeypatch.setattr(repo, "get_connection", lambda: connection)
    monkeypatch.setattr(runtime, "_job", None)
    cache_file = tmp_path / "results.json"
    monkeypatch.setattr(strategy_service, "WEB_STRATEGY_RESULTS_FILE", cache_file)
    db.init_database()
    yield cache_file
    connection.close()


def _publish(run_id, cache_file):
    rows = [{"run_id": run_id, "trade_date": "2026-10-23", "strategy_filter": "b1",
             "strategy_name": "B1", "code": "000001", "signal_date": "2026-10-23",
             "category": "signal", "close": 10.0}]
    snapshot = {"_run_id": run_id, "trade_date": "2026-10-23", "total": 1,
                "groups": {"b1": {"total": 1}}, "available_groups": ["b1"],
                "results": rows, "scan_summary": {"processed": 2, "total_stocks": 2}}
    repo.publish_snapshot(run_id, "2026-10-23", "b1", rows, snapshot, cache_file)


def _disconnect(monkeypatch, run_id, before_yield):
    closed = []

    async def business_stream(**kwargs):
        try:
            before_yield(kwargs["_cancel_event"])
            yield {"event": "progress", "data": {"status": "running", "progress": 99}}
            await asyncio.sleep(60)
        finally:
            closed.append(True)

    monkeypatch.setattr(data_service, "_run_data_update_unlocked", business_stream)

    async def close_stream():
        stream = data_service._market_update_messages(_run_id=run_id)
        await anext(stream)
        await stream.aclose()
        # 在事件循环退出前断言，避免 asyncio.run 的最终清理掩盖泄漏。
        assert closed == [True]
        assert runtime.active_scan_status() == []

    asyncio.run(close_stream())


def test_disconnect_after_committed_publication_preserves_done(publication_store, monkeypatch):
    run_id = "published-then-disconnected"
    repo.create_run(run_id, "update_and_rebuild", "2026-10-23", "all", total_count=2)

    def committed(cancelled):
        with runtime.publication_guard(cancelled):
            _publish(run_id, publication_store)

    _disconnect(monkeypatch, run_id, committed)
    run = repo.get_run(run_id)
    assert run["status"] == "done"
    assert run["processed_count"] == 2
    assert run["matched_count"] == 1
    assert "发布后" in run["message"]
    assert repo.get_published_snapshot(publication_store)["_run_id"] == run_id


def test_disconnect_before_publication_preserves_previous_snapshot(publication_store, monkeypatch):
    repo.create_run("previous", "update_and_rebuild", "2026-10-23", "all", total_count=2)
    _publish("previous", publication_store)
    run_id = "disconnected-before-publish"
    repo.create_run(run_id, "update_and_rebuild", "2026-10-23", "all", total_count=2)
    _disconnect(monkeypatch, run_id, lambda cancelled: None)
    assert repo.get_run(run_id)["status"] == "error"
    assert repo.get_published_snapshot(publication_store)["_run_id"] == "previous"


@pytest.mark.parametrize("invalid_evidence", ["different_cache", "invalidated", "different_date"])
def test_unrelated_or_invalidated_publication_cannot_mark_run_done(
        publication_store, monkeypatch, invalid_evidence):
    run_id = "not-current-authority"
    run_date = "2026-10-22" if invalid_evidence == "different_date" else "2026-10-23"
    repo.create_run(run_id, "update_and_rebuild", run_date, "all", total_count=2)

    def publish_invalid_evidence(cancelled):
        cache_file = (publication_store.with_name("other.json")
                      if invalid_evidence == "different_cache" else publication_store)
        with runtime.publication_guard(cancelled):
            _publish(run_id, cache_file)
        if invalid_evidence == "invalidated":
            repo.invalidate_published_snapshots(cache_file)

    _disconnect(monkeypatch, run_id, publish_invalid_evidence)
    assert repo.get_run(run_id)["status"] == "error"
