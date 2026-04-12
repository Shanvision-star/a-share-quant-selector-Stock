"""K线数据服务 - 调用 CSVManager 和 technical.py"""
import sys
import json
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from utils.technical import KDJ, MA, EMA, calculate_zhixing_trend

csv_manager = CSVManager(str(project_root / "data"))
_stock_names = None


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


def get_kline(code: str, period: str = "daily", limit: int = 250) -> dict:
    """
    获取 K 线数据 + 技术指标

    逻辑：
    1. 从 CSVManager 读取 CSV（倒序，最新在前）
    2. 取前 limit 条
    3. 计算 KDJ(9,3,3)、MA5/10/20/60、知行双线、MACD
    4. 翻转为升序返回（前端图表需要时间正序）
    """
    df = csv_manager.read_stock(code)
    if df.empty:
        return None

    # CSV 以最新日期在前存储，这里先按底层顺序计算指标，最后再翻转给前端。
    # 取 limit 条（倒序数据，head 即最新的 N 条）
    df_slice = df.head(limit).copy()
    n = len(df_slice)

    # 计算技术指标（在倒序数据上计算，technical.py 已处理倒序）
    kdj_df = KDJ(df_slice, n=9, m1=3, m2=3)
    ma5 = MA(df_slice['close'], 5)
    ma10 = MA(df_slice['close'], 10)
    ma20 = MA(df_slice['close'], 20)
    ma60 = MA(df_slice['close'], 60)

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
            'open': round(float(row['open']), 2),
            'high': round(float(row['high']), 2),
            'low': round(float(row['low']), 2),
            'close': round(float(row['close']), 2),
            'volume': int(row['volume']),
            'amount': round(float(row.get('amount', 0)) / 1e4, 2),
            'turnover': round(float(row.get('turnover', 0)), 2),
            'market_cap': round(float(row.get('market_cap', 0)) / 1e8, 2),
        })

    # 指标也翻转为升序
    def _reverse(series):
        return [round(float(series.iloc[i]), 2) for i in range(n - 1, -1, -1)]

    indicators = {
        'ma5': _reverse(ma5),
        'ma10': _reverse(ma10),
        'ma20': _reverse(ma20),
        'ma60': _reverse(ma60),
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
        'bars': bars,
        'indicators': indicators,
    }


def get_stock_price_info(code: str) -> dict:
    """
    获取股票详情页右侧的价格面板信息

    逻辑：
    1. 读取最新 2 条数据（当天 + 前一天）计算涨跌额/幅
    2. 计算当天的 MA 和 KDJ
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

    prev_close = float(prev['close'])
    change = float(latest['close']) - prev_close
    change_pct = (change / prev_close * 100) if prev_close != 0 else 0

    return {
        'code': code,
        'name': get_stock_name(code),
        'close': round(float(latest['close']), 2),
        'open': round(float(latest['open']), 2),
        'high': round(float(latest['high']), 2),
        'low': round(float(latest['low']), 2),
        'prev_close': round(prev_close, 2),
        'change': round(change, 2),
        'change_pct': round(change_pct, 2),
        'volume': int(latest['volume']),
        'amount': round(float(latest.get('amount', 0)) / 1e4, 2),
        'turnover': round(float(latest.get('turnover', 0)), 2),
        'market_cap': round(float(latest.get('market_cap', 0)) / 1e8, 2),
        'latest_date': latest['date'].strftime('%Y-%m-%d') if hasattr(latest['date'], 'strftime') else str(latest['date'])[:10],
        'ma5': round(float(ma5.iloc[0]), 2),
        'ma10': round(float(ma10.iloc[0]), 2),
        'ma20': round(float(ma20.iloc[0]), 2),
        'ma60': round(float(ma60.iloc[0]), 2),
        'k': round(float(kdj_df.iloc[0]['K']), 2),
        'd': round(float(kdj_df.iloc[0]['D']), 2),
        'j': round(float(kdj_df.iloc[0]['J']), 2),
    }


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
