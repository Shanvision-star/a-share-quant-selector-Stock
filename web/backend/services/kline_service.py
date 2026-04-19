"""K线数据服务 - 调用 CSVManager 和 technical.py"""
import sys
import json
import math
import logging
from pathlib import Path
import pandas as pd

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from utils.technical import KDJ, MA, EMA, calculate_zhixing_trend

csv_manager = CSVManager(str(project_root / "data"))
_stock_names = None

import time as _time
_ADJUST_CACHE: dict = {}   # key=(code, adjust, period, limit) → {'ts': float, 'result': dict}
_ADJUST_CACHE_TTL = 600    # 10分钟

logger = logging.getLogger(__name__)

# ── 板块判断 ────────────────────────────────────────────────────────────
def _get_board_type(code: str) -> str:
    """根据股票代码前缀判断板块类型"""
    if code.startswith('688'):
        return '科创板'
    if code.startswith('6'):
        return '上海主板'
    if code.startswith('30'):
        return '创业板'
    if code.startswith('00'):
        return '深圳主板'
    if code.startswith('8') or code.startswith('43'):
        return '北交所'
    return '未知'


# ── 个股信息缓存（行业/地区/主营业务，TTL 1天）──────────────────────────
_STOCK_INFO_CACHE: dict = {}   # code -> {'ts': float, 'data': dict}
_STOCK_INFO_CACHE_TTL = 86400  # 1天


def _fetch_stock_extra_info(code: str) -> dict:
    """通过 EastMoney CompanySurvey 接口获取行业/地区/经营范围（含缓存）"""
    now = _time.time()
    cached = _STOCK_INFO_CACHE.get(code)
    if cached and (now - cached['ts']) < _STOCK_INFO_CACHE_TTL:
        return cached['data']

    info = {'industry': '', 'region': '', 'main_business': ''}
    try:
        import requests as _req
        market = 'SZ' if code.startswith(('00', '30')) else 'SH' if code.startswith('6') else 'BJ'
        url = 'https://emweb.securities.eastmoney.com/pc_hsf10/CompanySurvey/CompanySurveyAjax'
        params = {'code': f'{market}{code}'}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://emweb.securities.eastmoney.com/',
        }
        resp = _req.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        jbzl = data.get('jbzl') or {}
        info['industry'] = jbzl.get('sshy', '')
        info['region'] = jbzl.get('qy', '')
        # 经营范围可能很长，截取前200字
        jyfw = jbzl.get('jyfw', '')
        info['main_business'] = jyfw[:200] if jyfw else ''
        logger.info(f"CompanySurvey {code}: industry={info['industry']}, region={info['region']}")
    except Exception as e:
        logger.warning(f"获取个股信息失败 {code}: {e}")
        # 回退到 akshare
        try:
            import akshare as ak
            df = ak.stock_individual_info_em(symbol=code)
            if not df.empty:
                item_map = dict(zip(df['item'].astype(str), df['value'].astype(str)))
                info['industry'] = item_map.get('行业', item_map.get('所处行业', ''))
        except Exception:
            pass

    _STOCK_INFO_CACHE[code] = {'ts': now, 'data': info}
    return info


# ── 概念标签缓存（单独接口，耗时较长）──────────────────────────────────
_CONCEPT_CACHE: dict = {}  # code -> {'ts': float, 'tags': list}
_CONCEPT_CACHE_TTL = 86400


