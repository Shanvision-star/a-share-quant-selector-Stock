"""每日闭环的日期、防陈旧、持仓边界和中断幂等测试，不调用真实供应商。"""

from datetime import datetime, timezone
import json
import threading
import time

import pytest

from scripts.run_daily_agent import DailyRunner, exclusive_run
from web.backend.services.daily_workflow import latest_closed_day
from web.backend.services.daily_observation import market_snapshot, refresh_observation, verified_market_report
from web.backend.services import sqlite_service as db, workspace_agent as agents, tracking_service as tracking
from web.backend.services.workspace_actions import ActionRequest, TrackingRefreshParameters


def bars(root, latest='2026-10-23'):
    directory = root / 'data/00'
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'000717.csv').write_text('date,open,high,low,close,volume,amount\n'
        f'{latest},10,12,9,11,200,2200\n2026-10-22,9,11,8,10,100,1000\n', encoding='utf-8')


def test_shanghai_cutoff_weekend_and_holiday():
    assert latest_closed_day(datetime(2026, 10, 23, 6, 59, tzinfo=timezone.utc)) == '2026-10-22'
    assert latest_closed_day(datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)) == '2026-10-23'
    assert latest_closed_day(datetime(2026, 10, 24, 11, 0, tzinfo=timezone.utc)) == '2026-10-23'
    assert latest_closed_day(datetime(2026, 10, 1, 11, 0, tzinfo=timezone.utc)) == '2026-09-30'
    with pytest.raises(ValueError):
        latest_closed_day(datetime(2027, 1, 3, tzinfo=timezone.utc))


def test_market_freshness_and_future_exclusion(tmp_path):
    bars(tmp_path)
    snapshot = market_snapshot(tmp_path, '000717', '2026-10-22')
    assert snapshot['total'] == 1 and snapshot['items'][0]['close'] == 10
    with pytest.raises(ValueError, match='未达到'):
        market_snapshot(tmp_path, '000717', '2026-10-26')
    with pytest.raises(ValueError):
        agents.AgentRequest(question='日线', task='market', code='000717')


def test_invalid_market_values_rejected(tmp_path):
    bars(tmp_path)
    path = tmp_path/'data/00/000717.csv'
    path.write_text(path.read_text().replace(',11,200,', ',NaN,200,'))
    with pytest.raises(ValueError, match='数值无效'):
        market_snapshot(tmp_path, '000717', '2026-10-23')


def test_program_computes_window_dates_and_rejects_model_numbers(tmp_path):
    bars(tmp_path)
    data = market_snapshot(tmp_path, '000717', '2026-10-23')
    assert data['metrics']['20']['count'] == 2
    assert data['metrics']['20']['start'] == '2026-10-22'
    source = {'source_id':'S1', 'data':data}
    report = {'summary':'量价存在变化，仍需观察。','findings':[],'next_steps':[],'limitations':[]}
    result = verified_market_report(report, source)
    assert '最近 2 根日线：2026-10-22 至 2026-10-23' in result['findings'][2]['text']
    report['summary'] = '近20个交易日从2026-09-24开始'
    with pytest.raises(ValueError, match='数字'):
        verified_market_report(report, source)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path/'cache.db')
    monkeypatch.setattr(db, '_local', threading.local())
    monkeypatch.setattr(agents, 'ROOT', tmp_path)
    db.init_database()
    agent = agents.WorkspaceAgent()
    agent.store.init()
    monkeypatch.setattr(agents, 'workspace_agent', agent)
    service = tracking.TrackingService()
    monkeypatch.setattr(tracking, 'tracking_service', service)
    monkeypatch.setattr(service, '_compute_tracked_days', lambda *_: 1)
    bars(tmp_path)
    yield agent, service
    agent.pool.shutdown(wait=True)


def completed_market(agent):
    run = agent.submit(agents.AgentRequest(question='每日行情', task='market', mode='local', code='000717', trade_date='2026-10-23'))
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        run = agent.store.get(run['run_id'])
        if run['status'] not in ('queued','running'):
            assert run['status'] == 'completed', run
            return run
        time.sleep(.01)
    pytest.fail('报告没有完成')


