"""验证权威扫描快照原子发布、零命中替换和旧版查询兼容性。"""

import sqlite3

import pytest

from web.backend.services import sqlite_service as db
from web.backend.services import strategy_result_repository as repo


@pytest.fixture
def connection(monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(db, 'get_connection', lambda: conn)
    monkeypatch.setattr(repo, 'get_connection', lambda: conn)
    db.init_database()
    yield conn
    conn.close()


def _row(run_id, code='000001', sf='b1', date='2026-10-23'):
    return {'run_id': run_id, 'trade_date': date, 'strategy_filter': sf,
            'strategy_name': sf.upper(), 'code': code, 'signal_date': date,
            'category': 'signal', 'close': 10.0}


def _snapshot(run_id, batch, groups=('b1', 'b2'), date='2026-10-23'):
    return {'trade_date': date, '_run_id': run_id, 'total': len(batch),
            'available_groups': list(groups), 'results': batch,
            'groups': {sf: {'total': sum(row['strategy_filter'] == sf for row in batch)} for sf in groups}}


def _publish(run_id, batch, cache_file, **kwargs):
    snapshot = _snapshot(run_id, batch, **kwargs)
    repo.publish_snapshot(run_id, snapshot['trade_date'], 'all', batch, snapshot, cache_file)
    return snapshot


def test_authoritative_run_removes_old_hits_without_deleting_history(connection, tmp_path):
    repo.insert_results_batch([_row('old', '000001'), _row('old', '000002')])
    _publish('new', [_row('new', '000002')], tmp_path / 'cache.json')
    assert repo.query_unique_codes(trade_date='2026-10-23') == ['000002']
    assert repo.query_results(trade_date='2026-10-23')['total'] == 1
    assert connection.execute("SELECT COUNT(*) FROM strategy_results WHERE run_id='old'").fetchone()[0] == 2


def test_zero_hit_publication_suppresses_previous_hits_and_keeps_group_completeness(connection, tmp_path):
    repo.insert_results_batch([_row('old', '000001', sf='b2')])
    _publish('empty', [], tmp_path / 'cache.json')
    assert repo.query_results(trade_date='2026-10-23')['total'] == 0
    assert repo.get_available_trade_dates() == []
    summary = repo.get_result_summary_for_date('2026-10-23')
    assert summary['available_groups'] == ['b1', 'b2']
    assert summary['group_totals'] == {'b1': 0, 'b2': 0}


def test_publication_rolls_back_results_and_snapshot_together(connection, monkeypatch, tmp_path):
    cache_file = tmp_path / 'cache.json'
    _publish('same-run', [_row('same-run', '000001')], cache_file)
    original_save = repo.save_snapshot

    def fail_after_snapshot(*args, **kwargs):
        original_save(*args, **kwargs)
        raise RuntimeError('injected snapshot failure')

    monkeypatch.setattr(repo, 'save_snapshot', fail_after_snapshot)
    with pytest.raises(RuntimeError, match='injected'):
        _publish('same-run', [_row('same-run', '000002')], cache_file)
    assert repo.query_unique_codes() == ['000001']
    assert repo.get_published_snapshot(cache_file)['results'][0]['code'] == '000001'
    assert connection.execute('SELECT COUNT(*) FROM strategy_cache_snapshots').fetchone()[0] == 1


def test_republishing_same_run_replaces_entire_batch(connection, tmp_path):
    cache_file = tmp_path / 'cache.json'
    _publish('run', [_row('run', '000001'), _row('run', '000002', sf='b2')], cache_file)
    _publish('run', [_row('run', '000003', sf='b2')], cache_file)
    assert repo.query_unique_codes() == ['000003']
    assert repo.query_results(strategy_filter='b1')['total'] == 0
    assert repo.get_published_snapshot(cache_file)['results'][0]['code'] == '000003'


def test_latest_published_snapshot_is_scoped_by_cache_path(connection, tmp_path):
    cache_a, cache_b = tmp_path / 'a.json', tmp_path / 'b.json'
    _publish('first', [_row('first')], cache_a)
    _publish('second', [], cache_b)
    assert repo.get_published_snapshot(cache_a)['_run_id'] == 'first'
    assert repo.get_published_snapshot(cache_b)['_run_id'] == 'second'
    assert repo.get_published_snapshot(tmp_path / 'missing.json') is None


def test_partial_strategy_publication_preserves_other_group_authority(connection, tmp_path):
    cache_file = tmp_path / 'cache.json'
    _publish('first', [_row('first'), _row('first', '000002', sf='b2')], cache_file)
    _publish('b1-only', [], cache_file, groups=('b1',))
    assert repo.query_unique_codes(strategy_filter='b1') == []
    assert repo.query_unique_codes(strategy_filter='b2') == ['000002']


def test_legacy_snapshot_does_not_hide_legacy_results(connection):
    repo.insert_results_batch([_row('old', '000001'), _row('new', '000002')])
    repo.save_snapshot('new', '2026-10-23', 'all', 1, ['b1'], {'b1': 1})
    assert repo.query_unique_codes() == ['000001', '000002']


def test_publication_rejects_mixed_run_or_date_batch(connection, tmp_path):
    with pytest.raises(ValueError):
        _publish('run', [_row('different-run')], tmp_path / 'cache.json')
    assert connection.execute('SELECT COUNT(*) FROM strategy_results').fetchone()[0] == 0


def test_invalidating_cache_preserves_history_but_hides_old_current_snapshot(connection, tmp_path):
    cache_file = tmp_path / 'cache.json'
    _publish('first', [_row('first')], cache_file)
    _publish('second', [_row('second', '000002')], cache_file)
    repo.invalidate_published_snapshots(cache_file)
    assert repo.get_published_snapshot(cache_file) is None
    assert repo.query_unique_codes() == ['000002']
    assert repo.get_latest_snapshot()['summary']['_invalidated'] is True
    _publish('third', [_row('third', '000003')], cache_file)
    assert repo.get_published_snapshot(cache_file)['_run_id'] == 'third'


def test_json_serialization_failure_rolls_back_batch_replacement(connection, tmp_path):
    cache_file = tmp_path / 'cache.json'
    _publish('run', [_row('run')], cache_file)
    rows = [_row('run', '000002')]
    snapshot = _snapshot('run', rows)
    snapshot['invalid_value'] = object()
    with pytest.raises(TypeError):
        repo.publish_snapshot('run', '2026-10-23', 'all', rows, snapshot, cache_file)
    assert repo.query_unique_codes() == ['000001']
    assert repo.get_published_snapshot(cache_file)['results'][0]['code'] == '000001'
