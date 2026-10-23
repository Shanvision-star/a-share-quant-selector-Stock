"""每日研究的日线取证与观察刷新，不推进持仓或生成交易意图。"""

import csv
from datetime import date, datetime
import json
import hashlib
import math
import re
from pathlib import Path

from .sqlite_service import get_connection


def market_snapshot(root: Path, code: str, target: str, limit: int = 50) -> dict:
    """只读取目标日及以前的真实日线，缺少目标日时拒绝冒充最新数据。"""
    date.fromisoformat(target)
    path = root / 'data' / code[:2] / f'{code}.csv'
    rows = {}
    with path.open(encoding='utf-8-sig', newline='') as stream:
        for raw in csv.DictReader(stream):
            day = raw.get('date', '')[:10]
            try:
                date.fromisoformat(day)
            except ValueError:
                continue
            if day > target:
                continue
            bar = {'code': code, 'trade_date': day}
            for field in ('open', 'high', 'low', 'close', 'volume'):
                value = float(raw[field])
                if not math.isfinite(value) or value < 0 or (field in ('open', 'high', 'low', 'close') and value == 0):
                    raise ValueError(f'{code} 日线数值无效：{day}/{field}')
                bar[field] = value
            if bar['low'] > min(bar['open'], bar['close']) or bar['high'] < max(bar['open'], bar['close']):
                raise ValueError(f'{code} OHLC 范围无效：{day}')
            rows[day] = bar
    latest = max(rows, default=None)
    if latest != target:
        raise ValueError(f'{code} 行情未达到目标交易日 {target}，实际 {latest or "无数据"}')
    selected = [rows[day] for day in sorted(rows, reverse=True)[:limit]]
    metrics = {}
    for count in (5, 20):
        window = selected[:count]
        metrics[str(count)] = {'count': len(window), 'start': window[-1]['trade_date'], 'end': window[0]['trade_date'],
            'close_min': min(bar['close'] for bar in window), 'close_max': max(bar['close'] for bar in window),
            'high': max(bar['high'] for bar in window), 'low': min(bar['low'] for bar in window),
            'first_close': window[-1]['close'], 'last_close': window[0]['close'],
            'interval_change_pct': round((window[0]['close']/window[-1]['close']-1)*100, 2)}
    latest_bar = selected[0]
    span = latest_bar['high'] - latest_bar['low']
    metrics['close_position'] = round((latest_bar['close']-latest_bar['low'])/span, 4) if span else None
    metrics['close_position_label'] = '区间上部' if span and metrics['close_position'] >= .75 else '区间下部' if span and metrics['close_position'] <= .25 else '区间中部或无振幅'
    return {'code': code, 'latest_date': latest, 'total': len(rows), 'items': selected,
            'metrics': metrics,
            'limit': limit, 'price_basis': '原项目 CSV 口径，未在研究阶段变更复权',
            'volume_basis': '原CSV成交量，仅用于同一股票同口径比较；成交额单位未核验，不纳入分析',
            'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def verified_market_report(model_report: dict, source: dict) -> dict:
    """数字事实由程序生成，阻止模型自行重算价格或交易日窗口后进入正式复盘。"""
    texts = [model_report['summary'], *[item['text'] for item in model_report['findings']],
             *model_report['next_steps'], *model_report['limitations']]
    if any(re.search(r'[0-9０-９]', re.sub(r'\bS\d+\b', '', text)) for text in texts):
        raise ValueError('日线模型解读包含自行输出的数字，未发布；数字事实必须来自程序核验')
    data = source['data']
    latest = data['items'][0]
    facts = [{'text': f"日线事实：{data['code']}，{data['latest_date']}，开 {latest['open']}、高 {latest['high']}、低 {latest['low']}、收 {latest['close']}；成交量 {latest['volume']:g}。收盘位置为当日{data['metrics']['close_position_label']}。", 'source_ids':[source['source_id']]}]
    for window in (5, 20):
        value = data['metrics'][str(window)]
        facts.append({'text': f"最近 {value['count']} 根日线：{value['start']} 至 {value['end']}，收盘区间 {value['close_min']}—{value['close_max']}，最高 {value['high']}、最低 {value['low']}；区间首尾收盘变化 {value['interval_change_pct']}%。", 'source_ids':[source['source_id']]})
    return {'summary': f"{data['code']} · {data['latest_date']}，最新收盘 {latest['close']}。窗口与数值已由程序核验。模型解读：{model_report['summary']}",
            'findings': facts + [{'text': '模型解读（需复核）：'+item['text'], 'source_ids':item['source_ids']} for item in model_report['findings'][:10]],
            'next_steps': model_report['next_steps'],
            'limitations': ['数字事实由本地日线计算；模型定性解读仍需复核，不代表交易执行。', *model_report['limitations'][:9]]}


def refresh_observation(tracking_id: str, run_id: str, review_date: str) -> dict:
    """报告、复盘与观察事件绑定；事务保证重放不增加重复事件。"""
    from .workspace_agent import workspace_agent, ROOT
    from .review_repository import ReviewRepository
    from .tracking_service import tracking_service

    run = workspace_agent.store.get(run_id)
    if run['status'] != 'completed' or run['input']['task'] != 'market':
        raise ValueError('观察刷新需要已完成的最新日线报告')
    if run.get('saved_review') != review_date:
        raise ValueError('请先保存本次复盘')
    review = ReviewRepository(ROOT / 'data/review_library').load(review_date)
    if not review or f'<!-- agent-run:{run_id} -->' not in review.body:
        raise ValueError('复盘缺少对应报告')
    source = next(s['data'] for s in run['sources'] if s['tool'] == 'market_daily')
    target = run['input']['trade_date']
    if source['latest_date'] != target or source['items'][0]['trade_date'] != target:
        raise ValueError('报告来源日期不一致')
    conn = get_connection()
    marker = f'[daily-agent:{run_id}]'
    conn.execute('BEGIN IMMEDIATE')
    try:
        row = conn.execute('SELECT * FROM tracking_items WHERE tracking_id=?', (tracking_id,)).fetchone()
        if not row or row['code'] != run['input']['code'] or row['status'] == 'closed':
            raise ValueError('跟踪对象不匹配或已经结束')
        if row['last_eval_date'] and row['last_eval_date'] > target:
            raise ValueError('不能用旧报告回退跟踪日期')
        exists = conn.execute("SELECT 1 FROM tracking_events WHERE tracking_id=? AND event_type='agent_observation' AND message=?", (tracking_id, marker)).fetchone()
        if not exists:
            close = source['items'][0]['close']
            changed_at = datetime.now().isoformat(timespec='seconds')
            note = (row['note'] or '') + f'\n{marker} 行情 {target}；复盘 {review_date}；观察刷新，未登记成交。'
            return_pct = row['latest_return_pct']
            if row['entry_price'] and row['status'] in ('holding', 'partial_sold'):
                return_pct = round((close / row['entry_price'] - 1) * 100, 2)
            conn.execute('UPDATE tracking_items SET last_eval_date=?,last_close=?,latest_return_pct=?,note=?,updated_at=? WHERE tracking_id=?',
                         (target, close, return_pct, note, changed_at, tracking_id))
            conn.execute('INSERT INTO tracking_events (tracking_id,event_date,event_type,action,message,payload_json,created_at) VALUES (?,?,?,?,?,?,?)',
                         (tracking_id, target, 'agent_observation', 'OBSERVE', marker,
                          json.dumps({'run_id': run_id, 'review_date': review_date, 'source_hashes': {s['source_id']: s['sha256'] for s in run['sources']}}, ensure_ascii=False), changed_at))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return tracking_service.get_item(tracking_id)
