"""验证正式扫描失败时不覆盖已发布结果。"""
from types import SimpleNamespace
import pytest


@pytest.fixture
def scan_fixture(monkeypatch, tmp_path):
    from web.backend.services import strategy_service as service, strategy_scan as runtime
    monkeypatch.setattr(service, 'WEB_STRATEGY_RESULTS_FILE', tmp_path / 'results.json')
    service.WEB_STRATEGY_RESULTS_FILE.write_text('previous good snapshot', encoding='utf-8')
    manager = SimpleNamespace(list_all_stocks=lambda: ['000001'], data_dir=tmp_path,
                              get_stock_path=lambda code: tmp_path / f'{code}.csv')
    (tmp_path / '000001.csv').write_text('date,close\n2026-10-23,10\n')
    monkeypatch.setattr(service, 'csv_manager', manager)
    monkeypatch.setattr(service, 'get_registry', lambda *args: SimpleNamespace(auto_register_from_directory=lambda *args: None))
    monkeypatch.setattr(service, '_resolve_web_strategies', lambda *args: {})
    monkeypatch.setattr(service, '_resolve_selected_web_strategies', lambda *args: [('b1', 'B1CaseStrategy', None)])
    monkeypatch.setattr(service, '_load_stock_names', lambda: {'000001': '测试'})
    published = []
    monkeypatch.setattr(service, '_write_results_to_sqlite', lambda *args: published.append(args))
    return service, runtime, published


def test_strategy_error_never_publishes_partial_snapshot(scan_fixture, monkeypatch):
    service, runtime, published = scan_fixture
    monkeypatch.setattr(runtime, 'iter_scan_results', lambda *args, **kwargs: iter([
        {'code': '000001', 'status': 'error', 'hits': {},
         'outcomes': {'b1': {'status': 'error', 'error_message': 'broken formula'}}}]))
    with pytest.raises(RuntimeError, match='异常'):
        service.build_strategy_result_snapshot('2026-10-23', 'b1', run_id='error-test')
    assert not published
    assert service.WEB_STRATEGY_RESULTS_FILE.read_text(encoding='utf-8') == 'previous good snapshot'


def test_all_strategies_requires_complete_registration(scan_fixture, monkeypatch):
    service, runtime, published = scan_fixture
    started = []
    monkeypatch.setattr(runtime, 'iter_scan_results', lambda *args, **kwargs: started.append(True) or iter([]))
    with pytest.raises(RuntimeError, match='未全部注册'):
        service.build_strategy_result_snapshot('2026-10-23', 'all', run_id='incomplete-registration')
    assert not started
    assert not published


def test_missing_strategy_outcome_never_publishes(scan_fixture, monkeypatch):
    service, runtime, published = scan_fixture
    monkeypatch.setattr(runtime, 'iter_scan_results', lambda *args, **kwargs: iter([
        {'code': '000001', 'status': 'ok', 'hits': {}, 'outcomes': {}}]))
    with pytest.raises(RuntimeError, match='完整'):
        service.build_strategy_result_snapshot('2026-10-23', 'b1', run_id='missing-test')
    assert not published


def test_changed_input_never_publishes(scan_fixture, monkeypatch):
    service, runtime, published = scan_fixture
    def result(*args, **kwargs):
        (service.csv_manager.data_dir / '000001.csv').write_text('changed')
        yield {'code': '000001', 'status': 'ok', 'hits': {},
               'outcomes': {'b1': {'status': 'not_matched'}}}
    monkeypatch.setattr(runtime, 'iter_scan_results', result)
    with pytest.raises(RuntimeError, match='变化'):
        service.build_strategy_result_snapshot('2026-10-23', 'b1', run_id='changed-test')
    assert not published


def test_database_failure_does_not_replace_file(scan_fixture, monkeypatch):
    service, runtime, _ = scan_fixture
    monkeypatch.setattr(runtime, 'iter_scan_results', lambda *args, **kwargs: iter([
        {'code': '000001', 'status': 'ok', 'hits': {}, 'outcomes': {'b1': {'status': 'not_matched'}}}]))
    def fail_publish(*args):
        raise OSError('database unavailable')
    monkeypatch.setattr(service, '_write_results_to_sqlite', fail_publish)
    with pytest.raises(OSError, match='database unavailable'):
        service.build_strategy_result_snapshot('2026-10-23', 'b1', run_id='database-test')
    assert service.WEB_STRATEGY_RESULTS_FILE.read_text(encoding='utf-8') == 'previous good snapshot'


def test_published_database_wins_over_stale_file(scan_fixture, monkeypatch):
    service, _, _ = scan_fixture
    expected = {'_run_id': 'published', 'groups': {}, 'results': [], '_authoritative': True}
    monkeypatch.setattr(service.repo, 'get_published_snapshot', lambda cache_file: expected)
    assert service._read_strategy_snapshot() == expected


def test_system_status_uses_same_publication_as_desktop(monkeypatch, tmp_path):
    import json
    from web.backend.services import system_status_service as status
    expected = {'_run_id': 'published', '_authoritative': True, 'groups': {}, 'results': []}
    monkeypatch.setattr(status, 'WEB_STRATEGY_RESULTS_FILE', tmp_path / 'missing.json')
    monkeypatch.setattr(status, '_read_only_db_rows', lambda *args: [{'summary_json': json.dumps(expected)}])
    assert status._read_strategy_snapshot() == expected


@pytest.mark.parametrize('outcome_status,stock_status,hit,count', [
    ('matched', 'ok', None, 1), ('not_matched', 'ok', {'signals': [{'date': '2026-10-23'}]}, 0),
    ('matched', 'ok', {'code': '000002', 'signals': [{'date': '2026-10-23'}]}, 1),
    ('matched', 'ok', {'code': '000001', 'signals': [{'date': '2026-10-23'}]}, 2),
    ('error', 'ok', None, 0),
])
def test_inconsistent_result_is_rejected(scan_fixture, monkeypatch, outcome_status, stock_status, hit, count):
    service, runtime, published = scan_fixture
    row = {'code': '000001', 'status': stock_status,
           'hits': {'b1': {'strategy_name': 'B1CaseStrategy', 'stock_result': hit}} if hit else {},
           'outcomes': {'b1': {'status': outcome_status, 'signal_count': count}}}
    monkeypatch.setattr(runtime, 'iter_scan_results', lambda *args, **kwargs: iter([row]))
    with pytest.raises(RuntimeError, match='不一致'):
        service.build_strategy_result_snapshot('2026-10-23', 'b1', run_id='inconsistent-test')
    assert not published
