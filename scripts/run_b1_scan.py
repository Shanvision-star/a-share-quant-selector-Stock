"""
前瞻型 B1 信号扫描脚本 - 直接运行，避免 PowerShell -c 换行报错
用法: .\.venv\Scripts\python.exe .\scripts\run_b1_scan.py
"""
import json
import random
import time
from pathlib import Path

import yaml

from utils.csv_manager import CSVManager
from utils.dingtalk_notifier import DingTalkNotifier
from utils.tdx_exporter import export_b1_pre_signal_tdx
from strategy.b1_case_analyzer import B1CaseAnalyzer

base = Path(__file__).parent.parent
cm = CSVManager(str(base / 'data'))
analyzer = B1CaseAnalyzer()


def _format_eta(seconds):
    if seconds is None or seconds < 0:
        return "--:--"
    total_seconds = int(seconds)
    minutes, sec = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def load_stock_names():
    names_path = base / 'data' / 'stock_names.json'
    if not names_path.exists():
        return {}
    for encoding in ('utf-8', 'gbk', 'utf-8-sig'):
        try:
            with open(names_path, 'r', encoding=encoding) as f:
                data = json.load(f)
            print(f'[INFO] 股票名称字典加载成功: {len(data)} 项 (encoding={encoding})')
            return data
        except Exception:
            continue

    print('[WARN] 读取股票名称失败: 尝试 utf-8/gbk/utf-8-sig 均失败')
    return {}


def resolve_stock_name(code: str, stock_names: dict) -> str:
    code = str(code).strip()
    candidates = [
        code,
        code.lstrip('0'),
        code.zfill(6),
        f'SH{code}',
        f'SZ{code}',
        f'BJ{code}',
        f'sh{code}',
        f'sz{code}',
        f'bj{code}',
    ]
    for key in candidates:
        if key in stock_names and stock_names[key]:
            return str(stock_names[key])
    return '未知'


def build_notifier():
    config_path = base / 'config' / 'config.yaml'
    if not config_path.exists():
        return DingTalkNotifier()
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    except Exception as exc:
        print(f'[WARN] 读取钉钉配置失败: {exc}')
        config = {}
    dingtalk_cfg = config.get('dingtalk', {})
    return DingTalkNotifier(
        dingtalk_cfg.get('webhook_url'),
        dingtalk_cfg.get('secret'),
    )

data_dirs = ['00', '30', '60', '68']
candidates = []
for d in data_dirs:
    folder = base / 'data' / d
    if folder.exists():
        candidates += [f.stem for f in folder.glob('*.csv')]

print(f'总股票数: {len(candidates)}', flush=True)

# 全量扫描（设 sample_size=None 时扫全部，否则随机抽样）
SAMPLE_SIZE = None   # 改为整数如 500 可加快速度

random.seed(42)
sample = candidates if SAMPLE_SIZE is None else random.sample(candidates, min(SAMPLE_SIZE, len(candidates)))
print(f'本次扫描: {len(sample)} 只', flush=True)

found = []
errors = 0
stock_names = load_stock_names()
stock_data_dict = {}
scan_started = time.time()
last_progress_ts = scan_started
total = len(sample)

for idx, code in enumerate(sample, start=1):
    if idx == 1 or idx % 50 == 0:
        pct = idx / total * 100 if total else 0.0
        print(f"正在扫描: [{idx}/{total}] {pct:5.1f}% 当前 {code}", flush=True)

    try:
        df = cm.read_stock(code)
        if df is None or df.empty or len(df) < 50:
            pass
        else:
            r = analyzer.scan_pre_signal(df, lookback_days=100)
            if r['detected']:
                prepared_df = analyzer.prepare_indicators(df)
                stock_data_dict[code] = prepared_df
                found.append({
                    'stock_code': code,
                    'stock_name': resolve_stock_name(code, stock_names),
                    'strategy_name': '阶段型B1前瞻扫描',
                    **r,
                })
    except Exception:
        errors += 1

    now_ts = time.time()
    if idx % 100 == 0 or (now_ts - last_progress_ts) >= 5 or idx == total:
        elapsed = max(now_ts - scan_started, 1e-6)
        rate = idx / elapsed
        remaining = total - idx
        eta = remaining / rate if rate > 0 else None
        pct = idx / total * 100 if total else 0.0
        print(
            f"扫描进度: [{idx}/{total}] {pct:5.1f}% | {rate:.1f}只/秒 | ETA {_format_eta(eta)} | 命中 {len(found)} | 异常 {errors}",
            flush=True,
        )
        last_progress_ts = now_ts

print(f'\n=== 前瞻 B1 预信号命中: {len(found)} 只 (扫描失败: {errors} 只) ===', flush=True)
for item in found:
    code = item['stock_code']
    name = item.get('stock_name') or resolve_stock_name(code, stock_names)
    print(
        f'  {code} {name}'
        f'  anchor={item["anchor_date"]}'
        f'  J={item["anchor_j"]}'
        f'  setup={item["setup_window_start"]}'
        f'  curJ={item["current_j"]}'
        f'  多空线偏离={item["current_dist_pct"]}%'
        f'  支撑价={item["support_price"]}'
    , flush=True)

txt_path = export_b1_pre_signal_tdx(found, strategy_name='阶段型B1前瞻扫描')
if txt_path:
    print(f'阶段型B1预警TXT: {txt_path}', flush=True)

notifier = build_notifier()
if found:
    if notifier.webhook_url:
        masked = notifier.webhook_url.split('access_token=')[-1][:8] + '***' if 'access_token=' in notifier.webhook_url else '已配置'
        print(f'[INFO] 准备推送钉钉通知，命中 {len(found)} 只，webhook={masked}', flush=True)
        push_ok = notifier.send_b1_pre_signal_results_with_charts(
            found,
            stock_names=stock_names,
            stock_data_dict=stock_data_dict,
            params={
                'strategy_name': '阶段型B1前瞻扫描',
                'chart_days': 80,
                'duokong_pct': analyzer.config.get('duokong_pct', 3),
                'short_pct': analyzer.config.get('short_pct', 2),
            },
        )
        if push_ok:
            print('[OK] 钉钉推送完成', flush=True)
        else:
            print('[WARN] 钉钉推送失败，请查看上方 errcode/HTTP 异常日志', flush=True)
    else:
        print('[WARN] 未配置钉钉 webhook，跳过发送通知', flush=True)
else:
    print('[INFO] 本次无命中，未触发钉钉推送', flush=True)

# 单独验证掌阅科技回溯模式是否仍然正常
print('\n=== 掌阅科技 603533 回溯验证 ===')
from strategy.pattern_library import B1PatternLibrary
lib = B1PatternLibrary(cm)
df603 = cm.read_stock('603533')
stage_results = lib._analyze_stage_cases('603533', df603)
print(f'阶段型命中数: {len(stage_results)}', flush=True)
if stage_results:
    s = stage_results[0].get('summary', {})
    for k, v in s.items():
        print(f'  {k}: {v}', flush=True)
print('done', flush=True)