@pytest.mark.parametrize('status,entry,quantity', [('watch_buy',None,0), ('holding',10,100)])
def test_observation_does_not_create_fills_and_is_idempotent(environment, status, entry, quantity):
    agent, service = environment
    item = service.create_item({'code':'000717','signal_date':'2026-08-28','name':'中南股份'})
    service._update_item(item['tracking_id'], status=status, entry_price=entry, quantity=quantity)
    run = completed_market(agent)
    agent.save_review(run['run_id'], '2026-10-23')
    result = refresh_observation(item['tracking_id'], run['run_id'], '2026-10-23')
    again = refresh_observation(item['tracking_id'], run['run_id'], '2026-10-23')
    assert result['last_eval_date'] == '2026-10-23' and result['last_close'] == 11
    assert result['status'] == status and result['entry_price'] == entry and result['quantity'] == quantity
    assert result['latest_intent'] is None and again['note'] == result['note']
    assert len([e for e in service.list_events(item['tracking_id']) if e['event_type'] == 'agent_observation']) == 1


def test_observation_requires_saved_report_and_matching_stock(environment):
    agent, service = environment
    item = service.create_item({'code':'000718','signal_date':'2026-08-28'})
    run = completed_market(agent)
    with pytest.raises(ValueError, match='先保存'):
        refresh_observation(item['tracking_id'], run['run_id'], '2026-10-23')
    agent.save_review(run['run_id'], '2026-10-23')
    with pytest.raises(ValueError, match='不匹配'):
        refresh_observation(item['tracking_id'], run['run_id'], '2026-10-23')
    with pytest.raises(ValueError):
        TrackingRefreshParameters(tracking_id=item['tracking_id'], run_id=run['run_id'], review_date='2026-10-23', quantity=100)
    assert ActionRequest(request_id='test', action='tracking_refresh').confirmed is False


class FakeAPI:
    def __init__(self):
        self.run = None
        self.calls = []
        self.note = ''
        self.saved = False
        self.partial = False
        self.fail_save_once = False

    def __call__(self, method, endpoint, payload=None):
        self.calls.append((method, endpoint, payload))
        if method == 'POST' and endpoint == 'agent/actions':
            if payload['action'] == 'update':
                return {'action_id':'update1'}
            self.note = f'[daily-agent:{self.run["run_id"]}]'
            return {'status':'completed','action_id':'observe1'}
        if endpoint == 'agent/actions/update1':
            return {'status':'failed' if self.partial else 'completed', 'action_id':'update1', 'business_id':'business1', 'result':{'trade_date':'2026-10-23','verification_passed':True}, 'update_status':'partial' if self.partial else None}
        if method == 'POST' and endpoint == 'agent/runs':
            self.run = {'run_id':'a'*32, 'status':'completed','input':payload,'sources':[{'tool':'market_daily','data':{'latest_date':'2026-10-23'}}], 'model':'stub','provider':'stub','usage':{},'latency_ms':1,'cost':0}
            return self.run
        if endpoint.endswith('/review'):
            if self.fail_save_once:
                self.fail_save_once = False
                raise ConnectionError('复盘暂不可达')
            self.saved = True
            self.run['saved_review'] = '2026-10-23'
            return {}
        if endpoint.startswith('agent/runs/'):
            return self.run
        if endpoint.startswith('agent/runs?'):
            return {'items':[self.run] if self.run else []}
        if endpoint.startswith('tracking?'):
            return {'data':{'items':[{'tracking_id':'trk_abc','code':'000717','status':'watch_buy'}]}}
        if endpoint.startswith('tracking/'):
            return {'data':{'code':'000717','last_eval_date':'2026-10-23','last_close':11,'note':self.note}}
        if endpoint.startswith('reviews/'):
            return {'data':{'body':f'<!-- agent-run:{self.run["run_id"]} -->' if self.saved else ''}}
        raise AssertionError(endpoint)


