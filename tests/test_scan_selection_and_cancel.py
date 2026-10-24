"""验证多选策略单次发布与发布前取消，并覆盖 SSE 显式关闭边界。"""

import asyncio
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from web.backend.services import data_service, strategy_scan as runtime, strategy_service as service


@pytest.fixture
def isolated_update(monkeypatch):
    monkeypatch.setattr(runtime, '_job', None)
    monkeypatch.setattr(data_service, '_UPDATE_JOB_LOCK', threading.Lock())
    monkeypatch.setattr(data_service, '_UPDATE_JOB_STATE', {})
    monkeypatch.setattr(data_service.csv_manager, 'list_all_stocks', lambda: ['000001'])
    monkeypatch.setattr(data_service.fetcher, 'daily_update', lambda **kwargs: {
        'status': 'done', 'target_date': '2026-10-23', 'cache_hit': True})
    for name in ('create_run', 'finish_run', 'insert_event', 'update_run'):
        monkeypatch.setattr(data_service.repo, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(data_service.repo, 'get_run', lambda *args: None)


def test_selected_update_builds_all_requested_strategies_once(isolated_update, monkeypatch):
    calls = []

    def build(**kwargs):
        calls.append(kwargs)
        return {'trade_date': kwargs['target_date'], 'total': 0, 'groups': {'b1': {}, 'b2': {}}}

    monkeypatch.setattr(service, 'build_strategy_result_snapshot', build)

    async def collect():
        return [event async for event in data_service.run_data_update(
            auto_rebuild=True, target_date='2026-10-23', strategies=['b1', 'b2'])]

    events = asyncio.run(collect())
    assert events[-1]['event'] == 'job_complete'
    assert len(calls) == 1
    assert calls[0]['strategy_filter'] == 'all'
    assert calls[0]['strategy_filters'] == ['b1', 'b2']
    assert calls[0]['run_id'] == events[-1]['data']['run_id']


@pytest.fixture
def selected_builder(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, '_job', None)
    cache_file = tmp_path / 'results.json'
    cache_file.write_text('previous good snapshot', encoding='utf-8')
    monkeypatch.setattr(service, 'WEB_STRATEGY_RESULTS_FILE', cache_file)
    monkeypatch.setattr(service, 'csv_manager', SimpleNamespace(
        list_all_stocks=lambda: ['000001'], data_dir=tmp_path,
        get_stock_path=lambda code: tmp_path / f'{code}.csv'))
    monkeypatch.setattr(runtime, 'file_manifest', lambda paths: {'input': 'unchanged'})
    monkeypatch.setattr(service, 'get_registry', lambda *args: SimpleNamespace(
        auto_register_from_directory=lambda *args: None))
    strategies = {sf: {'strategy_name': name, 'strategy': None}
                  for sf, name in [('b1', 'B1CaseStrategy'), ('b2', 'B2Strategy')]}
    monkeypatch.setattr(service, '_resolve_web_strategies', lambda *args: strategies)
    monkeypatch.setattr(service, '_load_stock_names', lambda: {'000001': '测试'})
    monkeypatch.setattr(service.repo, 'get_published_snapshot', lambda path: None)
    published = []
    monkeypatch.setattr(service, '_write_results_to_sqlite', lambda *args: published.append(args))
    return cache_file, published


def test_second_selected_strategy_error_prevents_entire_publication(selected_builder, monkeypatch):
    cache_file, published = selected_builder
    row = {
        'code': '000001', 'name': '测试', 'status': 'error',
        'hits': {'b1': {'strategy_name': 'B1CaseStrategy', 'stock_result': {
            'code': '000001', 'name': '测试',
            'signals': [{'date': '2026-10-23', 'close': 10.0, 'category': 'signal'}],
        }}},
        'outcomes': {
            'b1': {'status': 'matched', 'signal_count': 1},
            'b2': {'status': 'error', 'signal_count': 0, 'error_type': 'ValueError',
                   'error_message': 'bad B2 template'},
        },
    }
    requested = []

    def results(codes, names, items, *args, **kwargs):
        requested.append([item[0] for item in items])
        yield row

    monkeypatch.setattr(runtime, 'iter_scan_results', results)
    with pytest.raises(RuntimeError, match='异常'):
        service.build_strategy_result_snapshot(
            '2026-10-23', 'all', run_id='selected-error', strategy_filters=['b1', 'b2'])
    assert requested == [['b1', 'b2']]
    assert published == []
    assert cache_file.read_text(encoding='utf-8') == 'previous good snapshot'


def test_cancel_during_temporary_file_write_prevents_database_publication(selected_builder, monkeypatch):
    cache_file, published = selected_builder
    row = {'code': '000001', 'name': '测试', 'status': 'ok', 'hits': {},
           'outcomes': {sf: {'status': 'not_matched', 'signal_count': 0} for sf in ('b1', 'b2')}}
    monkeypatch.setattr(runtime, 'iter_scan_results', lambda *args, **kwargs: iter([row]))
    original_write = Path.write_text
    cancellation = []

    def write_then_cancel(path, *args, **kwargs):
        result = original_write(path, *args, **kwargs)
        if path == cache_file.with_suffix('.tmp'):
            cancellation.extend(runtime.cancel_active_scans())
        return result

    monkeypatch.setattr(Path, 'write_text', write_then_cancel)
    with pytest.raises(runtime.ScanCancelled):
        service.build_strategy_result_snapshot(
            '2026-10-23', 'all', run_id='cancel-before-commit', strategy_filters=['b1', 'b2'])
    assert cancellation == ['cancel-before-commit']
    assert published == []
    assert cache_file.read_text(encoding='utf-8') == 'previous good snapshot'
    assert runtime.active_scan_status() == []


@pytest.mark.parametrize('route', ['update', 'init'])
def test_sse_route_close_immediately_closes_business_stream(monkeypatch, route):
    from web.backend.routers import update

    closed = []

    async def business_stream(**kwargs):
        try:
            yield {'event': 'progress', 'data': {'status': 'running'}}
            await asyncio.sleep(60)
        finally:
            closed.append(True)

    monkeypatch.setattr(data_service, 'run_data_update', business_stream)
    monkeypatch.setattr(data_service, 'run_data_init', business_stream)

    async def check():
        response = (await update.trigger_update(auto_rebuild=False, date='2026-10-23', pipeline=False,
                    allow_intraday_fast=False, init_if_empty=False, strategies=None)
                    if route == 'update' else await update.trigger_init(max_stocks=1))
        item = await anext(response.body_iterator)
        assert item['event'] == 'progress'
        await response.body_iterator.aclose()
        # 必须在事件循环退出前验证，不能依赖 asyncio.run 的最终清理掩盖泄漏。
        assert closed == [True]

    asyncio.run(check())
