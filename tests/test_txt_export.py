import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.backend.routers import strategy, txt_export
from web.backend.services import strategy_result_repository as repo


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(strategy.router)
    app.include_router(txt_export.router)
    return app


def _memory_strategy_db():
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE strategy_runs (
            run_id TEXT PRIMARY KEY,
            run_type TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            strategy_filter TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'done',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            stage TEXT,
            message TEXT,
            processed_count INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            matched_count INTEGER DEFAULT 0,
            error_message TEXT,
            host TEXT
        );
        CREATE TABLE strategy_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            strategy_filter TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            category TEXT,
            signal_date TEXT,
            trigger_price REAL,
            close REAL,
            j_value REAL,
            similarity_score REAL,
            reason TEXT,
            signal_json TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    return conn


def _insert_result(conn, *, run_id, trade_date, strategy_filter, signal_date, code, category='signal'):
    existing = conn.execute("SELECT 1 FROM strategy_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO strategy_runs
               (run_id, run_type, trade_date, strategy_filter, status, started_at, completed_at)
               VALUES (?, 'rebuild_only', ?, ?, 'done', '2026-05-06 16:00:00', '2026-05-06 16:01:00')""",
            (run_id, trade_date, strategy_filter),
        )
    conn.execute(
        """INSERT INTO strategy_results
           (run_id, trade_date, strategy_filter, strategy_name, code, name, category,
            signal_date, trigger_price, close, j_value, similarity_score, reason, signal_json, created_at)
           VALUES (?, ?, ?, ?, ?, '测试股票', ?,
                   ?, 10, 10, 12, NULL, 'signal', NULL, '2026-05-06 16:01:00')""",
        (run_id, trade_date, strategy_filter, f"{strategy_filter.upper()}Strategy", code, category, signal_date),
    )
    conn.commit()


def test_strategy_dates_endpoint_returns_signal_dates_filtered_by_strategy(monkeypatch):
    conn = _memory_strategy_db()
    monkeypatch.setattr(repo, 'get_connection', lambda: conn)
    _insert_result(
        conn,
        run_id='run-b1',
        trade_date='2026-05-06',
        strategy_filter='b1',
        signal_date='2026-05-06',
        code='000002',
    )
    _insert_result(
        conn,
        run_id='run-b2',
        trade_date='2026-05-06',
        strategy_filter='b2',
        signal_date='2026-04-30',
        code='000001',
    )

    response = TestClient(_build_test_app()).get(
        '/api/strategy/results/dates',
        params={'limit': 5, 'strategy': 'b2'},
    )

    assert response.status_code == 200
    assert response.json()['data'] == ['2026-04-30']


def test_txt_generate_without_date_uses_latest_signal_date_for_strategy(monkeypatch, tmp_path):
    conn = _memory_strategy_db()
    monkeypatch.setattr(repo, 'get_connection', lambda: conn)
    monkeypatch.setattr(txt_export, 'TXT_WEB_DIR', tmp_path)
    _insert_result(
        conn,
        run_id='run-b2',
        trade_date='2026-05-06',
        strategy_filter='b2',
        signal_date='2026-04-30',
        code='000001',
    )

    response = TestClient(_build_test_app()).post(
        '/api/txt/generate',
        params={'strategy': 'b2'},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['success'] is True
    assert payload['data']['date'] == '2026-04-30'
    assert payload['data']['filename'] == 'tdx_web_b2_20260430.txt'
    assert (tmp_path / 'tdx_web_b2_20260430.txt').read_text(encoding='utf-8') == 'SZ000001'


def test_txt_summary_reports_per_strategy_and_cross_strategy_overlap(monkeypatch):
    conn = _memory_strategy_db()
    monkeypatch.setattr(repo, 'get_connection', lambda: conn)
    _insert_result(
        conn,
        run_id='run-b1',
        trade_date='2026-05-06',
        strategy_filter='b1',
        signal_date='2026-04-30',
        code='000001',
        category='b1_setup',
    )
    _insert_result(
        conn,
        run_id='run-b1',
        trade_date='2026-05-06',
        strategy_filter='b1',
        signal_date='2026-04-30',
        code='000001',
        category='b1_confirm',
    )
    _insert_result(
        conn,
        run_id='run-b2',
        trade_date='2026-05-06',
        strategy_filter='b2',
        signal_date='2026-04-30',
        code='000001',
    )
    _insert_result(
        conn,
        run_id='run-bowl',
        trade_date='2026-05-06',
        strategy_filter='bowl',
        signal_date='2026-04-30',
        code='000002',
    )
    _insert_result(
        conn,
        run_id='run-brick',
        trade_date='2026-05-06',
        strategy_filter='brick',
        signal_date='2026-04-30',
        code='000003',
    )

    response = TestClient(_build_test_app()).get(
        '/api/txt/summary',
        params={'date': '2026-04-30'},
    )

    assert response.status_code == 200
    payload = response.json()['data']
    assert payload['date'] == '2026-04-30'
    assert payload['signal_total'] == 5
    assert payload['unique_code_total'] == 3
    assert payload['cross_strategy_overlap_count'] == 1
    assert payload['strategies'][0] == {
        'strategy': 'b1',
        'strategy_label': 'B1形态',
        'signal_total': 2,
        'unique_code_total': 1,
        'overlap_signal_count': 1,
    }
    assert payload['strategies'][1]['strategy'] == 'b2'
    assert payload['strategies'][1]['unique_code_total'] == 1
    assert payload['strategies'][2]['strategy'] == 'bowl'
    assert payload['strategies'][2]['unique_code_total'] == 1
    assert payload['strategies'][3]['strategy'] == 'brick'
    assert payload['strategies'][3]['strategy_label'] == '砖型图'
    assert payload['strategies'][3]['unique_code_total'] == 1


def test_txt_generate_batch_creates_each_strategy_and_deduped_all_file(monkeypatch, tmp_path):
    conn = _memory_strategy_db()
    monkeypatch.setattr(repo, 'get_connection', lambda: conn)
    monkeypatch.setattr(txt_export, 'TXT_WEB_DIR', tmp_path)
    _insert_result(
        conn,
        run_id='run-b1',
        trade_date='2026-05-06',
        strategy_filter='b1',
        signal_date='2026-04-30',
        code='000001',
    )
    _insert_result(
        conn,
        run_id='run-b2',
        trade_date='2026-05-06',
        strategy_filter='b2',
        signal_date='2026-04-30',
        code='000001',
    )
    _insert_result(
        conn,
        run_id='run-bowl',
        trade_date='2026-05-06',
        strategy_filter='bowl',
        signal_date='2026-04-30',
        code='000002',
    )
    _insert_result(
        conn,
        run_id='run-brick',
        trade_date='2026-05-06',
        strategy_filter='brick',
        signal_date='2026-04-30',
        code='000003',
    )

    response = TestClient(_build_test_app()).post(
        '/api/txt/generate-batch',
        params={'date': '2026-04-30'},
    )

    assert response.status_code == 200
    payload = response.json()['data']
    assert [item['strategy'] for item in payload['files']] == ['b1', 'b2', 'bowl', 'brick', 'all']
    assert payload['summary']['unique_code_total'] == 3
    assert payload['summary']['cross_strategy_overlap_count'] == 1
    assert (tmp_path / 'tdx_web_b1_20260430.txt').read_text(encoding='utf-8') == 'SZ000001'
    assert (tmp_path / 'tdx_web_b2_20260430.txt').read_text(encoding='utf-8') == 'SZ000001'
    assert (tmp_path / 'tdx_web_bowl_20260430.txt').read_text(encoding='utf-8') == 'SZ000002'
    assert (tmp_path / 'tdx_web_brick_20260430.txt').read_text(encoding='utf-8') == 'SZ000003'
    assert (tmp_path / 'tdx_web_all_20260430.txt').read_text(encoding='utf-8') == 'SZ000001\nSZ000002\nSZ000003'