def get_stock_concept_tags(code: str) -> list:
    """查询股票所属概念板块（通过 EastMoney F10 接口直接获取，秒级响应）"""
    now = _time.time()
    cached = _CONCEPT_CACHE.get(code)
    if cached and (now - cached['ts']) < _CONCEPT_CACHE_TTL:
        return cached['tags']

    tags = []
    try:
        import requests as _req
        # EastMoney F10 概念题材接口：直接返回个股所属概念列表
        url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
        params = {
            "reportName": "RPT_F10_CORETHEME_BOARDTYPE",
            "columns": "BOARD_NAME",
            "filter": f'(SECURITY_CODE="{code}")',
            "pageNumber": "1",
            "pageSize": "50",
            "source": "HSF10",
            "client": "PC",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://emweb.securities.eastmoney.com/",
        }
        resp = _req.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        result = (data.get("result") or {}).get("data") or []
        for item in result:
            name = item.get("BOARD_NAME", "")
            if name:
                tags.append(name)
    except Exception as e:
        logger.warning(f"F10概念接口失败 {code}, 回退到 akshare: {e}")
        try:
            import akshare as ak
            df = ak.stock_individual_info_em(symbol=code)
            if df is not None and not df.empty:
                item_map = dict(zip(df['item'].astype(str), df['value'].astype(str)))
                for key in ['概念板块', '概念', '所属概念']:
                    val = item_map.get(key, '')
                    if val:
                        tags = [t.strip() for t in val.replace('；', ';').split(';') if t.strip()]
                        break
        except Exception:
            pass

    _CONCEPT_CACHE[code] = {'ts': now, 'tags': tags}
    return tags


def _load_stock_names() -> dict:
    """懒加载股票名称映射"""
    global _stock_names
    if _stock_names is None:
        names_file = project_root / "data" / "stock_names.json"
        if names_file.exists():
            with open(names_file, 'r', encoding='utf-8') as f:
                _stock_names = json.load(f)
        else:
            _stock_names = {}
    return _stock_names


def get_stock_name(code: str) -> str:
    names = _load_stock_names()
    return names.get(code, "未知")