CONFIG = {'targets':[{'code':'000717','name':'中南股份'}]}


def test_repeated_complete_does_not_repeat_model_or_review(tmp_path):
    api = FakeAPI()
    DailyRunner(tmp_path, CONFIG, '2026-10-23', api).run()
    DailyRunner(tmp_path, CONFIG, '2026-10-23', api).run()
    assert sum(m == 'POST' and e == 'agent/runs' for m,e,_ in api.calls) == 1
    assert sum(e.endswith('/review') for _,e,_ in api.calls) == 1
    assert json.loads((tmp_path/'data/daily-agent/latest.json').read_text(encoding='utf-8'))['status'] == 'completed'


def test_partial_market_stops_before_model(tmp_path):
    api = FakeAPI()
    api.partial = True
    runner = DailyRunner(tmp_path, CONFIG, '2026-10-23', api)
    with pytest.raises(ValueError, match='全市场未完成'):
        runner.run()
    assert api.run is None and runner.state['status'] == 'failed'


def test_valid_market_cache_hit_still_checks_target_evidence(tmp_path):
    api = FakeAPI()
    def cached(method, endpoint, payload=None):
        value = api(method, endpoint, payload)
        if endpoint == 'agent/actions/update1':
            value['result'].update(verification_passed=False, cache_hit=True)
        return value
    assert DailyRunner(tmp_path, CONFIG, '2026-10-23', cached).run()['status'] == 'completed'


def test_wrong_market_target_date_stops_model(tmp_path):
    api = FakeAPI()
    def old_date(method, endpoint, payload=None):
        value = api(method, endpoint, payload)
        if endpoint == 'agent/actions/update1':
            value['result']['trade_date'] = '2026-10-22'
        return value
    with pytest.raises(ValueError, match='全市场未完成'):
        DailyRunner(tmp_path, CONFIG, '2026-10-23', old_date).run()
    assert api.run is None


def test_resume_after_review_failure_keeps_model_run(tmp_path):
    api = FakeAPI()
    api.fail_save_once = True
    with pytest.raises(ConnectionError):
        DailyRunner(tmp_path, CONFIG, '2026-10-23', api).run()
    DailyRunner(tmp_path, CONFIG, '2026-10-23', api).run()
    assert sum(m == 'POST' and e == 'agent/runs' for m,e,_ in api.calls) == 1


def test_unknown_submission_is_not_blindly_retried(tmp_path):
    api = FakeAPI()
    runner = DailyRunner(tmp_path, CONFIG, '2026-10-23', api)
    runner.state.update(market_complete=True, targets={'000717':{'submitting':True}})
    with pytest.raises(ValueError, match='状态不确定'):
        runner.run()
    assert api.run is None


def test_process_lock_releases_after_exception(tmp_path):
    path = tmp_path/'run.lock'
    with pytest.raises(RuntimeError):
        with exclusive_run(path):
            with pytest.raises(OSError):
                with exclusive_run(path):
                    pass
            raise RuntimeError()
    with exclusive_run(path):
        pass


def test_slow_home_initial_check_does_not_block_agent_read(monkeypatch):
    import asyncio
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from web.backend.routers.update import router
    from web.backend.services import data_service

    entered, release = threading.Event(), threading.Event()
    def slow_files():
        entered.set()
        release.wait(2)
        return []
    monkeypatch.setattr(data_service.csv_manager, 'list_all_stocks', slow_files)
    app = FastAPI()
    app.include_router(router)
    @app.get('/probe')
    async def probe():
        return {'responsive': True}

    async def check():
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            pending = asyncio.create_task(client.get('/api/data/init-status'))
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(.005)
                assert entered.is_set()
                assert not pending.done(), 'slow disk request should still be waiting'
                response = await asyncio.wait_for(client.get('/probe'), timeout=.5)
                assert response.json() == {'responsive': True}
            finally:
                release.set()
                await pending
    asyncio.run(check())
