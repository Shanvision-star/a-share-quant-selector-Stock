"""验证扫描调度的取消、输入冻结和完整性边界。"""
import threading

import pytest


def test_cancelled_scan_never_starts_computation(monkeypatch):
    from web.backend.services import strategy_scan as scan
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(scan.ScanCancelled):
        list(scan.iter_scan_results(['000001'], {}, [], '2026-10-23', cancel_event=stopped))


def test_market_lease_blocks_other_jobs_but_allows_same_run():
    from web.backend.services import strategy_scan as scan
    with scan.market_job('update-1', 'update'):
        with scan.market_job('update-1', 'scan'):
            assert scan.active_scan_status()[0]['id'] == 'update-1'
        with pytest.raises(scan.ScanBusy):
            with scan.market_job('attack-2', 'attack'):
                pass
    assert scan.active_scan_status() == []


def test_cancel_active_signals_owner():
    from web.backend.services import strategy_scan as scan
    with scan.market_job('cancel-test', 'scan') as cancelled:
        assert scan.cancel_active_scans() == ['cancel-test']
        assert cancelled.is_set()


def test_duplicate_stock_codes_rejected():
    from web.backend.services import strategy_scan as scan
    with pytest.raises(ValueError, match='重复'):
        list(scan.iter_scan_results(['000001', '000001'], {}, [], '2026-10-23', backend='serial'))


def test_input_digest_detects_same_size_same_timestamp_edits(tmp_path):
    from web.backend.services import strategy_scan as scan
    import os
    path = tmp_path / 'bar.csv'
    path.write_bytes(b'close\n10\n')
    stamp = path.stat()
    before = scan.file_manifest([path])
    path.write_bytes(b'close\n11\n')
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert before != scan.file_manifest([path])


def test_serial_keeps_explicit_error_outcomes(monkeypatch):
    from web.backend.services import strategy_scan as scan, strategy_service as service
    expected = {'code': '000001', 'status': 'error', 'hits': {}, 'outcomes': {'b1': {'status': 'error'}}}
    monkeypatch.setattr(service, '_process_one_stock', lambda *args: expected)
    assert list(scan.iter_scan_results(['000001'], {}, [], '2026-10-23', backend='serial')) == [expected]


def test_process_pool_failure_is_not_converted_to_empty_results(monkeypatch):
    from web.backend.services import strategy_scan as scan
    def broken_pool(**kwargs):
        raise OSError('worker cannot start')
    monkeypatch.setattr(scan, 'ProcessPoolExecutor', broken_pool)
    with pytest.raises(OSError, match='worker cannot start'):
        list(scan.iter_scan_results(['000001'], {}, [], '2026-10-23'))