def _safe_float(value, default=0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return default if pd.isna(number) else number


def _round_or_none(value, digits: int = 2):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(number) or not math.isfinite(number):
        return None
    return round(number, digits)


def _prepare_kline_df(df, period: str) -> pd.DataFrame:
    prepared = df.copy()
    prepared['date'] = pd.to_datetime(prepared['date'])

    for column in ['amount', 'turnover', 'market_cap']:
        if column not in prepared.columns:
            prepared[column] = 0

    prepared = prepared.sort_values('date', ascending=True).reset_index(drop=True)

    if period == 'weekly':
        prepared = (
            prepared.groupby(prepared['date'].dt.to_period('W-FRI'))
            .agg(
                date=('date', 'last'),
                open=('open', 'first'),
                high=('high', 'max'),
                low=('low', 'min'),
                close=('close', 'last'),
                volume=('volume', 'sum'),
                amount=('amount', 'sum'),
                turnover=('turnover', 'sum'),
                market_cap=('market_cap', 'last'),
            )
            .reset_index(drop=True)
        )

    prepared = prepared.dropna(subset=['date', 'open', 'high', 'low', 'close'])
    return prepared.sort_values('date', ascending=False).reset_index(drop=True)


def get_kline(code: str, period: str = "daily", limit: int = 2600, adjust: str = "qfq") -> dict:
    """
    获取 K 线数据 + 技术指标

    逻辑：
    1. adjust=='qfq'（默认）→ 直接读 CSV（前复权，与策略引擎数据一致）
    2. adjust=='hfq'|'nfq' → 实时向 EastMoney 拉取对应复权数据（内存缓存10分钟）
       - 拉取失败 fallback 到 qfq CSV 数据，result 中 adjust 字段反映实际使用类型
    3. adjust 不合法 → 强制为 'qfq'

    period: daily | weekly
    limit : 返回最大条数（120-3200）
    """
    # 边界值: 合法性校验，双重防御（router 层 pattern 已做第一道）
    if adjust not in ("qfq", "hfq", "nfq"):
        adjust = "qfq"

    # 非前复权：走缓存 + 实时拉取路径
    if adjust != "qfq":
        cache_key = (code, adjust, period, limit)
        now = _time.time()
        cached = _ADJUST_CACHE.get(cache_key)
        if cached and now - cached['ts'] < _ADJUST_CACHE_TTL:
            return cached['result']

        fqt_map = {"hfq": 2, "nfq": 0}
        fqt = fqt_map[adjust]
        try:
            from utils.akshare_fetcher import AKShareFetcher
            fetcher = AKShareFetcher(str(project_root / "data"))
            df = fetcher.fetch_kline_for_display(code, fqt=fqt)
        except Exception:
            df = None

        # fallback: 拉取失败退化为前复权 CSV
        if df is None or df.empty:
            df = csv_manager.read_stock(code)
            if df.empty:
                return None
            adjust = "qfq"

        result = _build_kline_result(df, code, period, limit, adjust)
        if result is not None:
            _ADJUST_CACHE[cache_key] = {'ts': now, 'result': result}
        return result

    # 前复权：走现有 CSV 路径（不改动，最快）
    df = csv_manager.read_stock(code)
    if df.empty:
        return None
    return _build_kline_result(df, code, period, limit, adjust)


def _build_kline_result(df, code: str, period: str, limit: int, adjust: str) -> dict:
    """将 DataFrame 转换为前端 K 线响应 dict（含指标）。
    adjust 字段写入 result，告知前端实际使用的复权类型（fallback 时可能与请求不同）。
    """
    df = _prepare_kline_df(df, period)
    if df.empty:
        return None

    # CSV 以最新日期在前存储，这里先按底层顺序计算指标，最后再翻转给前端。
    # 取 limit 条（倒序数据，head 即最新的 N 条）
    df_slice = df.head(limit).copy()
    n = len(df_slice)

    # ── 周期自适应均线配置 ─────────────────────────────────────────────────
    # 日线：MA10 / MA30 / MA60 / MA120（短中长超长）
    # 周线：MA34 / MA55 / MA144 / MA233（斐波那契周期，适合中长期趋势判断）
    # 未来如需增加 MA 周期，在此扩展即可，前端会自动读取 ma_periods 字段渲染标签。
    if period == 'weekly':
        _ma_periods = [34, 55, 144, 233]
    else:
        _ma_periods = [10, 30, 60, 120]

    ma_a = MA(df_slice['close'], _ma_periods[0])
    ma_b = MA(df_slice['close'], _ma_periods[1])
    ma_c = MA(df_slice['close'], _ma_periods[2])
    ma_d = MA(df_slice['close'], _ma_periods[3])

    # 计算技术指标（在倒序数据上计算，technical.py 已处理倒序）
    kdj_df = KDJ(df_slice, n=9, m1=3, m2=3)
    ma3 = MA(df_slice['close'], 3)
    ma6 = MA(df_slice['close'], 6)
    ma12 = MA(df_slice['close'], 12)
    ma24 = MA(df_slice['close'], 24)
    bbi = (ma3 + ma6 + ma12 + ma24) / 4

    zhixing = calculate_zhixing_trend(df_slice)

    # 计算 MACD: DIF = EMA(close,12) - EMA(close,26), DEA = EMA(DIF,9), MACD柱 = (DIF-DEA)*2
    ema12 = EMA(df_slice['close'], 12)
    ema26 = EMA(df_slice['close'], 26)
    dif = ema12 - ema26
    dea = EMA(dif, 9)
    macd_bar = (dif - dea) * 2

    # 前端图表要求时间正序，因此 bars 和 indicators 都要统一翻转。
    # 构建结果（翻转为升序）
    bars = []
    for i in range(n - 1, -1, -1):
        row = df_slice.iloc[i]
        bars.append({
            'date': row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])[:10],
            'open': round(_safe_float(row['open']), 2),
            'high': round(_safe_float(row['high']), 2),
            'low': round(_safe_float(row['low']), 2),
            'close': round(_safe_float(row['close']), 2),
            'volume': int(_safe_float(row['volume'], 0)),
            'amount': round(_safe_float(row.get('amount', 0)) / 1e4, 2),
            'turnover': round(_safe_float(row.get('turnover', 0)), 2),
            'market_cap': round(_safe_float(row.get('market_cap', 0)) / 1e8, 2),
        })

    # 指标也翻转为升序
    def _reverse(series):
        return [_round_or_none(series.iloc[i], 2) for i in range(n - 1, -1, -1)]

    # ma_periods 告知前端本次返回的均线周期，便于动态渲染图例标签
    indicators = {
        f'ma{_ma_periods[0]}': _reverse(ma_a),
        f'ma{_ma_periods[1]}': _reverse(ma_b),
        f'ma{_ma_periods[2]}': _reverse(ma_c),
        f'ma{_ma_periods[3]}': _reverse(ma_d),
        'ma_periods': _ma_periods,
        'bbi': _reverse(bbi),
        'K': _reverse(kdj_df['K']),
        'D': _reverse(kdj_df['D']),
        'J': _reverse(kdj_df['J']),
        'short_term_trend': _reverse(zhixing['short_term_trend']),
        'bull_bear_line': _reverse(zhixing['bull_bear_line']),
        'DIF': _reverse(dif),
        'DEA': _reverse(dea),
        'MACD': _reverse(macd_bar),
    }

    return {
        'code': code,
        'name': get_stock_name(code),
        'period': period,
        'adjust': adjust,
        'bars': bars,
        'indicators': indicators,
    }


