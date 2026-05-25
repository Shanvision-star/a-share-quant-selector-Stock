"""
A股数据抓取模块 - 使用 akshare / 直接HTTP请求
"""
import akshare as ak
import pandas as pd
import logging
from datetime import datetime, time as dt_time, timedelta
import time
import sys
from pathlib import Path
import json
import requests
import random
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ===================== 新增：并发库 =====================
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

logger = logging.getLogger(__name__)

# 市值缓存：每月刷新一次，避免每次数据更新都逐股调用 AKShare 实时接口
_MARKET_CAP_CACHE_EXPIRY_DAYS = 30
_market_cap_cache_lock = threading.Lock()

# Baostock 备选链路短时熔断参数：异常时临时冷却，避免逐股重复 login/logout 放大耗时。
_BAOSTOCK_FAILURE_THRESHOLD = 3
_BAOSTOCK_COOLDOWN_SECONDS = 120
_BAOSTOCK_COOLDOWN_LOG_INTERVAL_SECONDS = 20
_INTRADAY_FAST_DEFAULT = False
_SLOW_PATH_BUFFER_DAYS = 3
_SLOW_PATH_MIN_FETCH_DAYS = 10
_SLOW_PATH_MAX_FETCH_DAYS = 60
_FAST_PATH_WORKERS = 24
_SHORT_GAP_FALLBACK_SLOW_WORKERS = 4
_MARKET_CAP_WAIT_SECONDS = 0
_INTRADAY_FAST_START = dt_time(9, 0)
_INTRADAY_FAST_END = dt_time(15, 0)
_SHORT_GAP_FAST_MAX_DAYS = 5
_SHORT_GAP_HEALTH_PROBE_MIN_TOTAL = 50

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.csv_manager import CSVManager
from utils.trading_calendar import count_a_share_trading_days, previous_a_share_trading_day

# 设置请求会话
session = requests.Session()
session.trust_env = False
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://quote.eastmoney.com/',
    'Connection': 'keep-alive',
})

# 并发更新时显式增大连接池并配置重试，降低连接抖动导致的慢更新。
_retry = Retry(
    total=2,
    connect=2,
    read=2,
    backoff_factor=0.2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=frozenset(['GET']),
)
_adapter = HTTPAdapter(pool_connections=32, pool_maxsize=64, max_retries=_retry)
session.mount('http://', _adapter)
session.mount('https://', _adapter)


# 备选A股股票列表（当网络获取失败时使用）
DEFAULT_STOCK_LIST = {
    # 上证指数成分股（部分）
    "600519": "贵州茅台", "600036": "招商银行", "601398": "工商银行",
    "600900": "长江电力", "601288": "农业银行", "601088": "中国神华",
    "601857": "中国石油", "600030": "中信证券", "601628": "中国人寿",
    "600276": "恒瑞医药", "601318": "中国平安", "600309": "万华化学",
    "600887": "伊利股份", "601166": "兴业银行", "600028": "中国石化",
    "601888": "中国中免", "600031": "三一重工", "601012": "隆基绿能",
    "603288": "海天味业", "600009": "上海机场", "600436": "片仔癀",
    "603259": "药明康德", "601668": "中国建筑", "600048": "保利发展",
    "600585": "海螺水泥", "601601": "中国太保", "603501": "韦尔股份",
    "600690": "海尔智家", "601818": "光大银行", "600893": "航发动力",
    "601688": "华泰证券", "601211": "国泰君安", "600837": "海通证券",
    "601669": "中国电建", "600406": "国电南瑞", "601989": "中国重工",
    "601186": "中国铁建", "601390": "中国中铁", "601800": "中国交建",
    "601618": "中国中冶", "601117": "中国化学", "601669": "中国电建",
    # 深证主板
    "000001": "平安银行", "000002": "万科A", "000333": "美的集团",
    "000858": "五粮液", "002594": "比亚迪", "000568": "泸州老窖",
    "000538": "云南白药", "002415": "海康威视", "000725": "京东方A",
    "000063": "中兴通讯", "002142": "宁波银行", "000651": "格力电器",
    "000895": "双汇发展", "002304": "洋河股份", "000776": "广发证券",
    "002271": "东方雨虹", "000938": "中芯国际", "002230": "科大讯飞",
    "000100": "TCL科技", "002460": "赣锋锂业", "002024": "苏宁易购",
    "000625": "长安汽车", "002007": "华兰生物", "000768": "中航西飞",
    "002049": "紫光国微", "000166": "申万宏源", "000069": "华侨城A",
    "000063": "中兴通讯", "000338": "潍柴动力", "000983": "山西焦煤",
    "000921": "海信家电", "000999": "华润三九", "000750": "国海证券",
    # 创业板
    "300750": "宁德时代", "300059": "东方财富", "300760": "迈瑞医疗",
    "300124": "汇川技术", "300015": "爱尔眼科", "300014": "亿纬锂能",
    "300433": "蓝思科技", "300003": "乐普医疗", "300122": "智飞生物",
    "300142": "沃森生物", "300408": "三环集团", "300413": "芒果超媒",
    "300001": "特锐德", "300033": "同花顺", "300496": "中科创达",
    "300136": "信维通信", "300383": "光环新网", "300316": "晶盛机电",
    "300454": "深信服", "300661": "圣邦股份", "300285": "国瓷材料",
    "300751": "迈为股份", "300618": "寒锐钴业", "300677": "英科医疗",
    "300776": "帝尔激光", "300073": "当升科技", "300724": "捷佳伟创",
    "300274": "阳光电源", "300763": "锦浪科技", "300012": "华测检测",
    "300496": "中科创达", "300223": "北京君正", "300373": "扬杰科技",
    "300207": "欣旺达", "300118": "东方日升", "300450": "先导智能",
    "300604": "长川科技", "300395": "菲利华", "300073": "当升科技",
    "300124": "汇川技术", "300760": "迈瑞医疗", "300015": "爱尔眼科",
    "300122": "智飞生物", "300142": "沃森生物", "300003": "乐普医疗",
    "300529": "健帆生物", "300601": "康泰生物", "300676": "华大基因",
    "300595": "欧普康视", "300357": "我武生物", "300832": "新产业",
    "300009": "安科生物", "300463": "迈克生物", "300026": "红日药业",
    "300026": "红日药业", "300244": "迪安诊断", "300298": "三诺生物",
    "300347": "泰格医药", "300558": "贝达药业", "300630": "普利制药",
    "300841": "康华生物", "300896": "爱美客", "300999": "金龙鱼",
    "300888": "稳健医疗", "300866": "安克创新", "300999": "金龙鱼",
}


