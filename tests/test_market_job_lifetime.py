"""验证取消和断连后行情写入仍持有租约，策略回调异常必须留痕。"""

import asyncio
import threading

import pytest

from web.backend.services import data_service, strategy_scan as runtime, strategy_service


@pytest.fixture(autouse=True)
def isolated_jobs(monkeypatch):
    monkeypatch.setattr(runtime, '_job', None)
    monkeypatch.setattr(data_service, '_UPDATE_JOB_LOCK', threading.Lock())
    monkeypatch.setattr(data_service, '_UPDATE_JOB_STATE', {})
    monkeypatch.setattr(data_service.csv_manager, 'list_all_stocks', lambda: ['000001'])
    monkeypatch.setattr(data_service.repo, 'create_run', lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.repo, 'finish_run', lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.repo, 'insert_event', lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.repo, 'update_run', lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.repo, 'get_run', lambda *args: {'run_id': 'test'})


async def _wait_started(event):
    for _ in range(200):
        if event.is_set():
            return
        await asyncio.sleep(.005)
    raise AssertionError('测试行情线程未启动')


@pytest.mark.parametrize('mode', ['update', 'init'])
def test_cancel_keeps_market_lease_until_real_writer_stops(monkeypatch, mode):
    started, release = threading.Event(), threading.Event()

    def writer(**kwargs):
        started.set()
        kwargs['progress_callback']({'progress': 20, 'message': 'working'})
        assert release.wait(3)
        return {'status': 'done', 'cache_hit': True, 'total': 1, 'success': 1, 'failed': 0}

    monkeypatch.setattr(data_service.fetcher, 'daily_update', writer)
    monkeypatch.setattr(data_service.fetcher, 'init_full_data', writer)

    async def check():
        stream = (data_service.run_data_update(auto_rebuild=False, target_date='2026-10-23')
                  if mode == 'update' else data_service.run_data_init(max_stocks=1))

        async def collect():
            return [item async for item in stream]

        task = asyncio.create_task(collect())
        try:
            await _wait_started(started)
            runtime.cancel_active_scans()
            await asyncio.sleep(.05)
            assert runtime.active_scan_status()
            with pytest.raises(runtime.ScanBusy):
                with runtime.market_job('another-job', 'scan'):
                    pass
            assert not task.done()
        finally:
            release.set()
            events = await asyncio.wait_for(task, 1)
        assert events[-1]['event'] == 'error'
        assert not any(item['event'] == 'job_complete' for item in events)
        assert runtime.active_scan_status() == []

    asyncio.run(check())


def test_disconnect_does_not_release_running_writer_lease(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def writer(**kwargs):
        started.set()
        kwargs['progress_callback']({'progress': 20})
        assert release.wait(3)
        return {'status': 'done', 'cache_hit': True}

    monkeypatch.setattr(data_service.fetcher, 'daily_update', writer)

    async def check():
        stream = data_service.run_data_update(auto_rebuild=False, target_date='2026-10-23')
        try:
            while True:
                event = await anext(stream)
                if event['event'] == 'update_progress':
                    break
            await asyncio.wait_for(stream.aclose(), .2)
            assert runtime.active_scan_status()
            with pytest.raises(runtime.ScanBusy):
                with runtime.market_job('new-scan', 'scan'):
                    pass
        finally:
            release.set()
            for _ in range(200):
                if not runtime.active_scan_status():
                    break
                await asyncio.sleep(.005)
        assert runtime.active_scan_status() == []

    asyncio.run(check())


def test_pipeline_failure_is_recorded_and_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(strategy_service, 'get_resolved_strategy_items', lambda: ({'000001': '测试'}, []))

    def fail(*args):
        raise ValueError('bad strategy data')

    monkeypatch.setattr(strategy_service, 'scan_one_stock_with_df', fail)

    def writer(**kwargs):
        kwargs['on_stock_ready']('000001', object())
        return {'status': 'done', 'cache_hit': True}

    monkeypatch.setattr(data_service.fetcher, 'daily_update', writer)

    async def collect():
        return [item async for item in data_service.run_data_update(
            auto_rebuild=False, pipeline=True, target_date='2026-10-23')]

    events = asyncio.run(collect())
    assert any(event['event'] == 'pipeline_error' for event in events)
    assert events[-1]['event'] == 'error'
    assert events[-1]['data']['pipeline_error_count'] == 1
    assert events[-1]['data']['update_status'] == 'done'
