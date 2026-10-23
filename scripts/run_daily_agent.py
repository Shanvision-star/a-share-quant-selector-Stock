"""全市场更新、目标股研究、复盘和观察跟踪的可恢复每日入口。"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.quant_tools import request
from web.backend.services.daily_workflow import latest_closed_day, SHANGHAI


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)


@contextmanager
def exclusive_run(path: Path):
    """内核文件锁在进程退出时释放，避免遗留 PID 文件阻塞未来每日任务。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if config.get('market_scope') != 'all' or not config.get('targets'):
        raise ValueError('配置需要全市场更新范围和至少一只目标股票')
    codes = set()
    for target in config['targets']:
        if not re.fullmatch(r'\d{6}', target.get('code', '')) or target['code'] in codes:
            raise ValueError('目标股票必须是无重复的六位代码')
        codes.add(target['code'])
    if len(codes) > 20:
        raise ValueError('单次最多分析20只目标股票')
    return config


class DailyRunner:
    """阶段完成后持久化，未知提交状态不自动重新调用模型。"""

    def __init__(self, root: Path, config: dict, target: str, api=request, pause=time.sleep):
        self.root, self.config, self.target, self.api, self.pause = root, config, target, api, pause
        digest = hashlib.sha256(json.dumps({'version':2,'targets':config['targets']}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
        self.path = root / 'data/daily-agent' / f'{target}-{digest}.json'
        self.state = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'workflow_version': 2, 'target_date': target, 'status': 'pending', 'stage': 'market',
            'review_date': target, 'market_scope': 'all', 'targets': {}, 'market_attempt': 1,
            'created_at': datetime.now(SHANGHAI).isoformat()}

    def save(self, **changes):
        self.state.update(changes, updated_at=datetime.now(SHANGHAI).isoformat())
        atomic_json(self.path, self.state)
        atomic_json(self.root/'data/daily-agent/latest.json', self.state)

    def poll(self, endpoint: str, timeout: int, kind: str) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            item = self.api('GET', endpoint)
            if kind == 'market':
                self.state['market'] = {key: item.get(key) for key in ('action_id','business_id','status','result','error','update_status')}
                self.save()
            if item['status'] not in ('queued', 'running', 'cancel_requested'):
                return item
            if time.monotonic() >= deadline:
                raise TimeoutError(f'{kind} 等待超时；保留已有任务编号，后续从同一任务恢复')
            self.pause(5 if kind == 'market' else 1)

    def market(self):
        self.save(stage='market')
        attempt = self.state['market_attempt']
        key = f'daily-{self.target}-market-{attempt}'
        action = self.api('POST', 'agent/actions', {'request_id': key, 'action': 'update', 'confirmed': True,
            'parameters': {'target_date': self.target, 'auto_rebuild': False, 'pipeline': False,
                           'allow_intraday_fast': False, 'init_if_empty': False}})
        self.state['market_action_id'] = action['action_id']
        self.save()
        action = self.poll(f'agent/actions/{action["action_id"]}', int(self.config.get('market_timeout_seconds', 14400)), 'market')
        result = action.get('result') or {}
        verified = (result.get('verification_passed') is True or result.get('cache_hit') is True
                    or (result.get('scan_total', 0) > 0 and result.get('up_to_date') == result['scan_total'] and result.get('remaining') == 0))
        if (action['status'] != 'completed' or action.get('update_status') in ('partial', 'error')
                or (result.get('target_date') or result.get('trade_date')) != self.target
                or result.get('failed', 0) or not verified):
            raise ValueError(f'全市场未完成目标日更新：{action["status"]}；{action.get("error") or result.get("message", "日期或验证不符")}')
        self.state['market_complete'] = True
        self.save()

    def research(self, target: dict, record: dict):
        code = target['code']
        question = (f'每日收盘研究 v2 {self.target}：{target.get("name", "")}({code})。仅依据实际日线与程序计算的metrics，'
                    '定性分析最近价格变化、波动和成交量变化。数字和日期由程序呈现，你的正文不输出阿拉伯数字或自行计算区间。'
                    '区分事实、推断和待观察条件，不虚构策略命中、持仓或成交，不提供具体下单数量。输出后续观察要点。')
        if not record.get('run_id'):
            # 提交前写标记；网络断开时通过完全相同的问题恢复运行，不能盲目再次付费。
            if record.get('submitting'):
                recent = self.api('GET', 'agent/runs?limit=100')['items']
                found = [run for run in recent if run['input'].get('question') == question and run['input'].get('code') == code and run['input'].get('trade_date') == self.target]
                if len(found) != 1:
                    raise ValueError(f'{code} 模型提交状态不确定，需要核对运行历史后恢复')
                record['run_id'] = found[0]['run_id']
            else:
                record['submitting'] = True
                self.save()
                run = self.api('POST', 'agent/runs', {'question': question, 'task': 'market', 'mode': 'model',
                    'code': code, 'trade_date': self.target, 'limit': 50})
                record['run_id'] = run['run_id']
            record['submitting'] = False
            self.save()
        run = self.poll('agent/runs/' + record['run_id'], int(self.config.get('agent_timeout_seconds', 240)), 'agent')
        if run['status'] != 'completed':
            raise ValueError(f'{code} 模型运行{run["status"]}：{run.get("error")}')
        sources = [s for s in run['sources'] if s['tool'] == 'market_daily']
        if len(sources) != 1 or sources[0]['data']['latest_date'] != self.target:
            raise ValueError('模型来源未达到目标交易日')
        record.update(model=run['model'], provider=run['provider'], usage=run['usage'], latency_ms=run['latency_ms'], cost=run['cost'])
        self.save()

    def tracking(self, target: dict, record: dict):
        items = self.api('GET', f'tracking?code={target["code"]}')['data']['items']
        items = [item for item in items if item['status'] != 'closed']
        specified = target.get('tracking_id')
        if specified:
            items = [item for item in items if item['tracking_id'] == specified]
            if not items:
                raise ValueError(f'{target["code"]} 指定跟踪不存在或已结束')
        if len(items) > 1:
            raise ValueError(f'{target["code"]} 有多个活跃跟踪，请在配置指定 tracking_id')
        if not items:
            created = self.api('POST', 'agent/actions', {'request_id': f'daily-{self.target}-{target["code"]}-create',
                'action': 'tracking', 'confirmed': True, 'parameters': {'code': target['code'], 'name': target.get('name',''),
                    'signal_date': self.target, 'source': 'daily_agent', 'note': '每日观察；未登记成交'}})
            if created['status'] != 'completed':
                raise ValueError('跟踪创建未完成')
            items = [created['result']]
        tracking_id = items[0]['tracking_id']
        action = self.api('POST', 'agent/actions', {'request_id': f'daily-{record["run_id"]}-observe',
            'action': 'tracking_refresh', 'confirmed': True, 'parameters': {'tracking_id': tracking_id,
            'run_id': record['run_id'], 'review_date': self.target}})
        if action['status'] != 'completed':
            raise ValueError(f'观察刷新未完成：{action.get("error")}')
        record.update(tracking_id=tracking_id, tracking_action_id=action['action_id'])
        self.save()

    def verify(self, target: dict, record: dict):
        run = self.api('GET', 'agent/runs/' + record['run_id'])
        review = self.api('GET', 'reviews/' + self.target)['data']
        item = self.api('GET', 'tracking/' + record['tracking_id'])['data']
        if (run['status'] != 'completed' or run.get('saved_review') != self.target
                or f'<!-- agent-run:{run["run_id"]} -->' not in review['body']
                or item['code'] != target['code'] or item['last_eval_date'] != self.target
                or f'[daily-agent:{run["run_id"]}]' not in item['note']):
            raise ValueError('桌面共用 API 回读结果不一致')
        record.update(status='completed', submitting=False, latest_close=item['last_close'], verified_at=datetime.now(SHANGHAI).isoformat())
        self.save()

    def run(self):
        self.save(status='running', error=None, error_type=None)
        try:
            if not self.state.get('market_complete'):
                self.market()
            for target in self.config['targets']:
                code = target['code']
                record = self.state['targets'].setdefault(code, {'name': target.get('name', '')})
                if record.get('status') == 'completed':
                    self.verify(target, record)
                    continue
                self.save(stage=f'agent:{code}')
                self.research(target, record)
                self.save(stage=f'review:{code}')
                self.api('POST', f'agent/runs/{record["run_id"]}/review', {'review_date': self.target, 'confirmed': True})
                self.save(stage=f'tracking:{code}')
                self.tracking(target, record)
                self.verify(target, record)
            self.save(status='completed', stage='verified', completed_at=self.state.get('completed_at') or datetime.now(SHANGHAI).isoformat())
        except Exception as exc:
            self.save(status='failed', error=str(exc)[:600], error_type=type(exc).__name__)
            raise
        return self.state


def ensure_desktop():
    """优先连接现有实例；缺少服务时用已安装桌面启动同一持久工作区。"""
    try:
        request('GET', 'agent/capabilities')
        return
    except Exception:
        pass
    executable = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/A-share Quant/A-share Quant.exe'
    if not executable.exists():
        raise ValueError('未找到已安装桌面，请先安装 Windows 桌面版')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    env = {**os.environ, 'QUANT_WORKSPACE': str(ROOT)}
    for key in ('PYTHONHOME', 'PYTHONPATH', 'ELECTRON_RUN_AS_NODE'):
        env.pop(key, None)
    subprocess.Popen([str(executable)], cwd=ROOT, env=env, startupinfo=startup)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        time.sleep(1)
        try:
            request('GET', 'agent/capabilities')
            return
        except Exception:
            continue
    raise TimeoutError('桌面后端未在90秒内就绪')


async def verify_codex_mcp(state: dict):
    """按真实 Codex 配置启动 stdio 工具，并回读同一批正式报告。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    config = tomllib.loads((Path.home()/'.codex/config.toml').read_text(encoding='utf-8'))['mcp_servers']['ashare_quant']
    parameters = StdioServerParameters(command=config['command'], args=config.get('args', []), env={**os.environ, **config.get('env', {})})
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            async def call(name, args=None):
                response = await client.call_tool(name, args or {})
                if response.isError:
                    raise ValueError(f'Codex MCP {name} 回读失败')
                return response.structuredContent or json.loads(response.content[0].text)
            daily = await call('quant_daily_status')
            if daily['target_date'] != state['target_date']:
                raise ValueError('Codex MCP 连接的每日记录与当前工作区不一致')
            for code, target in state['targets'].items():
                if daily['targets'].get(code, {}).get('run_id') != target['run_id']:
                    raise ValueError('Codex MCP 读到了不同的目标报告')
                run = await call('quant_run', {'run_id':target['run_id']})
                if run['status'] != 'completed' or run['input']['trade_date'] != state['target_date'] or run.get('saved_review') != state['review_date']:
                    raise ValueError('Codex MCP 报告、日期或复盘关联不一致')


def main():
    parser = argparse.ArgumentParser(description='每日全市场更新与目标股研究闭环')
    parser.add_argument('--config', type=Path, default=ROOT/'config/daily-agent.json')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--retry-market', action='store_true', help='只在已确认失败后重试行情，不重放模型')
    args = parser.parse_args()
    os.environ['QUANT_RUNTIME_FILE'] = str(ROOT/'data/desktop-runtime.json')
    for key in ('QUANT_API_URL', 'QUANT_API_TOKEN'):
        os.environ.pop(key, None)
    from web.backend.services.daily_workflow import read_daily_status
    if args.status:
        print(json.dumps(read_daily_status(ROOT), ensure_ascii=False, indent=2))
        return
    config = load_config(args.config)
    if not config.get('enabled'):
        print(json.dumps({'status': 'disabled'}))
        return
    with exclusive_run(ROOT/'data/daily-agent/run.lock'):
        runner = DailyRunner(ROOT, config, latest_closed_day())
        ensure_desktop()
        if args.retry_market:
            market = runner.state.get('market') or {}
            if market.get('status') not in ('failed', 'interrupted') or runner.state.get('market_complete'):
                raise ValueError('只允许重试已经确认失败的全市场更新')
            runner.state['market_attempt'] += 1
            runner.save()
        result = runner.run()
        try:
            asyncio.run(asyncio.wait_for(verify_codex_mcp(result), timeout=60))
            runner.save(mcp_verified_at=datetime.now(SHANGHAI).isoformat())
        except Exception as exc:
            runner.save(status='failed', stage='mcp_verification', error=str(exc)[:600])
            raise
        print(json.dumps(runner.state, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': str(error)[:600]}, ensure_ascii=False))
        sys.exit(1)
