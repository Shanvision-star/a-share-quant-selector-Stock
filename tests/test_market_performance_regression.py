"""行情日期检测与指标加速的等价性回归，不调用真实行情提供方。"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from utils.csv_manager import CSVManager
from utils.technical import KDJ
from strategy.brick_pattern import _tdx_sma


def _reference_kdj(df, n, m1, m2):
    """冻结加速前的标量公式，检查初始化、NaN 传播和正倒序。"""
    descending = df['date'].iloc[0] > df['date'].iloc[-1]
    calc = df.iloc[::-1].reset_index(drop=True) if descending else df.reset_index(drop=True)
    lo = calc['low'].rolling(n, min_periods=1).min()
    hi = calc['high'].rolling(n, min_periods=1).max()
    k, d = [50.0], [50.0]
    for i in range(1, len(calc)):
        rsv = 50.0 if i < n - 1 or hi.iloc[i] == lo.iloc[i] else (
            (calc['close'].iloc[i] - lo.iloc[i]) / (hi.iloc[i] - lo.iloc[i]) * 100
        )
        k.append((rsv + k[-1] * (m1 - 1)) / m1)
        d.append((k[-1] + d[-1] * (m2 - 1)) / m2)
    result = pd.DataFrame({'K': k, 'D': d})
    result['J'] = 3 * result['K'] - 2 * result['D']
    if descending:
        result = result.iloc[::-1].reset_index(drop=True)
    result.index = df.index
    return result


@pytest.mark.parametrize('descending', [False, True])
@pytest.mark.parametrize('case', ['random', 'flat', 'missing', 'short'])
@pytest.mark.parametrize('params', [(9, 3, 3), (5, 2, 4)])
def test_kdj_preserves_exact_scalar_formula(descending, case, params):
    rng = np.random.default_rng(42)
    close = rng.uniform(10, 30, 60)
    df = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=60),
                       'close': close, 'low': close - 1, 'high': close + 2})
    if case == 'flat':
        df[['close', 'low', 'high']] = 10.0
    elif case == 'missing':
        df.loc[20:22, ['close', 'low', 'high']] = np.nan
    elif case == 'short':
        df = df.head(1)
    if descending:
        df = df.iloc[::-1]
    df.index = pd.Index([f'row-{i}' for i in range(len(df))])
    pd.testing.assert_frame_equal(KDJ(df, *params), _reference_kdj(df, *params), check_exact=True)


def test_brick_sma_keeps_missing_value_policy_and_index():
    values = pd.Series([None, 20, 40, np.nan, -10, 100], index=list('abcdef'))
    expected, previous = [], 0.0
    for value in [0.0, 20.0, 40.0, 0.0, -10.0, 100.0]:
        previous = (value + previous * 5) / 6
        expected.append(previous)
    pd.testing.assert_series_equal(_tdx_sma(values, 6, 1), pd.Series(expected, index=values.index), check_exact=True)
    assert _tdx_sma(pd.Series(dtype=float), 4, 1).empty


@pytest.mark.parametrize('value,expected', [
    ('2026-10-23', date(2026, 10, 23)),
    ('2026-10-23 12:23:45.123456', date(2026, 10, 23)),
    ('001', None), ('20261023', None), ('2026-99-01', None), ('', None),
])
def test_header_date_read_handles_mixed_dates_and_bad_rows(tmp_path, value, expected):
    cm = CSVManager(tmp_path)
    path = cm.get_stock_path('000001')
    path.write_text(f'close,date\n10,"{value}"\n9,2020-01-01\n', encoding='utf-8-sig')
    assert cm.read_latest_date('000001') == expected
    assert cm.read_latest_date('999999') is None


@pytest.mark.parametrize('dates,expected_state,current,invalid', [
    ([date(2026, 10, 23)] * 99 + [date(2026, 7, 16)], 'ready', 99, 0),
    ([date(2026, 7, 16)] * 100, 'stale', 0, 0),
    ([None] * 100, 'stale', 0, 100),
    ([date(2026, 10, 24)] * 100, 'stale', 0, 100),
    ([], 'empty', 0, 0),
])
def test_init_status_does_not_extrapolate_one_old_stock(monkeypatch, dates, expected_state, current, invalid):
    from web.backend.routers.update import get_init_status
    from web.backend.services import data_service, strategy_service
    monkeypatch.setattr(data_service.csv_manager, 'list_all_stocks', lambda: list(range(len(dates))))
    monkeypatch.setattr(data_service.csv_manager, 'read_latest_date', lambda code: dates[code])
    monkeypatch.setattr(strategy_service, 'get_latest_trade_date', lambda: '2026-10-23')
    first = get_init_status()['data']
    assert first == get_init_status()['data']
    assert first['state'] == expected_state
    assert first.get('current_count', 0) == current
    assert first.get('invalid_count', 0) == invalid


@pytest.mark.parametrize('endpoint', ['/api/data/status', '/api/system/status', '/api/strategy/cache/status'])
def test_status_disk_io_does_not_block_other_requests(monkeypatch, endpoint):
    import asyncio
    import threading
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from web.backend.routers import update, system_status, strategy
    from web.backend.services import data_service, strategy_service
    entered, release = threading.Event(), threading.Event()
    def slow_read(*args):
        entered.set()
        release.wait(2)
        return {}
    monkeypatch.setattr(data_service, 'get_data_status', slow_read)
    monkeypatch.setattr(strategy_service, 'get_strategy_cache_status', slow_read)
    monkeypatch.setattr(system_status.system_status_service, 'build_status', slow_read)
    app = FastAPI()
    for router in (update.router, system_status.router, strategy.router):
        app.include_router(router)
    @app.get('/probe')
    async def probe():
        return {'ok': True}
    async def check():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            pending = asyncio.create_task(client.get(endpoint))
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(.005)
                assert entered.is_set() and not pending.done()
                response = await asyncio.wait_for(client.get('/probe'), timeout=.5)
                assert response.json() == {'ok': True}
            finally:
                release.set()
                await pending
    asyncio.run(check())