def get_stock_price_info(code: str) -> dict:
    """
    获取股票详情页右侧的价格面板信息

    逻辑：
    1. 读取最新 2 条数据（当天 + 前一天）计算涨跌额/幅
    2. 计算当天的 MA 和 KDJ
    3. 板块、行业、地区、主营业务
    4. 近30日最大涨幅、近30日单日最大涨幅
    """
    df = csv_manager.read_stock(code)
    if df.empty or len(df) < 2:
        return None

    latest = df.iloc[0]
    prev = df.iloc[1]

    # 价格面板只展示“当前截面”，因此这里不返回整段序列，而是提取最新一根的指标值。
    # 计算指标
    df_for_indicator = df.head(120)
    kdj_df = KDJ(df_for_indicator, n=9, m1=3, m2=3)
    ma5 = MA(df_for_indicator['close'], 5)
    ma10 = MA(df_for_indicator['close'], 10)
    ma20 = MA(df_for_indicator['close'], 20)
    ma60 = MA(df_for_indicator['close'], 60)

    latest_close = _safe_float(latest.get('close', 0))
    latest_open = _safe_float(latest.get('open', 0))
    latest_high = _safe_float(latest.get('high', 0))
    latest_low = _safe_float(latest.get('low', 0))
    prev_close = _safe_float(prev.get('close', 0))
    change = latest_close - prev_close
    change_pct = (change / prev_close * 100) if prev_close != 0 else 0

    # ── 板块 / 行业 / 地区 / 主营业务 ──────────────────────────────────
    board = _get_board_type(code)
    extra = _fetch_stock_extra_info(code)

    # ── 近30日统计 ──────────────────────────────────────────────────────
    df_30 = df.head(30)
    max_gain_30d = None
    max_daily_gain_30d = None
    if len(df_30) >= 2:
        closes_30 = df_30['close'].astype(float)
        base_close = float(closes_30.iloc[-1])  # 30日前第一天收盘价（df降序，iloc[-1]是最远）
        if base_close > 0:
            max_close_30 = float(closes_30.max())
            max_gain_30d = round((max_close_30 / base_close - 1) * 100, 2)
        daily_pcts = []
        for i in range(len(df_30) - 1):
            c_today = float(df_30.iloc[i]['close'])
            c_prev = float(df_30.iloc[i + 1]['close'])
            if c_prev > 0:
                daily_pcts.append((c_today / c_prev - 1) * 100)
        if daily_pcts:
            max_daily_gain_30d = round(max(daily_pcts), 2)

    return {
        'code': code,
        'name': get_stock_name(code),
        'close': round(latest_close, 2),
        'open': round(latest_open, 2),
        'high': round(latest_high, 2),
        'low': round(latest_low, 2),
        'prev_close': round(prev_close, 2),
        'change': round(change, 2),
        'change_pct': round(change_pct, 2),
        'volume': int(_safe_float(latest.get('volume', 0), 0)),
        'amount': round(_safe_float(latest.get('amount', 0), 0) / 1e4, 2),
        'turnover': round(_safe_float(latest.get('turnover', 0), 0), 2),
        'market_cap': round(_safe_float(latest.get('market_cap', 0), 0) / 1e8, 2),
        'latest_date': latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else str(latest['date'])[:10],
        'ma5': _round_or_none(ma5.iloc[0], 2),
        'ma10': _round_or_none(ma10.iloc[0], 2),
        'ma20': _round_or_none(ma20.iloc[0], 2),
        'ma60': _round_or_none(ma60.iloc[0], 2),
        'k': _round_or_none(kdj_df.iloc[0]['K'], 2),
        'd': _round_or_none(kdj_df.iloc[0]['D'], 2),
        'j': _round_or_none(kdj_df.iloc[0]['J'], 2),
        # 新增字段
        'board': board,
        'industry': extra.get('industry', ''),
        'region': extra.get('region', ''),
        'main_business': extra.get('main_business', ''),
        'max_gain_30d': max_gain_30d,
        'max_daily_gain_30d': max_daily_gain_30d,
    }


