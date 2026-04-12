"""Pydantic 数据模型"""
from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class StockInfo(BaseModel):
    """股票基本信息"""
    code: str
    name: str
    latest_price: float
    change_pct: float          # 涨跌幅 %
    latest_date: str
    market_cap: float          # 亿元
    data_count: int


class KlineBar(BaseModel):
    """单根 K 线数据"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float              # 万元
    turnover: float
    market_cap: float          # 亿元


class KlineResponse(BaseModel):
    """K 线数据响应"""
    code: str
    name: str
    bars: List[KlineBar]
    indicators: Optional[Dict[str, List[float]]] = None


class StrategySignal(BaseModel):
    """单个策略信号"""
    date: str
    close: float
    j_value: Optional[float] = None
    volume_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    reasons: List[str] = []
    category: str = ""
    short_term_trend: Optional[float] = None
    bull_bear_line: Optional[float] = None


class StrategyResult(BaseModel):
    """单只股票的策略结果"""
    code: str
    name: str
    signals: List[StrategySignal]


class StrategyResultsResponse(BaseModel):
    """策略选股响应"""
    strategy: str
    results: List[StrategyResult]
    time: str
    total: int


class DataStatus(BaseModel):
    """数据状态"""
    total_stocks: int
    latest_date: str
    stale_count: int
    checked_count: int
    is_fresh: bool
    boards: Dict[str, Dict[str, Any]]


class StockPriceInfo(BaseModel):
    """股票详情页右侧价格面板"""
    code: str
    name: str
    close: float
    open: float
    high: float
    low: float
    prev_close: float
    change: float
    change_pct: float
    volume: int
    amount: float
    turnover: float
    market_cap: float
    latest_date: str
    ma5: float
    ma10: float
    ma20: float
    ma60: float
    k: float
    d: float
    j: float


class StrategyParamConfig(BaseModel):
    """策略参数配置"""
    strategy_name: str
    params: Dict[str, Any]
    param_meta: Optional[Dict[str, Dict[str, Any]]] = None


class ConfigUpdateRequest(BaseModel):
    """策略参数更新请求"""
    strategy_name: str
    params: Dict[str, Any]
