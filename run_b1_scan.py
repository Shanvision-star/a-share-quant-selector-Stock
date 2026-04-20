"""
前瞻型 B1 信号扫描脚本 - 直接运行，避免 PowerShell -c 换行报错
用法: .\.venv\Scripts\python.exe .\run_b1_scan.py
"""
import json
import random
import time
from pathlib import Path

import yaml

from EmQuantAPI import c
import ctypes

from utils.dingtalk_notifier import DingTalkNotifier
from utils.tdx_exporter import export_b1_pre_signal_tdx
from strategy.b1_case_analyzer import B1CaseStrategy
from utils.csv_manager import CSVManager

# Adjust base path to project root (run_b1_scan.py is in project root)
base = Path(__file__).resolve().parent

# Load EmQuantAPI DLL（失败时静默，不影响主流程）
def load_emquantapi_dll():
    dll_path = r"E:\\ApplicationInstall\\EMQuantAPI_Python\\python3\\libs\\windows\\EmQuantAPI_x64.dll"
    try:
        ctypes.CDLL(dll_path)
    except OSError:
        pass

load_emquantapi_dll()

import pandas as pd
from datetime import datetime, timedelta

# EmQuantAPI 登录状态（懒初始化，只登录一次）
_emquant_logged_in = False

def _emquant_login():
    """使用缓存凭证登录 EmQuantAPI（只执行一次）。
    若账户未开通 Python API 权限（ErrorCode=10001003），静默返回 False，不影响主流程。
    """
    global _emquant_logged_in
    if _emquant_logged_in:
        return True
    try:
        result = c.start("ForceLogin=1")
        if result.ErrorCode != 0:
            # 静默：权限不足时不打印警告，避免日志噪音
            return False
        _emquant_logged_in = True
        print("[INFO] EmQuantAPI 登录成功，实时数据补充已启用", flush=True)
        return True
    except Exception as e:
        return False


def _to_emquant_code(code: str) -> str:
    """将 6 位纯数字代码转换为 EmQuantAPI 格式（如 600000 → 600000.SH）。"""
    code = str(code).strip().upper()
    # 已有后缀
    if '.' in code:
        return code
    if len(code) != 6:
        return code
    prefix = code[:3]
    if prefix in ('600', '601', '603', '605', '688', '689', '900'):
        return code + '.SH'
    if prefix in ('000', '001', '002', '003', '300', '301'):
        return code + '.SZ'
    if prefix in ('430', '831', '832', '833', '834', '835', '836', '837',
                  '838', '839', '870', '871', '872', '873', '920'):
        return code + '.BJ'
    # 兜底
    first = code[0]
    if first == '6':
        return code + '.SH'
    return code + '.SZ'


def fetch_stock_data_emquantapi(code: str, lookback_days: int = 250):
    """通过 EmQuantAPI c.csd() 拉取日 K 线，返回与 CSVManager 列格式一致的 DataFrame。
    列：date, open, high, low, close, volume, amount, turnover
    失败或未登录时返回 None。
    """
    if not _emquant_login():
        return None

    em_code = _to_emquant_code(code)
    end_date = datetime.today().strftime("%Y-%m-%d")
    start_date = (datetime.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    try:
        result = c.csd(
            em_code,
            "OPEN,HIGH,LOW,CLOSE,VOLUME,AMOUNT,TURNOVERRATE",
            start_date,
            end_date,
            "Period=1,Adjustflag=1,Order=1,Ispandas=1",
        )
        # Ispandas=1 时直接返回 DataFrame
        if isinstance(result, pd.DataFrame) and not result.empty:
            df = result.reset_index()
            df = df.rename(columns={
                'DATETIME': 'date',
                'OPEN':     'open',
                'HIGH':     'high',
                'LOW':      'low',
                'CLOSE':    'close',
                'VOLUME':   'volume',
                'AMOUNT':   'amount',
                'TURNOVERRATE': 'turnover',
            })
            # 保留需要的列（忽略多余列）
            keep = [c for c in ('date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover') if c in df.columns]
            df = df[keep].copy()
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            return df

        # Ispandas=0 时是 EmQuantData 对象
        if hasattr(result, 'ErrorCode') and result.ErrorCode != 0:
            print(f"[WARN] EmQuantAPI csd 错误 ({em_code}) ErrorCode={result.ErrorCode}: {result.ErrorMsg}", flush=True)
            return None

        # 手动组装 DataFrame（非 Pandas 模式）
        if hasattr(result, 'Dates') and result.Dates and hasattr(result, 'Data') and result.Data:
            rows = []
            for i, dt in enumerate(result.Dates):
                row = {'date': str(dt)[:10]}
                for ind in ('OPEN', 'HIGH', 'LOW', 'CLOSE', 'VOLUME', 'AMOUNT', 'TURNOVERRATE'):
                    vals = result.Data.get(ind, result.Data.get(ind.lower(), []))
                    row[ind.lower() if ind != 'TURNOVERRATE' else 'turnover'] = vals[i] if i < len(vals) else None
                rows.append(row)
            df = pd.DataFrame(rows)
            df = df.rename(columns={'turnoverrate': 'turnover'})
            return df if not df.empty else None

    except Exception as e:
        print(f"[WARN] EmQuantAPI 拉取数据异常 ({em_code}): {e}", flush=True)

    return None


def fetch_stock_data(code):
    """数据加载主入口。
    优先级：
      1. 本地 CSVManager（速度快、数据稳定，主力数据源）
      2. EmQuantAPI（实时补充，当本地无数据时使用）
    返回标准 DataFrame（含 date/open/high/low/close/volume 等列），或 None。
    """
    # 优先：本地 CSV
    try:
        df = cm.read_stock(code)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"[WARN] CSVManager 加载数据失败 ({code}): {e}", flush=True)

    # 备用：EmQuantAPI（实时数据）
    try:
        df = fetch_stock_data_emquantapi(code)
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"[WARN] EmQuantAPI 加载数据失败 ({code}): {e}", flush=True)

    return None

cm = CSVManager(str(base / 'data'))
strategy = B1CaseStrategy()


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
        df = fetch_stock_data(code)
        if df is not None and not df.empty:
            r = strategy.scan_pre_signal(df, lookback_days=100)
            if r['detected']:
                prepared_df = strategy.prepare_indicators(df)
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
                'duokong_pct': strategy.config.get('duokong_pct', 3),
                'short_pct': strategy.config.get('short_pct', 2),
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

def _test_data_loading():
    """独立调用验证：fetch_stock_data 是否能正确加载数据（仅用于调试，不影响主流程）。"""
    test_codes = ["603920", "688519", "600519"]
    for code in test_codes:
        df = fetch_stock_data(code)
        if df is not None and not df.empty:
            print(f"[TEST OK] {code}: {len(df)} 行, 列={list(df.columns)}", flush=True)
        else:
            print(f"[TEST FAIL] {code}: 无数据", flush=True)