def get_intraday_kline(code: str, date: str, period: str = '1') -> list:
    """
    获取分时K线数据（单日）。优先读 SQLite 缓存，未命中则调用 EastMoney 接口并写库。
    code  : 股票代码，如 '000001'
    date  : 日期字符串 'YYYY-MM-DD'
    period: 分钟级别，支持 '1'/'15'
    注意：EastMoney 只保留近 ~5 个交易日的分钟数据；缓存后历史数据永久可用。
    """
    import re
    import json
    from datetime import datetime as _dt
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date):
        return []
    if period not in ('1', '15'):
        period = '1'
    period_int = int(period)

    # ── 1. 读 SQLite 缓存 ─────────────────────────────────────────────────
    try:
        from web.backend.services.sqlite_service import get_connection
        conn = get_connection()
        row = conn.execute(
            "SELECT bars_json FROM intraday_klines WHERE code=? AND date=? AND period=?",
            (code, date, period_int)
        ).fetchone()
        if row:
            return json.loads(row['bars_json'])
    except Exception:
        pass

    # ── 2. 调用 EastMoney 分时接口 ────────────────────────────────────────
    try:
        from utils.akshare_fetcher import AKShareFetcher
        bars = AKShareFetcher().fetch_intraday_kline(code, date, klt=period_int)
    except Exception:
        bars = []

    # ── 3. 有效数据写入 SQLite 缓存 ──────────────────────────────────────
    if bars:
        try:
            from web.backend.services.sqlite_service import get_connection
            conn = get_connection()
            conn.execute(
                "INSERT OR REPLACE INTO intraday_klines"
                "(code, date, period, bars_json, fetched_at) VALUES(?,?,?,?,?)",
                (code, date, period_int,
                 json.dumps(bars, ensure_ascii=False),
                 _dt.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()
        except Exception:
            pass

    return bars


def get_mini_kline(code: str, days: int = 30) -> list:
    """
    获取迷你 K 线数据（首页缩略图用）
    返回最近 N 天的 [date, open, close, high, low] 升序列表
    """
    df = csv_manager.read_stock(code)
    if df.empty:
        return []
    df_slice = df.head(days)
    result = []
    for i in range(len(df_slice) - 1, -1, -1):
        row = df_slice.iloc[i]
        result.append([
            row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])[:10],
            round(float(row['open']), 2),
            round(float(row['close']), 2),
            round(float(row['high']), 2),
            round(float(row['low']), 2),
        ])
    return result