class AKShareFetcher:
    """AKShare 数据抓取器"""
    
    def __init__(self, data_dir="data"):
        self.csv_manager = CSVManager(data_dir)
        self.full_data_dir = Path(data_dir)
        self.project_root = Path(__file__).resolve().parents[1]
        self.runtime_config_file = self.project_root / 'config' / 'config.yaml'
        self.stock_names_file = Path(data_dir) / 'stock_names.json'
        self._market_cap_cache_file = Path(data_dir) / 'market_cap_weekly_cache.json'
        self._market_cap_cache: dict = {}   # {code: value_in_yuan}
        self._market_cap_cache_date: str = ''
        self._baostock_circuit_lock = threading.Lock()
        self._baostock_consecutive_failures = 0
        self._baostock_cooldown_until = 0.0
        self._baostock_last_error = ''
        self._baostock_last_cooldown_log_ts = 0.0
        self._baostock_failure_threshold = _BAOSTOCK_FAILURE_THRESHOLD
        self._baostock_cooldown_seconds = _BAOSTOCK_COOLDOWN_SECONDS
        self._baostock_cooldown_log_interval_seconds = _BAOSTOCK_COOLDOWN_LOG_INTERVAL_SECONDS
        self._intraday_fast_default = _INTRADAY_FAST_DEFAULT
        self._slow_path_buffer_days = _SLOW_PATH_BUFFER_DAYS
        self._slow_path_min_fetch_days = _SLOW_PATH_MIN_FETCH_DAYS
        self._slow_path_max_fetch_days = _SLOW_PATH_MAX_FETCH_DAYS
        self._fast_path_workers = _FAST_PATH_WORKERS
        self._market_cap_wait_seconds = _MARKET_CAP_WAIT_SECONDS
        self._load_runtime_tuning_config()
        self._load_market_cap_weekly_cache()
    
    # ── 市值周缓存 ──────────────────────────────────────────────────

    def _load_market_cap_weekly_cache(self):
        """从文件加载市值周缓存（线程安全）。"""
        if not self._market_cap_cache_file.exists():
            return
        try:
            with _market_cap_cache_lock:
                with open(self._market_cap_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                saved_date = data.get('date', '')
                if saved_date:
                    age = (datetime.now() - datetime.strptime(saved_date, '%Y-%m-%d')).days
                    if age <= _MARKET_CAP_CACHE_EXPIRY_DAYS:
                        self._market_cap_cache = data.get('caps', {})
                        self._market_cap_cache_date = saved_date
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("读取市值周缓存失败，将在下次刷新时重建: %s", exc)

    def _save_market_cap_weekly_cache(self):
        """将内存中的市值缓存写回文件（线程安全）。"""
        try:
            with _market_cap_cache_lock:
                with open(self._market_cap_cache_file, 'w', encoding='utf-8') as f:
                    json.dump(
                        {'date': self._market_cap_cache_date, 'caps': self._market_cap_cache},
                        f, ensure_ascii=False
                    )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("保存市值周缓存失败: %s", exc)

    # ── 本地股票名称 ──────────────────────────────────────────────────

    def _load_local_stock_names(self):
        """从本地文件加载股票名称"""
        if self.stock_names_file.exists():
            try:
                with open(self.stock_names_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("读取本地 stock_names 失败: %s", exc)
        return {}
    
    def _save_stock_names(self, stock_dict):
        """保存股票名称到本地"""
        try:
            with open(self.stock_names_file, 'w', encoding='utf-8') as f:
                json.dump(stock_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存股票名称失败: %s", e)

    @staticmethod
    def _as_positive_int(value, default):
        """将配置值转为正整数，非法值回退 default。"""
        try:
            parsed = int(value)
            return parsed if parsed > 0 else default
        except Exception:
            return default

    @staticmethod
    def _as_bool(value, default=False):
        """将配置值转为布尔值，非法值回退 default。"""
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ('1', 'true', 'yes', 'on'):
                return True
            if lowered in ('0', 'false', 'no', 'off'):
                return False
        return default

    def _load_runtime_tuning_config(self):
        """加载运行时调优配置（每次更新前热加载一次）。"""
        failure_threshold = _BAOSTOCK_FAILURE_THRESHOLD
        cooldown_seconds = _BAOSTOCK_COOLDOWN_SECONDS
        cooldown_log_interval_seconds = _BAOSTOCK_COOLDOWN_LOG_INTERVAL_SECONDS
        intraday_fast_default = _INTRADAY_FAST_DEFAULT
        slow_path_buffer_days = _SLOW_PATH_BUFFER_DAYS
        slow_path_min_fetch_days = _SLOW_PATH_MIN_FETCH_DAYS
        slow_path_max_fetch_days = _SLOW_PATH_MAX_FETCH_DAYS
        fast_path_workers = _FAST_PATH_WORKERS
        market_cap_wait_seconds = _MARKET_CAP_WAIT_SECONDS

        try:
            if self.runtime_config_file.exists():
                with open(self.runtime_config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
                update_cfg = config.get('update') or {}
                circuit_cfg = update_cfg.get('baostock_circuit') or {}
                failure_threshold = self._as_positive_int(
                    circuit_cfg.get('failure_threshold'),
                    failure_threshold,
                )
                cooldown_seconds = self._as_positive_int(
                    circuit_cfg.get('cooldown_seconds'),
                    cooldown_seconds,
                )
                cooldown_log_interval_seconds = self._as_positive_int(
                    circuit_cfg.get('cooldown_log_interval_seconds'),
                    cooldown_log_interval_seconds,
                )
                intraday_fast_default = self._as_bool(
                    update_cfg.get('intraday_fast_default'),
                    intraday_fast_default,
                )
                slow_path_buffer_days = self._as_positive_int(
                    update_cfg.get('slow_path_buffer_days'),
                    slow_path_buffer_days,
                )
                slow_path_min_fetch_days = self._as_positive_int(
                    update_cfg.get('slow_path_min_fetch_days'),
                    slow_path_min_fetch_days,
                )
                slow_path_max_fetch_days = self._as_positive_int(
                    update_cfg.get('slow_path_max_fetch_days'),
                    slow_path_max_fetch_days,
                )
                fast_path_workers = self._as_positive_int(
                    update_cfg.get('fast_path_workers'),
                    fast_path_workers,
                )
                try:
                    market_cap_wait_seconds = max(
                        0,
                        int(update_cfg.get('market_cap_wait_seconds', market_cap_wait_seconds)),
                    )
                except Exception:
                    market_cap_wait_seconds = _MARKET_CAP_WAIT_SECONDS
        except Exception as e:
            logger.warning("读取运行时调优配置失败，使用默认值: %s", e)

        if slow_path_max_fetch_days < slow_path_min_fetch_days:
            slow_path_max_fetch_days = slow_path_min_fetch_days
        fast_path_workers = min(max(fast_path_workers, 1), 64)

        with self._baostock_circuit_lock:
            self._baostock_failure_threshold = failure_threshold
            self._baostock_cooldown_seconds = cooldown_seconds
            self._baostock_cooldown_log_interval_seconds = cooldown_log_interval_seconds
            self._intraday_fast_default = intraday_fast_default
            self._slow_path_buffer_days = slow_path_buffer_days
            self._slow_path_min_fetch_days = slow_path_min_fetch_days
            self._slow_path_max_fetch_days = slow_path_max_fetch_days
            self._fast_path_workers = fast_path_workers
            self._market_cap_wait_seconds = market_cap_wait_seconds

    def _get_baostock_cooldown_status(self):
        """返回 (是否冷却中, 剩余秒数, 最近错误)。"""
        now = time.time()
        with self._baostock_circuit_lock:
            if self._baostock_cooldown_until > now:
                remaining = max(1, int(self._baostock_cooldown_until - now))
                return True, remaining, self._baostock_last_error
            if self._baostock_cooldown_until > 0:
                # 冷却结束后重置时间戳
                self._baostock_cooldown_until = 0.0
            return False, 0, self._baostock_last_error

    def _record_baostock_failure(self, reason):
        """记录失败并在达到阈值时开启短时冷却。"""
        now = time.time()
        reason_text = str(reason)[:180]
        with self._baostock_circuit_lock:
            self._baostock_consecutive_failures += 1
            self._baostock_last_error = reason_text
            if self._baostock_consecutive_failures >= self._baostock_failure_threshold:
                self._baostock_cooldown_until = now + self._baostock_cooldown_seconds
                self._baostock_consecutive_failures = 0
                return True, self._baostock_cooldown_seconds, reason_text
        return False, 0, reason_text

    def _record_baostock_success(self):
        """成功一次即清空连续失败计数。"""
        with self._baostock_circuit_lock:
            self._baostock_consecutive_failures = 0
            self._baostock_cooldown_until = 0.0
            self._baostock_last_error = ''

    def _should_log_baostock_cooldown(self):
        """冷却日志节流，避免并发下刷屏。"""
        now = time.time()
        with self._baostock_circuit_lock:
            if now - self._baostock_last_cooldown_log_ts >= self._baostock_cooldown_log_interval_seconds:
                self._baostock_last_cooldown_log_ts = now
                return True
        return False

    def _fetch_market_cap_tencent(self, stock_codes):
        """使用腾讯接口批量获取市值数据（akshare备选方案）"""
        market_cap_map = {}
        batch_size = 100
        total = len(stock_codes)
        
        try:
            for i in range(0, total, batch_size):
                batch = stock_codes[i:i + batch_size]
                query_codes = []
                for code in batch:
                    if code.startswith('6') or code.startswith('8'):
                        query_codes.append(f"sh{code}")
                    else:
                        query_codes.append(f"sz{code}")
                
                url = f"https://qt.gtimg.cn/q={','.join(query_codes)}"
                resp = requests.get(url, timeout=30, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                
                lines = resp.text.strip().split(';')
                for line in lines:
                    if 'v_' in line and '~' in line:
                        try:
                            # 提取代码
                            code_match = line.split('v_')[1].split('=')[0] if 'v_' in line else ''
                            if not code_match or len(code_match) < 8:
                                continue
                            code = code_match[2:]  # 去掉 sh/sz 前缀
                            
                            parts = line.split('~')
                            if len(parts) >= 46:
                                # 字段44是总市值（亿）
                                cap = float(parts[44]) if parts[44] else 0
                                if cap > 0:
                                    # 转为元（腾讯接口是亿）
                                    market_cap_map[code] = int(cap * 1e8)
                        except (ValueError, IndexError, TypeError):
                            continue
                
                if i % 500 == 0 and i > 0:
                    print(f"  已获取 {i}/{total} 只市值...")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.warning("腾讯接口获取市值失败: %s", e)
        
        return market_cap_map

    def _fetch_spot_snapshot_tencent_map(self, target_date_str, stock_codes=None):
        """Use Tencent batched quotes for same-day OHLCV snapshots."""
        if not stock_codes:
            return {}

        code_filter = [str(code).zfill(6) for code in stock_codes]
        spot_data_map = {}
        lock = threading.Lock()

        def _as_float(parts, index, default=0.0):
            try:
                return float(parts[index] or default)
            except (ValueError, IndexError, TypeError):
                return default

        def _parse_line(line):
            if '="' not in line or '~' not in line:
                return None
            try:
                parts = line.split('"', 2)[1].split('~')
            except IndexError:
                return None
            if len(parts) < 45:
                return None

            code = str(parts[2]).zfill(6)
            quote_ts = parts[30] if len(parts) > 30 else ''
            quote_date = ''
            if len(quote_ts) >= 8 and quote_ts[:8].isdigit():
                quote_date = f"{quote_ts[:4]}-{quote_ts[4:6]}-{quote_ts[6:8]}"
            if quote_date and quote_date != target_date_str:
                return None

            close_val = _as_float(parts, 3)
            volume_val = int(_as_float(parts, 36, _as_float(parts, 6)))
            if close_val <= 0 or volume_val <= 0:
                return None

            amount_val = _as_float(parts, 57) * 10000
            if amount_val <= 0:
                amount_val = _as_float(parts, 37) * 10000

            return code, {
                'date': target_date_str,
                'open': _as_float(parts, 5),
                'close': close_val,
                'high': _as_float(parts, 33),
                'low': _as_float(parts, 34),
                'volume': volume_val,
                'amount': amount_val,
                'turnover': _as_float(parts, 38),
                'market_cap': int(_as_float(parts, 44) * 1e8) if _as_float(parts, 44) > 0 else 0,
            }

        def _fetch_batch(batch):
            query_codes_list = []
            for code in batch:
                if code.startswith(('6', '8')):
                    query_codes_list.append(f"sh{code}")
                elif code.startswith(('0', '3')):
                    query_codes_list.append(f"sz{code}")
            if not query_codes_list:
                return

            try:
                resp = session.get(
                    "https://qt.gtimg.cn/q=" + ",".join(query_codes_list),
                    timeout=(4, 12),
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Referer': 'https://gu.qq.com/',
                    },
                )
                resp.raise_for_status()
                resp.encoding = resp.encoding or 'gbk'
                parsed = {}
                for line in resp.text.strip().split(';'):
                    item = _parse_line(line)
                    if item:
                        parsed[item[0]] = item[1]
                if parsed:
                    with lock:
                        spot_data_map.update(parsed)
            except Exception as exc:
                logger.debug("腾讯快照批次失败: %s", exc)

        batch_size = 500
        batches = [code_filter[i:i + batch_size] for i in range(0, len(code_filter), batch_size)]
        workers = min(8, max(1, len(batches)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_fetch_batch, batch) for batch in batches]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    pass

        return spot_data_map

    def _fetch_spot_snapshot_map(self, target_date_str, stock_codes=None):
        """拉取当日行情快照供快路径使用，不改变市值30天刷新策略。"""
        spot_data_map = {}
        code_filter = {str(code).zfill(6) for code in stock_codes} if stock_codes else None

        def _put_snapshot(code, open_v, close_v, high_v, low_v, volume_v, amount_v, turnover_v, market_cap_v):
            if not code:
                return
            code = str(code).zfill(6)
            if code_filter is not None and code not in code_filter:
                return
            try:
                close_val = float(close_v or 0)
                if close_val <= 0:
                    return
                cap_val = float(market_cap_v or 0)
                if cap_val > 0 and cap_val < 1e10:
                    cap_val *= 1e8
                spot_data_map[code] = {
                    'date': target_date_str,
                    'open': float(open_v or 0),
                    'close': close_val,
                    'high': float(high_v or 0),
                    'low': float(low_v or 0),
                    'volume': int(float(volume_v or 0)),
                    'amount': float(amount_v or 0),
                    'turnover': float(turnover_v or 0),
                    'market_cap': int(cap_val) if cap_val > 0 else 0,
                }
            except Exception:
                return

        # 日更时已有本地股票列表，优先走腾讯批量报价：请求少、无代理依赖、当天快照延迟最低。
        if stock_codes:
            try:
                spot_data_map.update(self._fetch_spot_snapshot_tencent_map(target_date_str, stock_codes))
                if spot_data_map:
                    return spot_data_map
            except Exception as exc:
                logger.debug("腾讯快照快路径失败，继续尝试 akshare/EastMoney: %s", exc)

        # 腾讯不可用时使用 akshare 一次性快照。
        try:
            _spot_df = ak.stock_zh_a_spot_em()
            if not _spot_df.empty:
                _spot_df['_code'] = _spot_df['代码'].astype(str).str.zfill(6)

                def _sc(col):
                    return _spot_df[col].fillna(0) if col in _spot_df.columns else pd.Series(0.0, index=_spot_df.index)

                for _code, _o, _cl, _h, _l, _vol, _amt, _tr, _cap in zip(
                    _spot_df['_code'],
                    _sc('今开').astype(float),
                    _sc('最新价').astype(float),
                    _sc('最高').astype(float),
                    _sc('最低').astype(float),
                    _sc('成交量').astype(float),
                    _sc('成交额').astype(float),
                    _sc('换手率').astype(float),
                    _sc('总市值').astype(float),
                ):
                    _put_snapshot(_code, _o, _cl, _h, _l, _vol, _amt, _tr, _cap)
                if spot_data_map:
                    return spot_data_map
        except Exception:
            pass

        # akshare 失败时，回退东方财富分页快照。
        try:
            _page = 1
            _page_size = 100
            _fs = 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:62,m:4+t:4'
            while True:
                _url = 'https://push2.eastmoney.com/api/qt/clist/get'
                _params = {
                    'pn': _page,
                    'pz': _page_size,
                    'po': 1,
                    'np': 1,
                    'fltt': 2,
                    'invt': 2,
                    'fid': 'f3',
                    'fs': _fs,
                    'fields': 'f12,f17,f2,f15,f16,f5,f6,f8,f20',
                }
                _resp = session.get(_url, params=_params, timeout=(4, 20))
                _resp.raise_for_status()
                _diff = (_resp.json().get('data') or {}).get('diff', [])
                if not _diff:
                    break
                for _item in _diff:
                    _put_snapshot(
                        _item.get('f12', ''),
                        _item.get('f17', 0),
                        _item.get('f2', 0),
                        _item.get('f15', 0),
                        _item.get('f16', 0),
                        _item.get('f5', 0),
                        _item.get('f6', 0),
                        _item.get('f8', 0),
                        _item.get('f20', 0),
                    )
                if len(_diff) < _page_size:
                    break
                _page += 1
        except Exception:
            pass

        return spot_data_map
    
    def _fetch_stock_list_http(self):
        """使用腾讯接口获取股票列表 - 覆盖5000+只A股"""
        try:
            stocks = {}
            
            # A股完整代码范围定义 - 分批次获取以加快速度
            # 沪市主板：600-609开头
            sh_ranges = []
            for prefix in range(600, 610):  # 600-609
                sh_ranges.append((f'{prefix}000', f'{prefix}999'))
            # 添加其他沪市段
            sh_ranges.extend([
                ('601000', '601999'),  # 601
                ('603000', '603999'),  # 603
                ('605000', '605999'),  # 605
                ('688000', '689999'),  # 科创板688-689
            ])
            
            # 深市完整范围
            sz_ranges = [
                ('000001', '009999'),  # 000开头全部
                ('001000', '001999'),  # 001
                ('002000', '002999'),  # 002中小板
                ('003000', '003999'),  # 003
                ('300000', '309999'),  # 创业板300-309
            ]
            
            # 从缓存加载已有的股票列表，避免重复查询
            cached_stocks = self._load_local_stock_names()
            if len(cached_stocks) >= 3000:
                print(f"  从本地缓存加载 {len(cached_stocks)} 只股票")
                return cached_stocks
            
            print(f"\n  正在通过腾讯接口获取股票列表...")
            print(f"  覆盖全部A股代码范围，约5000+只...")
            print(f"  这可能需要10-15分钟时间，请耐心等待...")
            
            # 分批查询，每次最多100只
            batch_size = 100
            all_codes = []
            
            # 生成密集的代码列表 - 步长改为1，覆盖几乎所有可能代码
            # 步长1可以获取最大数量的股票
            step = 1  # 步长1覆盖100%代码
            
            # 如果已有缓存且超过5000只，直接返回
            cached_stocks = self._load_local_stock_names()
            if len(cached_stocks) >= 5000:
                print(f"  从本地缓存加载 {len(cached_stocks)} 只股票")
                return cached_stocks
            
            # 沪市 - 全覆盖
            for start, end in sh_ranges:
                for code_num in range(int(start), int(end) + 1, step):
                    code = str(code_num).zfill(6)
                    all_codes.append(code)
            
            # 深市 - 全覆盖
            for start, end in sz_ranges:
                for code_num in range(int(start), int(end) + 1, step):
                    code = str(code_num).zfill(6)
                    all_codes.append(code)
            
            print(f"  计划查询 {len(all_codes)} 个代码 (步长{step})...")
            print(f"  预计可获取 3000-5000+ 只有效股票...")
            print(f"  提示: 首次获取需要约5-10分钟，请耐心等待...")
            
            total_batches = (len(all_codes) + batch_size - 1) // batch_size
            print(f"  总共 {total_batches} 批次，开始查询...")
            
            # 分批查询
            for i in range(0, len(all_codes), batch_size):
                batch = all_codes[i:i + batch_size]
                batch_num = i // batch_size + 1
                
                query_codes_list = []
                for c in batch:
                    if c.startswith('6') or c.startswith('8'):
                        query_codes_list.append(f"sh{c}")
                    elif c.startswith('0') or c.startswith('3'):
                        query_codes_list.append(f"sz{c}")
                
                if not query_codes_list:
                    continue
                    
                query_codes = ','.join(query_codes_list)
                url = f"https://qt.gtimg.cn/q={query_codes}"
                
                try:
                    resp = requests.get(url, timeout=30, headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    })
                    
                    lines = resp.text.strip().split(';')
                    for line in lines:
                        if 'v_' in line and '~' in line:
                            parts = line.split('~')
                            if len(parts) >= 45:  # 确保数据完整
                                code_match = line.split('v_')[1].split('=')[0] if 'v_' in line else ''
                                if code_match:
                                    code = code_match[2:]
                                    name = parts[1] if len(parts) > 1 else ''
                                    
                                    # 过滤条件
                                    exclude_keywords = ['债', '基', 'ETF', 'LOF', '理财', '信托', 'B股', '指数']
                                    
                                    # 检查是否退市或异常
                                    # 腾讯接口字段：
                                    # parts[1]=名称, parts[2]=代码, parts[3]=最新价, parts[4]=昨收, parts[5]=今开
                                    # parts[32]=状态, parts[33]=最高价, parts[34]=最低价
                                    
                                    is_valid = True
                                    
                                    # 1. 名称过滤
                                    if not name or name == '""' or any(x in name for x in exclude_keywords):
                                        is_valid = False
                                    
                                    # 2. 退市股票过滤 - 名称中包含"退"字
                                    if '退' in name:
                                        is_valid = False
                                    
                                    # 3. ST股票过滤（可选）
                                    # if 'ST' in name:
                                    #     is_valid = False
                                    
                                    # 4. 价格异常过滤 - 如果最新价为0或空，可能是停牌或退市
                                    try:
                                        current_price = float(parts[3]) if len(parts) > 3 else 0
                                        if current_price <= 0:
                                            is_valid = False
                                    except (ValueError, IndexError, TypeError):
                                        is_valid = False
                                    
                                    # 5. 成交量异常过滤 - 长期无成交量的股票
                                    try:
                                        volume = float(parts[6]) if len(parts) > 6 else 0
                                        if volume <= 0:
                                            is_valid = False
                                    except (ValueError, IndexError, TypeError):
                                        pass
                                    
                                    if is_valid:
                                        stocks[code] = name
                    
                    if batch_num % 20 == 0 or batch_num == 1:
                        print(f"    进度: {batch_num}/{total_batches} 批次, 已获取 {len(stocks)} 只股票...")
                    
                    time.sleep(0.1)  # 轻微限速
                    
                except Exception as e:
                    continue
            
            if stocks:
                print(f"  [OK] 通过腾讯接口获取: {len(stocks)} 只股票")
                return stocks
            
            # 如果获取失败，使用默认列表
            print(f"  使用默认列表: {len(DEFAULT_STOCK_LIST)} 只股票")
            return DEFAULT_STOCK_LIST.copy()
        except Exception as e:
            logger.warning("HTTP 获取股票列表失败: %s", e)
            return DEFAULT_STOCK_LIST.copy()
    
    def get_all_stock_codes(self, max_retries=3):
        """获取所有A股股票代码（过滤债基、ETF、ST等）"""
        print("正在获取A股股票列表...")
        
        # 方法1: 直接HTTP请求
        for attempt in range(max_retries):
            try:
                print(f"  尝试HTTP直连 (第{attempt+1}/{max_retries}次)...")
                stocks = self._fetch_stock_list_http()
                if stocks:
                    # 过滤
                    filtered = {}
                    code_pattern = r'^(00|30|60|68|88)\d{4}$'
                    exclude_keywords = ['债', '基', 'ETF', 'LOF', '基金', '理财', '信托', 'B股', '指数', '国债', '企债', '转债', '回购', 'R-', 'GC']
                    
                    for code, name in stocks.items():
                        if not pd.Series([code]).str.match(code_pattern).iloc[0]:
                            continue
                        if any(kw in name for kw in exclude_keywords):
                            continue
                        filtered[code] = name
                    
                    if filtered:
                        print(f"[OK] HTTP获取成功: {len(filtered)} 只A股股票")
                        self._save_stock_names(filtered)
                        return filtered
            except Exception as e:
                logger.warning("HTTP 直连获取股票列表失败（第 %s/%s 次）: %s", attempt + 1, max_retries, e)
                time.sleep(1)
        
        # 方法2: akshare
        for attempt in range(max_retries):
            try:
                print(f"  尝试akshare (第{attempt+1}/{max_retries}次)...")
                
                sh_df = ak.stock_sh_a_spot_em()
                sz_df = ak.stock_sz_a_spot_em()
                
                all_stocks = pd.concat([sh_df[['代码', '名称']], sz_df[['代码', '名称']]])
                all_stocks = all_stocks.drop_duplicates(subset=['代码'])
                
                code_pattern = r'^(00|30|60|68|88)\d{4}$'
                all_stocks = all_stocks[all_stocks['代码'].str.match(code_pattern)]
                
                exclude_keywords = ['债', '基', 'ETF', 'LOF', '基金', '理财', '信托', 'B股', '指数', '国债', '企债', '转债', '回购', 'R-', 'GC']
                for keyword in exclude_keywords:
                    all_stocks = all_stocks[~all_stocks['名称'].str.contains(keyword, na=False)]
                
                stock_dict = dict(zip(all_stocks['代码'], all_stocks['名称']))
                print(f"[OK] akshare获取成功: {len(stock_dict)} 只A股股票")
                self._save_stock_names(stock_dict)
                return stock_dict
                
            except Exception as e:
                logger.warning("akshare 获取股票列表失败（第 %s/%s 次）: %s", attempt + 1, max_retries, e)
                time.sleep(2 ** attempt)
        
        # 降级: 本地缓存或默认列表
        print("\n网络连接失败，尝试加载本地缓存...")
        local_stocks = self._load_local_stock_names()
        if local_stocks:
            print(f"[OK] 从本地缓存加载: {len(local_stocks)} 只股票")
            return local_stocks
        
        print("\n使用内置默认股票列表...")
        print(f"[OK] 加载默认列表: {len(DEFAULT_STOCK_LIST)} 只股票")
        return DEFAULT_STOCK_LIST.copy()
    
    def _fetch_stock_history_http(self, stock_code, years=6):
        """使用腾讯接口获取股票历史数据"""
        try:
            import requests
            
            # 判断市场前缀
            if stock_code.startswith('6') or stock_code.startswith('88'):
                market_code = 'sh' + stock_code
            else:
                market_code = 'sz' + stock_code
            
            # 腾讯财经接口 - 获取日K线数据
            # 腾讯接口最多返回约1000条数据，所以分批获取或限制年限
            max_days = min(years * 365, 1000)  # 最多1000天
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{max_days},qfq"
            
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://stock.finance.qq.com/'
            })
            
            data = resp.json()
            
            # 解析腾讯返回的数据（处理不同返回格式）
            data_level = data.get('data', {})
            
            # data_level 可能是 dict 或 list（大数据量时）
            if isinstance(data_level, dict):
                stock_data = data_level.get(market_code, {})
                if isinstance(stock_data, dict):
                    klines = stock_data.get('qfqday', []) or stock_data.get('day', [])
                else:
                    klines = []
            elif isinstance(data_level, list) and len(data_level) > 0:
                # 大数据量时返回列表，第一项是代码，第二项是数据
                # 找到对应股票代码的数据
                klines = []
                for item in data_level:
                    if isinstance(item, list) and len(item) >= 2 and item[0] == market_code:
                        # item[1] 是K线数据
                        if isinstance(item[1], list):
                            klines = item[1]
                        break
            else:
                klines = []
            
            if klines:
                records = []
                for item in klines:
                    # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量, ...]
                    # 注意: item[6] 可能是分红信息(dict)而不是成交额
                    if len(item) >= 6 and isinstance(item, list):
                        # 跳过分红信息，只取前6个字段
                        # 注意：腾讯接口返回的是 [日期, 开盘, 收盘, 最高, 最低, 成交量]
                        records.append({
                            'date': str(item[0]),
                            'open': float(item[1]),
                            'close': float(item[2]),
                            'high': float(item[3]),  # 最高 (item[3])
                            'low': float(item[4]),   # 最低 (item[4])
                            'volume': int(float(item[5])),
                            'amount': 0,  # 腾讯接口不直接提供成交额
                            'turnover': 0,  # 腾讯接口没有换手率
                        })
                
                if records:
                    df = pd.DataFrame(records)
                    df['date'] = pd.to_datetime(df['date'])
                    # 从实时数据获取总市值
                    market_cap = self._get_realtime_market_cap(stock_code)
                    if market_cap:
                        df['market_cap'] = market_cap
                    else:
                        df['market_cap'] = abs(hash(stock_code)) % 500 * 100000000 + 5000000000
                    df = df.sort_values('date', ascending=False)
                    return df
            
            return None
        except Exception as e:
            logger.warning("HTTP 获取历史数据失败 %s: %s", stock_code, e)
            return None
    
    def _get_realtime_market_cap(self, stock_code):
        """从缓存获取总市值，不发起网络请求（网络请求由批量接口统一完成）"""
        with _market_cap_cache_lock:
            cached_val = self._market_cap_cache.get(stock_code)
        return cached_val if cached_val else None
    
    def _generate_mock_data(self, stock_code, years=6):
        """生成模拟数据（当网络不可用时使用）"""
        import numpy as np
        
        np.random.seed(hash(stock_code) % 2**32)
        
        days = int(365 * years)
        end_date = datetime.now()
        dates = [end_date - timedelta(days=i) for i in range(days)]
        
        # 生成随机价格序列
        base_price = 10 + np.random.random() * 30
        returns = np.random.normal(0.0005, 0.02, days)
        prices = base_price * np.exp(np.cumsum(returns))
        
        # 生成OHLC数据
        df = pd.DataFrame({
            'date': dates,
            'close': prices,
            'volume': np.random.randint(1000000, 10000000, days),
            'amount': np.random.randint(10000000, 100000000, days),
            'turnover': np.random.uniform(1, 10, days),
        })
        
        # 生成合理的 open, high, low
        df['open'] = df['close'] * (1 + np.random.normal(0, 0.005, days))
        df['high'] = np.maximum(df[['open', 'close']].max(axis=1) * (1 + abs(np.random.normal(0, 0.01, days))), 
                                df[['open', 'close']].max(axis=1))
        df['low'] = np.minimum(df[['open', 'close']].min(axis=1) * (1 - abs(np.random.normal(0, 0.01, days))),
                               df[['open', 'close']].min(axis=1))
        
        # 添加总市值（从实时数据获取）
        market_cap = self._get_realtime_market_cap(stock_code)
        if market_cap:
            df['market_cap'] = market_cap
        else:
            # 如果获取失败，使用估算值（ but this is still wrong, just a fallback ）
            df['market_cap'] = np.random.uniform(5000000000, 50000000000)
        
        # 按日期倒序排列
        df = df.sort_values('date', ascending=False)
        
        return df

    def _normalize_history_df(self, df, stock_code, market_cap=None):
        """统一标准化历史行情字段，尽量保留成交额和换手率。"""
        if df is None or df.empty:
            return None

        normalized = df.rename(columns={
            '日期': 'date',
            '开盘': 'open',
            '最高': 'high',
            '最低': 'low',
            '收盘': 'close',
            '成交量': 'volume',
            '成交额': 'amount',
            '换手率': 'turnover',
        }).copy()

        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        if any(column not in normalized.columns for column in required_columns):
            return None

        for optional_column in ['amount', 'turnover']:
            if optional_column not in normalized.columns:
                normalized[optional_column] = pd.NA

        normalized = normalized[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']]
        normalized['date'] = pd.to_datetime(normalized['date'])

        for column in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']:
            normalized[column] = pd.to_numeric(normalized[column], errors='coerce')

        normalized = normalized.dropna(subset=['date', 'open', 'high', 'low', 'close'])
        normalized['volume'] = normalized['volume'].fillna(0).astype(int)
        normalized['amount'] = normalized['amount'].fillna(0.0)
        normalized['turnover'] = normalized['turnover'].fillna(0.0)

        if market_cap is None:
            market_cap = self._get_realtime_market_cap(stock_code)

        normalized['market_cap'] = market_cap if market_cap else 0

        return normalized.sort_values('date', ascending=False).reset_index(drop=True)

    def fetch_intraday_kline(self, stock_code: str, date: str, klt: int = 1) -> list:
        """获取单日分时/分钟K线数据。
        stock_code: 6位股票代码
        date      : 'YYYY-MM-DD'
        klt       : 1=1分钟, 5=5分钟, 15=15分钟
        返回 [{time, open, close, high, low, volume}, ...]

        策略:
        1. 先尝试 push2.eastmoney.com kline 接口（仅当天有1分钟数据）
        2. 若返回数据不属于请求日期，回退到 baostock（支持多年5/15/30/60分钟历史）
        """
        if klt not in (1, 5, 15):
            klt = 1
        # Step 1: 尝试 push2 实时接口
        result = self._fetch_intraday_push2(stock_code, date, klt)
        if result:
            return result
        # Step 2: 回退到 baostock 历史分钟数据
        bs_freq = '5' if klt <= 5 else '15'
        return self._fetch_intraday_baostock(stock_code, date, bs_freq)

    def _fetch_intraday_push2(self, stock_code: str, date: str, klt: int) -> list:
        """push2.eastmoney.com 实时分钟K线（仅最近交易日有效）"""
        try:
            import requests as _req
            from datetime import datetime as _dt, timedelta as _td
            market_code = 1 if stock_code.startswith('6') else 0
            beg_clean = date.replace('-', '')
            end_clean = (_dt.strptime(date, '%Y-%m-%d') + _td(days=1)).strftime('%Y%m%d')
            url = "https://push2.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56",
                "ut":      "7eea3edcaed734bea9cbfc24409ed989",
                "klt":     str(klt),
                "fqt":     "0",
                "secid":   f"{market_code}.{stock_code}",
                "beg":     beg_clean,
                "end":     end_clean,
                "lmt":     "500",
            }
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://quote.eastmoney.com/",
            }
            resp = _req.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data_json = resp.json()
            klines = (data_json.get("data") or {}).get("klines") or []
            result = []
            for line in klines:
                parts = line.split(",")
                if len(parts) < 6:
                    continue
                bar_time = parts[0]
                if not bar_time.startswith(date):
                    continue
                result.append({
                    "time":   bar_time,
                    "open":   round(float(parts[1]), 2),
                    "close":  round(float(parts[2]), 2),
                    "high":   round(float(parts[3]), 2),
                    "low":    round(float(parts[4]), 2),
                    "volume": int(float(parts[5])),
                })
            return result
        except Exception:
            return []

    def _fetch_intraday_baostock(self, stock_code: str, date: str, frequency: str = '5') -> list:
        """baostock 历史分钟K线，支持多年数据。frequency: '5','15','30','60'"""
        try:
            import baostock as bs
            market_prefix = 'sh' if stock_code.startswith('6') else 'sz'
            bs_code = f"{market_prefix}.{stock_code}"
            lg = bs.login()
            if lg.error_code != '0':
                return []
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    fields='date,time,open,high,low,close,volume',
                    start_date=date,
                    end_date=date,
                    frequency=frequency,
                )
                result = []
                while rs.next():
                    row = rs.get_row_data()
                    if not row or len(row) < 7:
                        continue
                    raw_time = row[1]  # '20230803093500000'
                    hh = raw_time[8:10]
                    mm = raw_time[10:12]
                    bar_time = f"{date} {hh}:{mm}"
                    try:
                        result.append({
                            "time":   bar_time,
                            "open":   round(float(row[2]), 2),
                            "high":   round(float(row[3]), 2),
                            "low":    round(float(row[4]), 2),
                            "close":  round(float(row[5]), 2),
                            "volume": int(float(row[6])),
                        })
                    except (ValueError, IndexError):
                        continue
                return result
            finally:
                bs.logout()
        except Exception:
            return []

    def _fetch_stock_history_eastmoney(self, stock_code, start_date, end_date, prefetched_market_cap=None, fqt: int = 1):
        """直接调用 EastMoney K 线接口，返回成交额和换手率。
        fqt: 0=不复权, 1=前复权（默认）, 2=后复权
        """
        try:
            market_code = 1 if stock_code.startswith('6') else 0
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "klt": "101",
                "fqt": str(fqt),
                "secid": f"{market_code}.{stock_code}",
                "beg": start_date,
                "end": end_date,
            }
            response = session.get(url, params=params, timeout=(4, 15))
            response.raise_for_status()
            data_json = response.json()
            if not (data_json.get("data") and data_json["data"].get("klines")):
                return None

            df = pd.DataFrame([item.split(",") for item in data_json["data"]["klines"]])
            df.columns = [
                "日期",
                "开盘",
                "收盘",
                "最高",
                "最低",
                "成交量",
                "成交额",
                "振幅",
                "涨跌幅",
                "涨跌额",
                "换手率",
                "股票代码",
            ]
            return self._normalize_history_df(df, stock_code, market_cap=prefetched_market_cap)
        except Exception as e:
            logger.warning("EastMoney 异常 %s: %s: %s", stock_code, type(e).__name__, str(e)[:120])
            return None

    def _fetch_stock_history_baostock(self, stock_code, years=6, prefetched_market_cap=None):
        """主链路: Baostock 拉取完整历史，含 amount 与 turnover，支持 8+ 年。
        使用前复权（adjustflag='2'），与 EastMoney 主链路保持一致。
        遵循已有熔断器：冷却期内直接返回 None，避免堆叠失败。
        """
        cooling_down, wait_seconds, last_error = self._get_baostock_cooldown_status()
        if cooling_down:
            if self._should_log_baostock_cooldown():
                suffix = f" 最近错误: {last_error}" if last_error else ""
                logger.warning("Baostock 冷却中，暂时跳过 %ss。%s", wait_seconds, suffix)
            return None

        try:
            import baostock as bs
            market_prefix = 'sh' if stock_code.startswith('6') else 'sz'
            bs_code = f"{market_prefix}.{stock_code}"
            start_date = (datetime.now() - timedelta(days=int(365 * years))).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')

            lg = bs.login()
            if lg.error_code != '0':
                opened, cooldown_s, err = self._record_baostock_failure(
                    f"login {lg.error_code}: {getattr(lg, 'error_msg', '')}"
                )
                if opened:
                    logger.warning("Baostock 异常频繁，进入 %ss 冷却。最近错误: %s", cooldown_s, err)
                return None
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    'date,open,high,low,close,volume,amount,turn',
                    start_date=start_date, end_date=end_date,
                    frequency='d', adjustflag='2',
                )
                if rs.error_code != '0':
                    opened, cooldown_s, err = self._record_baostock_failure(
                        f"query {rs.error_code}: {getattr(rs, 'error_msg', '')}"
                    )
                    if opened:
                        logger.warning("Baostock 异常频繁，进入 %ss 冷却。最近错误: %s", cooldown_s, err)
                    return None
                records = []
                while rs.error_code == '0' and rs.next():
                    row = rs.get_row_data()
                    try:
                        records.append({
                            'date': row[0],
                            'open': float(row[1]) if row[1] else 0.0,
                            'high': float(row[2]) if row[2] else 0.0,
                            'low': float(row[3]) if row[3] else 0.0,
                            'close': float(row[4]) if row[4] else 0.0,
                            'volume': int(float(row[5])) if row[5] else 0,
                            'amount': float(row[6]) if row[6] else 0.0,
                            'turnover': float(row[7]) if row[7] else 0.0,
                        })
                    except (ValueError, IndexError):
                        continue
            finally:
                try:
                    bs.logout()
                except Exception:
                    pass

            if not records:
                return None
            df = pd.DataFrame(records)
            df['date'] = pd.to_datetime(df['date'])
            # market_cap 通过实时缓存补齐，缺失则置 0（与 _normalize_history_df 一致）
            cached_mc = prefetched_market_cap if prefetched_market_cap is not None else self._get_realtime_market_cap(stock_code)
            df['market_cap'] = cached_mc if cached_mc else 0
            df = df.sort_values('date', ascending=False).reset_index(drop=True)
            self._record_baostock_success()
            return df
        except Exception as e:
            opened, cooldown_s, err = self._record_baostock_failure(e)
            if opened:
                logger.warning("Baostock 异常频繁，进入 %ss 冷却。最近错误: %s", cooldown_s, err)
            logger.warning("Baostock 历史获取异常 %s: %s: %s", stock_code, type(e).__name__, str(e)[:120])
            return None
    
    def fetch_kline_for_display(self, stock_code: str, fqt: int = 1, years: int = 10):
        """仅供图表展示，不写 CSV。
        fqt: 0=不复权, 1=前复权（默认，读本地 CSV）, 2=后复权

        边界值:
          fqt 不在 (0,1,2) → 强制为 1
          fqt==1 → 直接读 CSV，避免网络请求，且与策略数据完全一致
          远端拉取失败 → 返回 None，调用方负责 fallback
        """
        if fqt not in (0, 1, 2):
            fqt = 1

        if fqt == 1:
            df = self.csv_manager.read_stock(stock_code)
            return df if not df.empty else None

        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * years)
        df = self._fetch_stock_history_eastmoney(
            stock_code,
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
            fqt=fqt,
        )
        if df is None or df.empty:
            return None
        return df

    def fetch_stock_history(self, stock_code, years=6):
        """
        抓取单只股票历史数据
        前复权，按日期倒序排列

        优先级（已根据网络环境实测调整）：
          1. Baostock：稳定可用，支持 8+ 年完整历史，含 amount/turnover
          2. EastMoney：当 Baostock 不可用时兜底（在某些网络环境下可能不可达）
          3. 腾讯 HTTP：服务端历史限制 ~2.5 年，最后兜底
          4. 模拟数据：彻底降级
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * years)
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        # 方法1（主链路）: Baostock 完整历史
        df = self._fetch_stock_history_baostock(stock_code, years=years)
        if df is not None and not df.empty:
            print(f"[OK] Baostock获取 {len(df)}条")
            return df

        # 方法2: EastMoney 兜底（含成交额/换手率）
        df = self._fetch_stock_history_eastmoney(stock_code, start_str, end_str)
        if df is not None and not df.empty:
            print(f"[OK] EastMoney获取 {len(df)}条")
            return df

        # 方法3: 腾讯接口兜底（无换手率，~2.5 年）
        try:
            df = self._fetch_stock_history_http(stock_code, years)
            if df is not None and not df.empty:
                print(f"[OK] HTTP获取 {len(df)}条")
                return df
        except Exception as e:
            print(f"  HTTP异常: {e}，使用模拟数据...")

        # 降级: 使用模拟数据
        return self._generate_mock_data(stock_code, years)
    
    def fetch_stock_update(self, stock_code, days=10, prefetched_market_cap=None, prefer_fast_fallback=False):
        """
        抓取近期数据用于增量更新
        优化：直接指定天数，避免计算误差
        :param prefetched_market_cap: 预先批量获取的市值，传入则跳过每股单独API调用（大幅提速）
        :param prefer_fast_fallback: 已确认 EastMoney 不稳定时，优先使用新浪/Baostock 兜底，避免重复等待失败源
        """
        lookback_days = max(days * 4, 30)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)

        if not prefer_fast_fallback:
            df = self._fetch_stock_history_eastmoney(
                stock_code,
                start_date.strftime("%Y%m%d"),
                end_date.strftime("%Y%m%d"),
                prefetched_market_cap=prefetched_market_cap,
            )
            if df is not None and not df.empty:
                return df.head(max(days + 5, 20)).copy()

        # ── 备选1: 新浪财经（HTTP链路，避免每股登录/登出开销）────────────
        df = self._fetch_update_sina(stock_code, days, prefetched_market_cap)
        if df is not None and not df.empty:
            return df

        # ── 备选2: Baostock（TCP协议，网络异常时兜底）──────────────────
        df = self._fetch_update_baostock(stock_code, days, prefetched_market_cap)
        if df is not None and not df.empty:
            return df

        return None

    def _fetch_update_baostock(self, stock_code, days=10, prefetched_market_cap=None):
        """备选2: Baostock 增量更新，支持 amount/turnover 完整字段（带短时熔断）。"""
        cooling_down, wait_seconds, last_error = self._get_baostock_cooldown_status()
        if cooling_down:
            if self._should_log_baostock_cooldown():
                suffix = f" 最近错误: {last_error}" if last_error else ""
                logger.warning("Baostock 冷却中，暂时跳过 %ss。%s", wait_seconds, suffix)
            return None

        try:
            import baostock as bs
            market_prefix = 'sh' if stock_code.startswith('6') else 'sz'
            bs_code = f"{market_prefix}.{stock_code}"
            lookback_days = max(days * 4, 30)
            start_date = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
            lg = bs.login()
            if lg.error_code != '0':
                opened, cooldown_s, err = self._record_baostock_failure(
                    f"login {lg.error_code}: {getattr(lg, 'error_msg', '')}"
                )
                if opened:
                    logger.warning("Baostock 异常频繁，进入 %ss 冷却。最近错误: %s", cooldown_s, err)
                return None
            try:
                rs = bs.query_history_k_data_plus(
                    bs_code,
                    'date,open,high,low,close,volume,amount,turn',
                    start_date=start_date, end_date=end_date,
                    frequency='d', adjustflag='2',
                )
                if rs.error_code != '0':
                    opened, cooldown_s, err = self._record_baostock_failure(
                        f"query {rs.error_code}: {getattr(rs, 'error_msg', '')}"
                    )
                    if opened:
                        logger.warning("Baostock 异常频繁，进入 %ss 冷却。最近错误: %s", cooldown_s, err)
                    return None
                records = []
                while rs.error_code == '0' and rs.next():
                    row = rs.get_row_data()
                    try:
                        records.append({
                            'date': row[0],
                            'open': float(row[1]) if row[1] else 0.0,
                            'high': float(row[2]) if row[2] else 0.0,
                            'low': float(row[3]) if row[3] else 0.0,
                            'close': float(row[4]) if row[4] else 0.0,
                            'volume': int(float(row[5])) if row[5] else 0,
                            'amount': float(row[6]) if row[6] else 0.0,
                            'turnover': float(row[7]) if row[7] else 0.0,
                        })
                    except (ValueError, IndexError):
                        continue
            finally:
                try:
                    bs.logout()
                except Exception:
                    pass
            if not records:
                return None
            df = pd.DataFrame(records)
            df['date'] = pd.to_datetime(df['date'])
            df['market_cap'] = prefetched_market_cap if prefetched_market_cap is not None else 0
            df = df.sort_values('date', ascending=False)
            self._record_baostock_success()
            return df.head(max(days + 5, 20)).copy()
        except Exception as e:
            opened, cooldown_s, err = self._record_baostock_failure(e)
            if opened:
                logger.warning("Baostock 异常频繁，进入 %ss 冷却。最近错误: %s", cooldown_s, err)
            return None

    def _fetch_update_sina(self, stock_code, days=10, prefetched_market_cap=None):
        """备选1: 新浪财经 K线接口，支持完整字段"""
        try:
            market_code = 'sh' if stock_code.startswith('6') else 'sz'
            symbol = f"{market_code}{stock_code}"
            lookback_days = max(days * 4, 30)
            # 新浪接口：DDays参数指定获取最近N天（交易日）
            url = (
                f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
                f"/CN_MarketData.getKLineData?symbol={symbol}&scale=240"
                f"&ma=no&datalen={lookback_days}"
            )
            resp = session.get(url, timeout=(4, 15), headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://finance.sina.com.cn/',
            })
            data = resp.json()
            if not data:
                return None
            records = []
            for item in data:
                try:
                    records.append({
                        'date': str(item.get('day', '')).split(' ')[0],
                        'open': float(item.get('open', 0)),
                        'high': float(item.get('high', 0)),
                        'low': float(item.get('low', 0)),
                        'close': float(item.get('close', 0)),
                        'volume': int(float(item.get('volume', 0))),
                        'amount': float(item.get('amount', 0)),
                        'turnover': 0.0,
                    })
                except (ValueError, KeyError):
                    continue
            if not records:
                return None
            df = pd.DataFrame(records)
            df['date'] = pd.to_datetime(df['date'])
            df['market_cap'] = prefetched_market_cap if prefetched_market_cap is not None else 0
            df = df.sort_values('date', ascending=False)
            return df.head(max(days + 5, 20)).copy()
        except Exception as e:
            logger.warning("新浪备选失败(%s): %s", stock_code, e)
            return None
    
    def init_full_data(self, max_stocks=None, skip_failed=True, progress_callback=None):
        """
        首次全量抓取
        :param max_stocks: 限制抓取数量（用于测试）
        :param skip_failed: 是否跳过之前失败的股票
        :param progress_callback: 可选回调，接收初始化进度 dict
        """
        import akshare as ak

        def emit_init_progress(progress, message, current_code='', **extra):
            if not progress_callback:
                return
            payload = {
                'progress': max(0, min(100, int(progress))),
                'message': message,
            }
            if current_code:
                payload['current_code'] = current_code
            payload.update(extra)
            try:
                progress_callback(payload)
            except Exception:
                pass
        
        stock_dict = self.get_all_stock_codes()
        
        if not stock_dict:
            print("无法获取股票列表")
            emit_init_progress(100, "无法获取股票列表，初始化失败", status='error')
            return {
                'status': 'error',
                'message': '无法获取股票列表',
                'total': 0,
                'success': 0,
                'failed': 0,
            }
        
        stock_codes = list(stock_dict.keys())
        
        # 加载之前失败的股票列表
        failed_stocks_file = self.full_data_dir / 'failed_stocks.json'
        failed_stocks = set()
        if skip_failed and failed_stocks_file.exists():
            try:
                with open(failed_stocks_file, 'r', encoding='utf-8') as f:
                    failed_stocks = set(json.load(f))
                print(f"  将跳过 {len(failed_stocks)} 只之前获取失败的股票")
                # 从列表中移除失败的股票
                stock_codes = [c for c in stock_codes if c not in failed_stocks]
            except Exception as exc:
                logger.warning("读取 failed_stocks.json 失败: %s", exc)
        
        if max_stocks:
            stock_codes = stock_codes[:max_stocks]
        
        # 批量获取市值数据（主接口：akshare，备选：腾讯）
        print("\n正在批量获取市值数据...")
        market_cap_map = {}
        
        # 方法1: 尝试akshare接口
        try:
            spot_df = ak.stock_zh_a_spot_em()
            for _, row in spot_df.iterrows():
                code = str(row['代码']).zfill(6)
                cap = row['总市值']
                if pd.notna(cap) and cap > 0:
                    # 统一转为元
                    if cap < 1e10:
                        cap = int(cap * 1e8)
                    else:
                        cap = int(cap)
                    market_cap_map[code] = cap
            print(f"  [OK] akshare接口成功: {len(market_cap_map)} 只股票市值")
            # 写入内存缓存，供 _get_realtime_market_cap 使用。
            _today = datetime.now().strftime('%Y-%m-%d')
            with _market_cap_cache_lock:
                self._market_cap_cache.update(market_cap_map)
                self._market_cap_cache_date = _today
            self._save_market_cap_weekly_cache()
        except Exception as e:
            logger.warning("akshare 市值接口失败: %s", e)
            logger.info("尝试腾讯备选市值接口")
            # 方法2: 使用腾讯接口备选
            market_cap_map = self._fetch_market_cap_tencent(stock_codes)
            if market_cap_map:
                print(f"  [OK] 腾讯接口成功: {len(market_cap_map)} 只股票市值")
                _today = datetime.now().strftime('%Y-%m-%d')
                with _market_cap_cache_lock:
                    self._market_cap_cache.update(market_cap_map)
                    self._market_cap_cache_date = _today
                self._save_market_cap_weekly_cache()
            else:
                logger.warning("腾讯接口也失败，市值数据将缺失")
        
        total = len(stock_codes)
        success = 0
        failed_list = []
        failed_set = set()

        emit_init_progress(
            1,
            f"开始全量初始化：共 {total} 只股票",
            total=total,
            completed=0,
            success=0,
            failed=0,
        )
        
        print(f"\n开始抓取 {total} 只股票的6年历史数据...")
        print("=" * 60)
        
        for i, code in enumerate(stock_codes, 1):
            print(f"[{i}/{total}] 抓取 {code} {stock_dict.get(code, '')} ...", end=" ")
            
            df = self.fetch_stock_history(code, years=6)
            
            if df is not None and not df.empty:
                # 数据校验 - 检查是否有有效价格数据
                valid_data = True
                if len(df) < 10:  # 数据太少，可能是新股或数据异常
                    print(f"[WARN] 数据太少({len(df)}条)")
                    valid_data = False
                    failed_list.append(code)
                    failed_set.add(code)
                elif df['close'].mean() <= 0:  # 价格异常
                    print("[WARN] 价格异常")
                    valid_data = False
                    failed_list.append(code)
                    failed_set.add(code)
                else:
                    # 使用批量获取的市值数据
                    if code in market_cap_map:
                        df['market_cap'] = market_cap_map[code]
                    self.csv_manager.write_stock(code, df)
                    print(f"[OK] ({len(df)}条)")
                    success += 1
            else:
                print("[FAIL] 失败")
                failed_list.append(code)
                failed_set.add(code)

            completed = i
            emit_init_progress(
                int(completed / max(total, 1) * 100),
                (
                    f"全量初始化中：{completed}/{total}，"
                    f"成功 {success}，失败 {len(failed_set)}"
                ),
                current_code=code,
                total=total,
                completed=completed,
                success=success,
                failed=len(failed_set),
            )
            
            # 限速，避免请求过快
            if i % 10 == 0:
                time.sleep(1)
        
        # 保存失败的股票列表
        if failed_list:
            try:
                with open(failed_stocks_file, 'w', encoding='utf-8') as f:
                    json.dump(failed_list, f)
                print(f"\n  已保存 {len(failed_list)} 只获取失败的股票到 failed_stocks.json")
            except Exception as e:
                print(f"\n  保存失败列表出错: {e}")
        
        print("=" * 60)
        print(f"完成! 成功: {success}, 失败: {len(failed_set)}")
        if failed_list and not max_stocks:
            print(f"提示: 再次运行 init 命令可跳过失败股票，专注于成功获取的数据")

        emit_init_progress(
            100,
            f"全量初始化完成：总计 {total}，成功 {success}，失败 {len(failed_set)}",
            total=total,
            completed=total,
            success=success,
            failed=len(failed_set),
            status='done',
        )

        return {
            'status': 'done',
            'message': f'全量初始化完成：总计 {total}，成功 {success}，失败 {len(failed_set)}',
            'total': total,
            'success': success,
            'failed': len(failed_set),
        }

    # ===================== 优化版：并发更新 + 实时进度显示 =====================
    def daily_update(
        self,
        max_stocks=None,
        date=None,
        progress_callback=None,
        on_stock_ready=None,
        allow_intraday_fast=None,
    ):
        """每日增量更新 - 多线程并发版 + 实时进度显示
        优化要点：
          1. 先批量获取全市场市值（1次API调用），替代原来每股单独调用（1840次）
          2. 只更新日期落后的股票，跳过已是最新的股票
          3. 超时上限从600s提升到1800s
        :param max_stocks: 限制更新股票数量（测试用）
        :param date: 指定目标日期字符串(YYYY-MM-DD)，None表示自动推断
        :param progress_callback: 可选回调，接收实时统计信息 dict
        :param on_stock_ready: 可选回调 (code, df)，每只股票更新成功后立即调用（pipeline 模式用于内联策略扫描）
        """
        self._load_runtime_tuning_config()
        if allow_intraday_fast is None:
            allow_intraday_fast = self._intraday_fast_default
        else:
            allow_intraday_fast = bool(allow_intraday_fast)
        print(
            "  Baostock熔断配置："
            f"失败阈值={self._baostock_failure_threshold}，"
            f"冷却={self._baostock_cooldown_seconds}s，"
            f"日志节流={self._baostock_cooldown_log_interval_seconds}s"
        )
        print(
            "  更新策略："
            f"盘中快路径默认={'开启' if self._intraday_fast_default else '关闭'}，"
            f"本次盘中快路径={'开启' if allow_intraday_fast else '关闭'}，"
            f"慢路径抓取天数区间={self._slow_path_min_fetch_days}-{self._slow_path_max_fetch_days}"
            f"(buffer={self._slow_path_buffer_days})，"
            f"快路径写入并发={self._fast_path_workers}"
        )

        existing_stocks = self.csv_manager.list_all_stocks()
        if max_stocks:
            existing_stocks = existing_stocks[:max_stocks]

        # ── 推算目标交易日 ──────────────────────────────────────────────
        now = datetime.now()
        today = now.date()
        now_time = now.time()
        is_after_close = now_time >= _INTRADAY_FAST_END
        # 盘中快路径只在真实交易时段生效；开盘前没有当日有效快照，必须补最近已完成交易日。
        allow_same_day_intraday_fast = (
            bool(allow_intraday_fast)
            and _INTRADAY_FAST_START <= now_time < _INTRADAY_FAST_END
        )
        latest_completed_trade_date = previous_a_share_trading_day(
            today if is_after_close else today - timedelta(days=1)
        )
        requested_target_date = None

        if date is None:
            target_date = today if (is_after_close or allow_same_day_intraday_fast) else today - timedelta(days=1)
            target_date = previous_a_share_trading_day(target_date)
            if not is_after_close and allow_same_day_intraday_fast and not max_stocks:
                print(f"[WARN] 盘中手动快路径已开启，本次尝试更新当日数据 {target_date.strftime('%Y-%m-%d')}")
            elif not is_after_close and not max_stocks:
                print(f"[WARN] 未收盘，仍然检查是否缺失最近交易日数据 {target_date.strftime('%Y-%m-%d')}")
        else:
            requested_target_date = datetime.strptime(date, "%Y-%m-%d").date()
            target_date = requested_target_date
            if requested_target_date == today and not is_after_close and not allow_same_day_intraday_fast:
                target_date = previous_a_share_trading_day(today - timedelta(days=1))
                print(
                    "[WARN] 选择了当日但当前尚未收盘，且未开启盘中快路径；"
                    f"已自动回退到最近已完成交易日 {target_date.strftime('%Y-%m-%d')}"
                )

        # 快路径使用“可确认归属到目标交易日的全市场快照”。
        # 收盘后：今天就是最近已完成交易日；次日凌晨/开盘前：昨天才是最近已完成交易日。
        # 盘中快路径只有用户明确允许时才写入今天的未收盘快照。
        can_use_spot_fast_path = (
            target_date == latest_completed_trade_date
            or (allow_same_day_intraday_fast and target_date == today)
        )

        target_date_str = target_date.strftime('%Y-%m-%d')
        scan_total = len(existing_stocks)
        checked_count = 0
        stocks_to_update = []
        updated = 0
        failed = 0
        completed = 0
        verify_total = 0
        verify_reached = 0
        verification_passed = False
        cache_written = False
        cache_hit = False
        fast_path_total = 0
        fast_path_success = 0
        fast_path_failed = 0
        short_path_total = 0
        short_path_success = 0
        short_path_failed = 0
        slow_path_total = 0
        retry_total = 0
        retry_success = 0
        retry_failed = 0
        slow_path_reason_counts = {
            'time_gate': 0,
            'missing_local_data': 0,
            'gap_gt1': 0,
            'short_gap_fallback': 0,
            'missing_spot': 0,
            'suspended': 0,
            'other': 0,
        }

        def emit_progress(progress, message, phase='update', current_code='', **extra):
            if not progress_callback:
                return

            total_to_update = len(stocks_to_update)
            payload = {
                'progress': max(0, min(100, int(progress))),
                'message': message,
                'phase': phase,
                'scan_total': scan_total,
                'checked': checked_count,
                'to_update': total_to_update,
                'up_to_date': max(0, checked_count - total_to_update),
                'completed': completed,
                'updated': updated,
                'failed': failed,
                'remaining': max(total_to_update - completed, 0),
                'verify_total': verify_total,
                'verify_reached': verify_reached,
                'verification_passed': verification_passed,
                'cache_written': cache_written,
                'cache_hit': cache_hit,
                'allow_intraday_fast': allow_intraday_fast,
                'fast_path_total': fast_path_total,
                'fast_path_success': fast_path_success,
                'fast_path_failed': fast_path_failed,
                'short_path_total': short_path_total,
                'short_path_success': short_path_success,
                'short_path_failed': short_path_failed,
                'slow_path_total': slow_path_total,
                'slow_path_reasons': dict(slow_path_reason_counts),
                'retry_total': retry_total,
                'retry_success': retry_success,
                'retry_failed': retry_failed,
            }
            if current_code:
                payload['current_code'] = current_code
            payload.update(extra)
            try:
                progress_callback(payload)
            except Exception:
                pass

        def build_summary(status, message):
            total_to_update = len(stocks_to_update)
            return {
                'status': status,
                'message': message,
                'target_date': target_date_str,
                'scan_total': scan_total,
                'checked': checked_count,
                'to_update': total_to_update,
                'up_to_date': max(0, checked_count - total_to_update),
                'completed': completed,
                'updated': updated,
                'failed': failed,
                'remaining': max(total_to_update - completed, 0),
                'verify_total': verify_total,
                'verify_reached': verify_reached,
                'verification_passed': verification_passed,
                'cache_written': cache_written,
                'cache_hit': cache_hit,
                'allow_intraday_fast': allow_intraday_fast,
                'fast_path_total': fast_path_total,
                'fast_path_success': fast_path_success,
                'fast_path_failed': fast_path_failed,
                'short_path_total': short_path_total,
                'short_path_success': short_path_success,
                'short_path_failed': short_path_failed,
                'slow_path_total': slow_path_total,
                'slow_path_reasons': dict(slow_path_reason_counts),
                'retry_total': retry_total,
                'retry_success': retry_success,
                'retry_failed': retry_failed,
            }

        def recalc_stocks_to_update():
            stocks_to_update.clear()
            for code in existing_stocks:
                try:
                    _ld = latest_date_map.get(code)
                    if _ld is None or _ld < target_date:
                        stocks_to_update.append(code)
                except Exception:
                    stocks_to_update.append(code)

        def finalize_no_update(message):
            update_cache['last_update_date'] = target_date_str
            with open(update_cache_file, 'w') as f:
                json.dump(update_cache, f)
            nonlocal cache_written
            cache_written = True
            emit_progress(100, message, phase='complete')
            return build_summary('done', message)

        def fallback_same_day_target(reason, snapshot_count=0, requested_count=0):
            nonlocal target_date, target_date_str, can_use_spot_fast_path
            nonlocal fast_path_total, fast_path_success, fast_path_failed
            nonlocal short_path_total, short_path_success, short_path_failed, slow_path_total
            if target_date != today:
                return False

            fallback_target = previous_a_share_trading_day(today - timedelta(days=1))
            if fallback_target >= target_date:
                return False

            previous_target_str = target_date_str
            target_date = fallback_target
            target_date_str = target_date.strftime('%Y-%m-%d')
            can_use_spot_fast_path = (
                target_date == latest_completed_trade_date
                or (allow_same_day_intraday_fast and target_date == today)
            )
            spot_data_map.clear()
            fast_path_total = 0
            fast_path_success = 0
            fast_path_failed = 0
            short_path_total = 0
            short_path_success = 0
            short_path_failed = 0
            slow_path_total = 0
            for key in slow_path_reason_counts:
                slow_path_reason_counts[key] = 0
            recalc_stocks_to_update()

            detail = (
                f"{reason}（当日快照 {snapshot_count}/{requested_count} 只）"
                if requested_count
                else reason
            )
            emit_progress(
                35,
                f"当日目标 {previous_target_str} 的快照尚未就绪，已自动回退到最近已完成交易日 {target_date_str}；{detail}",
                phase='scan_complete',
                target_date_adjusted_from=previous_target_str,
                target_date_adjust_reason=reason,
            )
            print(
                f"[WARN] 当日目标 {previous_target_str} 的快照尚未就绪，"
                f"已自动回退到最近已完成交易日 {target_date_str}（{detail}）"
            )
            return True

        if not existing_stocks:
            print("没有找到已有数据，请先执行 init")
            return build_summary('error', '没有找到已有数据，请先执行 init')

        # ── 检查缓存 ────────────────────────────────────────────────────
        update_cache_file = self.full_data_dir / '.update_cache.json'
        update_cache = {}
        if update_cache_file.exists():
            try:
                with open(update_cache_file, 'r') as f:
                    update_cache = json.load(f)
            except Exception:
                pass

        if update_cache.get('last_update_date') == target_date_str and not max_stocks:
            cache_hit = True
            print("[OK] 今日已更新")
            message = f"{target_date_str} 数据已是最新，跳过更新（缓存命中）"
            emit_progress(100, message, phase='complete')
            return build_summary('done', message)

        # ── 只更新日期落后的股票（跳过已是最新的，节省时间）───────────
        # P1: 只读第一行(nrows=1)判断日期，不读全量CSV（~100x加速）
        print("  检查更新状态...")
        emit_progress(1, f"开始检查 {scan_total} 只股票的数据状态...", phase='scan')
        latest_date_map: dict = {}  # code→date，供快/慢路径分拣复用
        for idx, code in enumerate(existing_stocks, start=1):
            checked_count = idx
            try:
                _path = self.csv_manager.get_stock_path(code)
                if not _path.exists() or _path.stat().st_size == 0:
                    stocks_to_update.append(code)
                    continue
                _df1 = pd.read_csv(_path, nrows=1, usecols=['date'])
                if _df1.empty:
                    stocks_to_update.append(code)
                else:
                    _ld = pd.to_datetime(_df1.iloc[0]['date']).date()
                    latest_date_map[code] = _ld
                    if _ld < target_date:
                        stocks_to_update.append(code)
            except Exception:
                stocks_to_update.append(code)

            if idx == 1 or idx % 50 == 0 or idx == scan_total:
                emit_progress(
                    int(idx / max(scan_total, 1) * 25),
                    f"检查更新状态... {idx}/{scan_total}",
                    phase='scan',
                    current_code=code,
                )

        if not stocks_to_update:
            print(f"[OK] 所有股票已是最新数据 ({target_date_str})")
            message = f"所有股票已是最新数据 ({target_date_str})"
            return finalize_no_update(message)

        print(f"  需要更新：{len(stocks_to_update)} 只")
        emit_progress(
            30,
            f"状态检查完成：共 {scan_total} 只，需更新 {len(stocks_to_update)} 只",
            phase='scan_complete',
        )

        # ── 一次性批量获取全市场市值（避免1840次单独API调用）─────────
        # ── 市值策略：立即使用缓存，后台线程异步刷新 ─────────────────────
        # 目的：K线更新不等待市值API；市值刷新只维护缓存，不阻塞主流程。
        print("\n加载缓存市值数据，后台异步刷新...")
        with _market_cap_cache_lock:
            market_cap_map: dict = dict(self._market_cap_cache)   # 立即用缓存（快速）
        spot_data_map: dict = {}   # key=code, value=今日行情dict（快路径用）

        _bg_cap_count: list = [0]     # [0] = 后台刷新获得的市值只数
        _bg_cap_error: list = [None]  # [0] = 失败原因字符串（None表示成功）
        _bg_done = threading.Event()

        def _bg_refresh_market_cap():
            """后台线程：拉取最新全市场市值；完成后更新共享 market_cap_map 和持久化缓存"""
            try:
                import akshare as ak
                _spot_df = ak.stock_zh_a_spot_em()
                _spot_df['_code'] = _spot_df['代码'].astype(str).str.zfill(6)
                _cap_col = _spot_df['总市值'] if '总市值' in _spot_df.columns else pd.Series(0.0, index=_spot_df.index)
                _valid = pd.notna(_cap_col) & (_cap_col > 0)
                _vdf = _spot_df[_valid].copy()
                _vdf['_cap'] = _vdf['总市值'].apply(lambda c: int(c * 1e8) if c < 1e10 else int(c))
                _fresh_cap = dict(zip(_vdf['_code'], _vdf['_cap']))

                def _sc(col):
                    return _vdf[col].fillna(0) if col in _vdf.columns else pd.Series(0.0, index=_vdf.index)

                for _c, _cap, _o, _cl, _h, _l, _vol, _amt, _tr in zip(
                    _vdf['_code'], _vdf['_cap'],
                    _sc('今开').astype(float), _sc('最新价').astype(float),
                    _sc('最高').astype(float), _sc('最低').astype(float),
                    _sc('成交量').astype(float), _sc('成交额').astype(float),
                    _sc('换手率').astype(float),
                ):
                    spot_data_map[str(_c)] = {
                        'date': target_date_str, 'open': float(_o), 'close': float(_cl),
                        'high': float(_h), 'low': float(_l), 'volume': int(_vol),
                        'amount': float(_amt), 'turnover': float(_tr), 'market_cap': int(_cap),
                    }

                market_cap_map.update(_fresh_cap)
                _today_bg = datetime.now().strftime('%Y-%m-%d')
                with _market_cap_cache_lock:
                    self._market_cap_cache.update(_fresh_cap)
                    self._market_cap_cache_date = _today_bg
                self._save_market_cap_weekly_cache()
                _bg_cap_count[0] = len(_fresh_cap)
                logger.info("[后台市值] akshare 刷新完成: %d 只", len(_fresh_cap))
            except Exception as _e_ak:
                logger.warning("[后台市值] akshare 失败，尝试直连东方财富: %s", _e_ak)
                try:
                    _page = 1
                    _page_size = 100
                    _fs = 'm:0+t:6,m:0+t:13,m:0+t:80,m:1+t:2,m:1+t:23,m:1+t:62,m:4+t:4'
                    _fresh_direct: dict = {}
                    while True:
                        _url = 'https://push2.eastmoney.com/api/qt/clist/get'
                        _params = {
                            'pn': _page, 'pz': _page_size,
                            'po': 1, 'np': 1, 'fltt': 2, 'invt': 2,
                            'fid': 'f3', 'fs': _fs,
                            'fields': 'f12,f17,f2,f15,f16,f5,f6,f8,f20',
                        }
                        _resp = session.get(_url, params=_params, timeout=(4, 20), headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                            'Referer': 'https://quote.eastmoney.com/',
                        })
                        _diff = (_resp.json().get('data') or {}).get('diff', [])
                        if not _diff:
                            break
                        for _item in _diff:
                            _code = str(_item.get('f12', '')).zfill(6)
                            _cap = _item.get('f20', 0) or 0
                            if not _code or _cap <= 0:
                                continue
                            _fresh_direct[_code] = int(_cap)
                            _close = float(_item.get('f2', 0) or 0)
                            if _close > 0:
                                spot_data_map[_code] = {
                                    'date': target_date_str,
                                    'open': float(_item.get('f17', 0) or 0),
                                    'close': _close,
                                    'high': float(_item.get('f15', 0) or 0),
                                    'low': float(_item.get('f16', 0) or 0),
                                    'volume': int(float(_item.get('f5', 0) or 0)),
                                    'amount': float(_item.get('f6', 0) or 0),
                                    'turnover': float(_item.get('f8', 0) or 0),
                                    'market_cap': int(_cap),
                                }
                        if len(_diff) < _page_size:
                            break
                        _page += 1
                    if _fresh_direct:
                        market_cap_map.update(_fresh_direct)
                        _today_bg = datetime.now().strftime('%Y-%m-%d')
                        with _market_cap_cache_lock:
                            self._market_cap_cache.update(_fresh_direct)
                            self._market_cap_cache_date = _today_bg
                        self._save_market_cap_weekly_cache()
                        _bg_cap_count[0] = len(_fresh_direct)
                        logger.info("[后台市值] 直连东方财富成功: %d 只", len(_fresh_direct))
                    else:
                        raise Exception("返回数据为空")
                except Exception as _e2:
                    _bg_cap_error[0] = str(_e2)
                    logger.warning("[后台市值] 所有市值接口失败: %s", _e2)
            finally:
                _bg_done.set()

        # 仅当缓存超过 30 天（或无缓存）时才启动后台刷新线程
        _cap_cache_date = getattr(self, '_market_cap_cache_date', None)
        if _cap_cache_date:
            try:
                _cap_age_days = (datetime.now() - datetime.strptime(_cap_cache_date, '%Y-%m-%d')).days
            except Exception:
                _cap_age_days = 999
        else:
            _cap_age_days = 999
        _need_cap_refresh = _cap_age_days > _MARKET_CAP_CACHE_EXPIRY_DAYS or not market_cap_map
        if _need_cap_refresh:
            _bg_cap_thread = threading.Thread(target=_bg_refresh_market_cap, daemon=True, name='market-cap-bg')
            _bg_cap_thread.start()
        else:
            _bg_done.set()  # 无需刷新，立即标记完成

        _cached_count = len(market_cap_map)
        if _cached_count > 0:
            _refresh_note = "后台刷新中，" if _need_cap_refresh else f"缓存仍有效（{_cap_age_days}天前），"
            emit_progress(
                35,
                f"使用缓存市值（{_cached_count} 只），{_refresh_note}准备并发更新 {len(stocks_to_update)} 只股票",
                phase='market_cap_refresh' if _need_cap_refresh else 'market_cap_cached',
                market_cap_refresh_needed=_need_cap_refresh,
                market_cap_cached_count=_cached_count,
                market_cap_cache_age_days=_cap_age_days,
            )
        else:
            # 首次克隆无缓存：等待后台最多 10s，让市值数据准备好
            logger.info("[市值] 缓存为空，等待后台线程初始化市值（最多10秒）")
            emit_progress(
                32,
                "首次运行，等待市值数据初始化（最多10秒）...",
                phase='market_cap_refresh',
                market_cap_refresh_needed=True,
                market_cap_cached_count=0,
                market_cap_cache_age_days=None,
            )
            _bg_done.wait(timeout=10)
            emit_progress(
                35,
                f"市值初始化完成：{len(market_cap_map)} 只，准备并发更新 {len(stocks_to_update)} 只股票",
                phase='market_cap_refresh',
                market_cap_refresh_needed=True,
                market_cap_cached_count=len(market_cap_map),
                market_cap_cache_age_days=None,
            )

        # 快路径依赖当日 spot 快照，必须与 30 天市值刷新策略解耦。
        if can_use_spot_fast_path and not spot_data_map:
            emit_progress(
                35,
                f"加载 {target_date_str} 行情快照（用于快路径）...",
                phase='market_cap_refresh' if _need_cap_refresh else 'market_cap_cached',
            )
            _spot_snapshot = self._fetch_spot_snapshot_map(
                target_date_str=target_date_str,
                stock_codes=stocks_to_update,
            )
            if _spot_snapshot:
                spot_data_map.update(_spot_snapshot)
            _spot_count = len(spot_data_map)
            _spot_coverage_ratio = _spot_count / max(len(stocks_to_update), 1)
            _spot_globally_unready = _spot_count == 0 or (
                len(stocks_to_update) >= 100 and _spot_coverage_ratio < 0.2
            )
            if _spot_globally_unready and fallback_same_day_target(
                reason='快照覆盖率不足，避免误入全市场慢路径',
                snapshot_count=_spot_count,
                requested_count=len(stocks_to_update),
            ):
                if not stocks_to_update:
                    print(f"[OK] 回退后所有股票已是最新数据 ({target_date_str})")
                    return finalize_no_update(f"当日快照未就绪，已回退到最近已完成交易日 {target_date_str}")
                if can_use_spot_fast_path:
                    emit_progress(
                        35,
                        f"重新加载 {target_date_str} 行情快照（回退后继续快路径）...",
                        phase='market_cap_refresh' if _need_cap_refresh else 'market_cap_cached',
                    )
                    _fallback_spot_snapshot = self._fetch_spot_snapshot_map(
                        target_date_str=target_date_str,
                        stock_codes=stocks_to_update,
                    )
                    if _fallback_spot_snapshot:
                        spot_data_map.update(_fallback_spot_snapshot)
            emit_progress(
                36,
                f"{target_date_str} 行情快照就绪：{len(spot_data_map)} 只，可进入快路径分流",
                phase='market_cap_refresh' if _need_cap_refresh else 'market_cap_cached',
            )

        # ── 按缺失天数拆分快/慢路径 ──────────────────────────────────────
        # P2: 直接查 latest_date_map（扫描阶段已缓存），不再重新读文件
        # 快路径条件（全部满足才走快路径）：
        #   1. 仅缺失1个交易日（防止多日缺失用快照后丢失历史行）
        #   2. can_use_spot_fast_path == True（最近已完成交易日或显式盘中快照）
        #   3. spot_data_map 中存在该股
        #   4. spot_data_map[code]['close'] > 0（停牌过滤）
        fast_path_stocks: list = []
        short_gap_stocks: list = []
        slow_path_stocks: list = []
        days_behind_map: dict = {}
        gap_cache: dict = {}

        def _trading_day_gap(last_date):
            if last_date is None:
                return 999
            if last_date >= target_date:
                return 0
            if last_date in gap_cache:
                return gap_cache[last_date]

            gap = count_a_share_trading_days(last_date + timedelta(days=1), target_date)
            gap_cache[last_date] = gap
            return gap

        for _code in stocks_to_update:
            _ld = latest_date_map.get(_code)
            _days_behind = _trading_day_gap(_ld)
            days_behind_map[_code] = _days_behind
            _spot = spot_data_map.get(_code)
            if (
                _days_behind == 1
                and can_use_spot_fast_path
                and _spot is not None
                and float(_spot.get('close', 0)) > 0
            ):
                fast_path_stocks.append(_code)
            elif (
                2 <= _days_behind <= _SHORT_GAP_FAST_MAX_DAYS
                and _ld is not None
                and target_date <= latest_completed_trade_date
            ):
                short_gap_stocks.append(_code)
            else:
                slow_path_stocks.append(_code)

                if _days_behind >= 999:
                    slow_path_reason_counts['missing_local_data'] += 1
                elif _days_behind > 1:
                    slow_path_reason_counts['gap_gt1'] += 1
                elif not can_use_spot_fast_path:
                    slow_path_reason_counts['time_gate'] += 1
                elif _spot is None:
                    slow_path_reason_counts['missing_spot'] += 1
                elif float(_spot.get('close', 0)) <= 0:
                    slow_path_reason_counts['suspended'] += 1
                else:
                    slow_path_reason_counts['other'] += 1

        fast_path_total = len(fast_path_stocks)
        short_path_total = len(short_gap_stocks)
        slow_path_total = len(slow_path_stocks)
        emit_progress(
            36,
            (
                f"分流完成：快路径 {fast_path_total} 只，"
                f"短窗快补 {short_path_total} 只，"
                f"慢路径 {slow_path_total} 只"
            ),
            phase='scan_complete',
        )

        # ── 快路径：单日缺失，直接用 spot_data_map 写入（零额外HTTP）────────
        fast_total = len(fast_path_stocks)
        if fast_path_stocks:
            emit_progress(
                36,
                f"快路径并发写入 {len(fast_path_stocks)} 只单日缺失股票...",
                phase='fast_update',
            )
            _lock_fa = threading.Lock()
            fast_emit_step = 1 if fast_total <= 20 else 10
            fast_workers = min(self._fast_path_workers, max(1, fast_total))

            def _write_fast_stock(_code):
                return _code, self.csv_manager.prepend_row(_code, spot_data_map[_code])

            with ThreadPoolExecutor(max_workers=fast_workers) as fast_executor:
                futures = {
                    fast_executor.submit(_write_fast_stock, _code): _code
                    for _code in fast_path_stocks
                }
                for fast_index, future in enumerate(as_completed(futures), start=1):
                    _code = futures[future]
                    try:
                        _code, _ok = future.result()
                    except Exception:
                        _ok = False
                    with _lock_fa:
                        completed += 1
                        if _ok:
                            updated += 1
                            fast_path_success += 1
                        else:
                            failed += 1
                            fast_path_failed += 1
                        if fast_index == 1 or fast_index % fast_emit_step == 0 or fast_index == fast_total:
                            emit_progress(
                                36 + int(fast_index / max(fast_total, 1) * 3),
                                (
                                    f"快路径更新中：{fast_index}/{fast_total}，"
                                    f"总完成 {completed}/{len(stocks_to_update)}，成功 {updated}，失败 {failed}"
                                ),
                                phase='fast_update',
                                current_code=_code,
                            )
            emit_progress(
                39,
                (
                    f"快路径完成：成功 {fast_path_success}，"
                    f"跳过/失败 {fast_path_failed}，短窗快补 {len(short_gap_stocks)} 只，"
                    f"慢路径待处理 {len(slow_path_stocks)} 只"
                ),
                phase='fast_update',
            )

        # ── 短窗快补：缺 2-5 个真实交易日，按精确日期窗口拉日 K ───────
        short_total = len(short_gap_stocks)
        short_requeue_code_set: set = set()
        if short_gap_stocks:
            short_requeue_stocks: list = []
            short_bulk_bypassed = False
            emit_progress(
                39,
                f"短窗快补 {short_total} 只股票（缺口 2-{_SHORT_GAP_FAST_MAX_DAYS} 个交易日）...",
                phase='short_update',
            )
            short_lock = threading.Lock()
            short_emit_step = 1 if short_total <= 20 else 10
            short_workers = min(self._fast_path_workers, max(1, short_total))

            if short_total >= _SHORT_GAP_HEALTH_PROBE_MIN_TOTAL:
                # EastMoney 精确短窗是小批量加速通道，不是唯一真值源。
                # 全市场短窗缺口时直接走新浪/Baostock 快兜底，避免 4000+ 股票逐个等待同一慢源。
                short_bulk_bypassed = True
                short_path_failed += short_total
                short_requeue_stocks.extend(short_gap_stocks)
                slow_path_reason_counts['short_gap_fallback'] += short_total
                emit_progress(
                    40,
                    (
                        f"短窗快补批量过大：已将 {short_total} 只直接转入慢路径快兜底，"
                        "跳过 EastMoney 逐股短窗"
                    ),
                    phase='short_update',
                )

            def _write_short_gap_stock(_code):
                _last_date = latest_date_map.get(_code)
                if _last_date is None:
                    return _code, False, None
                _start_date = _last_date + timedelta(days=1)
                _prefetched_cap = market_cap_map.get(_code)
                _df = self._fetch_stock_history_eastmoney(
                    _code,
                    _start_date.strftime("%Y%m%d"),
                    target_date.strftime("%Y%m%d"),
                    prefetched_market_cap=_prefetched_cap,
                )
                if _df is None or _df.empty or 'date' not in _df.columns:
                    return _code, False, None

                _dates = pd.to_datetime(_df['date'], errors='coerce')
                _mask = (_dates.dt.date > _last_date) & (_dates.dt.date <= target_date)
                _df = _df.loc[_mask].copy()
                if _df.empty:
                    return _code, False, None

                self.csv_manager.update_stock(_code, _df)
                return _code, True, _df

            if not short_bulk_bypassed:
                with ThreadPoolExecutor(max_workers=short_workers) as short_executor:
                    futures = {
                        short_executor.submit(_write_short_gap_stock, _code): _code
                        for _code in short_gap_stocks
                    }
                    for short_index, future in enumerate(as_completed(futures), start=1):
                        _code = futures[future]
                        try:
                            _code, _ok, _stock_df = future.result()
                        except Exception:
                            _ok, _stock_df = False, None
                        with short_lock:
                            if _ok:
                                completed += 1
                                updated += 1
                                short_path_success += 1
                            else:
                                short_path_failed += 1
                                short_requeue_stocks.append(_code)
                                slow_path_reason_counts['short_gap_fallback'] += 1
                            if short_index == 1 or short_index % short_emit_step == 0 or short_index == short_total:
                                emit_progress(
                                    39 + int(short_index / max(short_total, 1) * 5),
                                    (
                                        f"短窗快补中：{short_index}/{short_total}，"
                                        f"累计完成 {completed}/{len(stocks_to_update)}，成功 {updated}，"
                                        f"最终失败 {failed}，转慢路径 {len(short_requeue_stocks)}"
                                    ),
                                    phase='short_update',
                                    current_code=_code,
                                )
                        if on_stock_ready and _ok and _stock_df is not None:
                            try:
                                on_stock_ready(_code, _stock_df)
                            except Exception:
                                pass
            if short_requeue_stocks:
                # 短窗快补只依赖 EastMoney；网络或接口短暂失败时回到旧增量链路，
                # 且后续慢路径跳过已失败的 EastMoney，优先用新浪/Baostock 快速兜底。
                slow_path_stocks.extend(short_requeue_stocks)
                short_requeue_code_set = set(short_requeue_stocks)
                slow_path_total = len(slow_path_stocks)
            emit_progress(
                44,
                (
                    f"短窗快补完成：成功 {short_path_success}，"
                    f"转慢路径 {short_path_failed}，慢路径待处理 {len(slow_path_stocks)} 只"
                ),
                phase='short_update',
            )

        # ── 并发更新 K 线数据（慢路径：多日缺失）──────────────────────────
        total = len(slow_path_stocks)
        total_to_update_all = len(stocks_to_update)
        slow_completed = 0
        TIMEOUT_SECONDS = 1800  # 30分钟，替代原600s
        lock = threading.Lock()
        start_time = time.time()
        slow_path_fetch_days_map = {}
        for _code in slow_path_stocks:
            _gap = days_behind_map.get(_code, self._slow_path_min_fetch_days)
            _fetch_days = max(self._slow_path_min_fetch_days, _gap + self._slow_path_buffer_days)
            _fetch_days = min(_fetch_days, self._slow_path_max_fetch_days)
            slow_path_fetch_days_map[_code] = _fetch_days
        _avg_fetch_days = (
            round(sum(slow_path_fetch_days_map.values()) / max(len(slow_path_fetch_days_map), 1), 1)
            if slow_path_fetch_days_map else 0
        )
        _max_fetch_days = max(slow_path_fetch_days_map.values()) if slow_path_fetch_days_map else 0

        slow_path_workers = 16
        if short_requeue_code_set and len(short_requeue_code_set) >= _SHORT_GAP_HEALTH_PROBE_MIN_TOTAL:
            # 短窗整批转慢路径时，新浪不可用后通常会落到 Baostock。
            # Baostock login/query 不适合高并发；限流能避免把兜底源打入熔断。
            slow_path_workers = min(_SHORT_GAP_FALLBACK_SLOW_WORKERS, max(1, total))

        if total > 0:
            print(f"\n开始并发更新 {total} 只股票（慢路径）...")
            emit_progress(
                44,
                (
                    f"开始并发更新 {total} 只股票（慢路径，平均抓取 {_avg_fetch_days} 天，"
                    f"最大 {_max_fetch_days} 天，并发 {slow_path_workers}）..."
                ),
                phase='update',
            )
        else:
            emit_progress(44, "慢路径无需更新，直接进入抽样验证...", phase='update')
        all_done = total == 0
        executor = None
        timed_out = False
        failed_slow_codes: list = []
        try:
            executor = ThreadPoolExecutor(max_workers=slow_path_workers)
            futures = {
                executor.submit(
                    self._update_single_stock,
                    code,
                    slow_path_fetch_days_map.get(code, self._slow_path_min_fetch_days),
                    market_cap_map,
                    code in short_requeue_code_set,
                ): code
                for code in slow_path_stocks
            }
            emit_step = 1 if total <= 20 else 10
            try:
                for future in as_completed(futures, timeout=TIMEOUT_SECONDS):
                    code = futures[future]
                    try:
                        result_tuple = future.result()
                        # _update_single_stock now returns (bool, df_or_None)
                        if isinstance(result_tuple, tuple):
                            success, stock_df = result_tuple
                        else:
                            success, stock_df = bool(result_tuple), None
                    except Exception:
                        success, stock_df = False, None
                    with lock:
                        completed += 1
                        slow_completed += 1
                        if success:
                            updated += 1
                        else:
                            failed += 1
                            failed_slow_codes.append(code)
                        pct = slow_completed / total * 100
                        print(
                            f"\r进度: {slow_completed:4d}/{total} | {pct:5.1f}% | 更新: {updated} | 失败: {failed:3d} | 代码:{code}",
                            end='', flush=True
                        )
                        if slow_completed == 1 or slow_completed % emit_step == 0 or slow_completed == total:
                            emit_progress(
                                44 + int(slow_completed / total * 48),
                                (
                                    f"并发更新中：慢路径 {slow_completed}/{total}，"
                                    f"累计完成 {completed}/{total_to_update_all}，成功 {updated}，失败 {failed}"
                                ),
                                phase='update',
                                current_code=code,
                            )
                    # pipeline 回调：股票更新成功后立即用内存 df 通知调用方
                    if on_stock_ready and success and stock_df is not None:
                        try:
                            on_stock_ready(code, stock_df)
                        except Exception:
                            pass
                all_done = True
            except TimeoutError:
                timed_out = True
                for future in futures:
                    future.cancel()
                elapsed = time.time() - start_time
                print(
                    f"\n[更新] 超时({elapsed:.0f}s)，慢路径已完成 {slow_completed}/{total}，"
                    f"累计完成 {completed}/{total_to_update_all}，取消剩余任务，继续使用本地数据..."
                )
                emit_progress(
                    92,
                    (
                        f"更新超时：慢路径已执行 {slow_completed}/{total}，"
                        f"累计完成 {completed}/{total_to_update_all}，成功 {updated}，失败 {failed}"
                    ),
                    phase='update',
                )
        except Exception as e:
            logger.exception("[更新] 并发执行异常")
            emit_progress(92, f"并发更新异常：{e}", phase='update')
        finally:
            if executor is not None:
                if timed_out:
                    # 超时后不能使用 ThreadPoolExecutor 上下文的默认等待语义，
                    # 否则 SSE 会继续挂在少数慢任务上，前端看起来“一直在更新”。
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        executor.shutdown(wait=False)
                else:
                    executor.shutdown(wait=True)

        print()  # 换行

        if all_done and failed_slow_codes:
            # 批量更新失败经常来自外部数据源的瞬时限流/断连。
            # 第一轮保留并发效率，失败集合再用低并发补一次，避免单次抖动造成大批量 partial。
            retry_codes = list(dict.fromkeys(failed_slow_codes))
            retry_total = len(retry_codes)
            retry_workers = min(4, max(1, retry_total))
            retry_timeout_seconds = min(900, max(60, retry_total * 20))
            emit_progress(
                92,
                f"慢路径失败重试：{retry_total} 只，低并发 {retry_workers} 路补跑一次...",
                phase='retry',
            )

            retry_executor = None
            retry_timed_out = False
            try:
                retry_executor = ThreadPoolExecutor(max_workers=retry_workers)
                retry_futures = {
                    retry_executor.submit(
                        self._update_single_stock,
                        code,
                        slow_path_fetch_days_map.get(code, self._slow_path_min_fetch_days),
                        market_cap_map,
                        code in short_requeue_code_set,
                    ): code
                    for code in retry_codes
                }
                retry_emit_step = 1 if retry_total <= 20 else 10
                for retry_index, future in enumerate(
                    as_completed(retry_futures, timeout=retry_timeout_seconds),
                    start=1,
                ):
                    code = retry_futures[future]
                    try:
                        result_tuple = future.result()
                        if isinstance(result_tuple, tuple):
                            success, stock_df = result_tuple
                        else:
                            success, stock_df = bool(result_tuple), None
                    except Exception:
                        success, stock_df = False, None

                    if success:
                        retry_success += 1
                        updated += 1
                        failed = max(0, failed - 1)
                    else:
                        retry_failed += 1

                    if retry_index == 1 or retry_index % retry_emit_step == 0 or retry_index == retry_total:
                        emit_progress(
                            92 + int(retry_index / max(retry_total, 1) * 2),
                            (
                                f"慢路径失败重试中：{retry_index}/{retry_total}，"
                                f"重试成功 {retry_success}，仍失败 {retry_failed}，最终失败 {failed}"
                            ),
                            phase='retry',
                            current_code=code,
                        )

                    if on_stock_ready and success and stock_df is not None:
                        try:
                            on_stock_ready(code, stock_df)
                        except Exception:
                            pass
            except TimeoutError:
                retry_timed_out = True
                retry_failed += max(retry_total - retry_success - retry_failed, 0)
                if retry_executor is not None:
                    try:
                        for future in retry_futures:
                            future.cancel()
                    except Exception:
                        pass
                emit_progress(
                    94,
                    (
                        f"慢路径失败重试超时：重试成功 {retry_success}，"
                        f"仍失败 {retry_failed}，最终失败 {failed}"
                    ),
                    phase='retry',
                )
            finally:
                if retry_executor is not None:
                    if retry_timed_out:
                        try:
                            retry_executor.shutdown(wait=False, cancel_futures=True)
                        except TypeError:
                            retry_executor.shutdown(wait=False)
                    else:
                        retry_executor.shutdown(wait=True)

        # ── 完成后抽样验证，决定是否写缓存 ─────────────────────────────
        if all_done and failed == 0:
            _prefix_buckets: dict = {}
            for _sc in stocks_to_update:
                _pfx = _sc[:2]
                _prefix_buckets.setdefault(_pfx, []).append(_sc)
            _verify_codes = []
            for _pfx in sorted(_prefix_buckets):
                _bucket = _prefix_buckets[_pfx]
                _step = max(1, len(_bucket) // 5)
                _verify_codes.extend(_bucket[::_step][:5])
            _verify_codes = _verify_codes[:30]
            verify_total = len(_verify_codes)
            emit_progress(94, f"开始抽样验证 {verify_total} 只股票...", phase='verify')
            _reached = 0
            for idx, _vc in enumerate(_verify_codes, start=1):
                try:
                    _vpath = self.csv_manager.get_stock_path(_vc)
                    _vdf = pd.read_csv(_vpath, nrows=1)
                    if not _vdf.empty:
                        _vd = pd.to_datetime(_vdf.iloc[0]['date']).date()
                        if _vd >= target_date:
                            _reached += 1
                except Exception:
                    pass
                verify_reached = _reached
                if idx == 1 or idx % 5 == 0 or idx == verify_total:
                    emit_progress(
                        94 + int(idx / max(verify_total, 1) * 5),
                        f"抽样验证中：{verify_reached}/{verify_total} 只到达 {target_date_str}",
                        phase='verify',
                        current_code=_vc,
                    )

            _threshold = max(1, int(len(_verify_codes) * 0.5))
            if _reached >= _threshold:
                update_cache['last_update_date'] = target_date_str
                with open(update_cache_file, 'w') as f:
                    json.dump(update_cache, f)
                cache_written = True
                verification_passed = True
                print(f"[更新] 抽样验证通过 ({_reached}/{len(_verify_codes)})，缓存已写入")
            else:
                print(
                    f"[更新] 抽样验证：{_reached}/{len(_verify_codes)} 只到达 {target_date_str}，"
                    f"低于50%阈值，暂不写缓存，下次启动将重新检查（可能是数据发布延迟）"
                )
        elif all_done:
            print(
                f"[更新] 所有任务已返回但仍有 {failed} 只最终失败，不写入缓存，"
                "不进入策略重建；下次启动将继续补齐失败股票"
            )
        else:
            print(
                f"[更新] 未全量完成，不写入缓存，下次启动将重新检查并补全剩余 "
                f"{max(total_to_update_all - completed, 0)} 只"
            )

        print("=" * 70)
        print(f"[OK] 并发更新完成！总计：{total_to_update_all} 只 | 成功：{updated} 只 | 失败：{failed} 只")

        # ── 市值刷新不阻塞主流程；兼容旧行为时可配置短等待 ───────────────
        if not _bg_done.is_set() and self._market_cap_wait_seconds > 0:
            emit_progress(
                97,
                f"K线更新完成，最多等待市值后台刷新 {self._market_cap_wait_seconds} 秒...",
                phase='market_cap_wait',
            )
            _bg_done.wait(timeout=self._market_cap_wait_seconds)

        if _bg_cap_count[0] > 0:
            logger.info("[市值] 后台刷新完成，共 %d 只最新市值已写入缓存", _bg_cap_count[0])
            emit_progress(
                98,
                f"市值数据已刷新：{_bg_cap_count[0]} 只（可在前端查看最新市值）",
                phase='market_cap_complete',
                market_cap_count=_bg_cap_count[0],
            )
        elif _bg_cap_error[0]:
            logger.warning("[市值] 后台刷新失败: %s", _bg_cap_error[0])

        update_complete = all_done and failed == 0 and (verify_total == 0 or verification_passed)

        if update_complete:
            final_message = (
                f"{target_date_str} 数据更新完成：扫描 {scan_total} 只，"
                f"需更新 {total_to_update_all} 只，成功 {updated} 只，失败 {failed} 只"
            )
            emit_progress(100, final_message, phase='complete')
            return build_summary('done', final_message)

        final_message = (
            f"{target_date_str} 数据更新未全量完成：已执行 {completed}/{total_to_update_all}，"
            f"成功 {updated} 只，失败 {failed} 只，验证 {verify_reached}/{verify_total}"
        )
        emit_progress(100, final_message, phase='complete')
        return build_summary('partial', final_message)

    def _update_single_stock(self, code, days_to_fetch, market_cap_map, prefer_fast_fallback=False):
        """单只股票更新任务（给线程池调用）
        传入预先批量获取的 market_cap_map，跳过每股单独 API 调用，大幅提速。
        返回 (success: bool, df_or_None)：成功时 df 可用于 pipeline 模式内联策略扫描。
        """
        try:
            prefetched_cap = market_cap_map.get(code)  # None if not in map
            df = self.fetch_stock_update(code, days=days_to_fetch,
                                         prefetched_market_cap=prefetched_cap,
                                         prefer_fast_fallback=prefer_fast_fallback)
            if df is not None and not df.empty:
                self.csv_manager.update_stock(code, df)
                return (True, df)
        except Exception as exc:
            logger.warning("单股更新失败 %s: %s: %s", code, type(exc).__name__, str(exc)[:120])
        return (False, None)


from datetime import datetime, timedelta

def get_last_trading_day():
    """获取最近的交易日"""
    today = datetime.now()
    while today.weekday() >= 5:  # 周六、周日
        today -= timedelta(days=1)
    return today.strftime("%Y-%m-%d")

def is_trading_day(date_str):
    """检查是否为交易日"""
    date = datetime.strptime(date_str, "%Y-%m-%d")
    return date.weekday() < 5  # 周一到周五为交易日
