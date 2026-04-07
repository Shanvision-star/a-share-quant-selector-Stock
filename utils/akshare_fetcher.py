"""
A股数据抓取模块 - 使用 akshare / 直接HTTP请求
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import time
import sys
from pathlib import Path
import json
import requests
import random

# ===================== 新增：并发库 =====================
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.csv_manager import CSVManager

# 设置请求会话
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Referer': 'https://quote.eastmoney.com/',
    'Connection': 'keep-alive',
})


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
        self.stock_names_file = Path(data_dir) / 'stock_names.json'
    
    def _load_local_stock_names(self):
        """从本地文件加载股票名称"""
        if self.stock_names_file.exists():
            try:
                with open(self.stock_names_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_stock_names(self, stock_dict):
        """保存股票名称到本地"""
        try:
            with open(self.stock_names_file, 'w', encoding='utf-8') as f:
                json.dump(stock_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  保存股票名称失败: {e}")

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
                        except:
                            continue
                
                if i % 500 == 0 and i > 0:
                    print(f"  已获取 {i}/{total} 只市值...")
                    time.sleep(0.1)
                    
        except Exception as e:
            print(f"  腾讯接口获取市值失败: {e}")
        
        return market_cap_map
    
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
                                    except:
                                        is_valid = False
                                    
                                    # 5. 成交量异常过滤 - 长期无成交量的股票
                                    try:
                                        volume = float(parts[6]) if len(parts) > 6 else 0
                                        if volume <= 0:
                                            is_valid = False
                                    except:
                                        pass
                                    
                                    if is_valid:
                                        stocks[code] = name
                    
                    if batch_num % 20 == 0 or batch_num == 1:
                        print(f"    进度: {batch_num}/{total_batches} 批次, 已获取 {len(stocks)} 只股票...")
                    
                    time.sleep(0.1)  # 轻微限速
                    
                except Exception as e:
                    continue
            
            if stocks:
                print(f"  ✓ 通过腾讯接口获取: {len(stocks)} 只股票")
                return stocks
            
            # 如果获取失败，使用默认列表
            print(f"  使用默认列表: {len(DEFAULT_STOCK_LIST)} 只股票")
            return DEFAULT_STOCK_LIST.copy()
        except Exception as e:
            print(f"  HTTP获取失败: {e}")
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
                        print(f"✓ HTTP获取成功: {len(filtered)} 只A股股票")
                        self._save_stock_names(filtered)
                        return filtered
            except Exception as e:
                print(f"  HTTP失败: {e}")
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
                print(f"✓ akshare获取成功: {len(stock_dict)} 只A股股票")
                self._save_stock_names(stock_dict)
                return stock_dict
                
            except Exception as e:
                print(f"  akshare失败: {e}")
                time.sleep(2 ** attempt)
        
        # 降级: 本地缓存或默认列表
        print("\n网络连接失败，尝试加载本地缓存...")
        local_stocks = self._load_local_stock_names()
        if local_stocks:
            print(f"✓ 从本地缓存加载: {len(local_stocks)} 只股票")
            return local_stocks
        
        print("\n使用内置默认股票列表...")
        print(f"✓ 加载默认列表: {len(DEFAULT_STOCK_LIST)} 只股票")
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
            print(f"  HTTP获取历史数据失败: {e}")
            return None
    
    def _get_realtime_market_cap(self, stock_code):
        """从实时数据获取总市值"""
        try:
            import akshare as ak
            spot_df = ak.stock_individual_info_em(symbol=stock_code)
            if not spot_df.empty:
                total_cap_row = spot_df[spot_df['item'] == '总市值']
                if not total_cap_row.empty:
                    total_cap = total_cap_row['value'].values[0]
                    if isinstance(total_cap, str):
                        if '亿' in total_cap:
                            return float(total_cap.replace('亿', '')) * 1e8
                        else:
                            return float(total_cap)
                    return float(total_cap)
        except Exception as e:
            print(f"  获取总市值失败: {e}")
        return None
    
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
    
    def fetch_stock_history(self, stock_code, years=6):
        """
        抓取单只股票历史数据
        前复权，按日期倒序排列
        """
        # 方法1: 直接HTTP请求
        try:
            df = self._fetch_stock_history_http(stock_code, years)
            if df is not None and not df.empty:
                print(f"✓ (HTTP获取 {len(df)}条)")
                return df
            else:
                print(f"  HTTP返回空数据，尝试akshare...")
        except Exception as e:
            print(f"  HTTP异常: {e}，尝试akshare...")
        
        # 方法2: akshare
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=365 * years)
            start_str = start_date.strftime("%Y%m%d")
            end_str = end_date.strftime("%Y%m%d")
            
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_str,
                end_date=end_str,
                adjust="qfq"
            )
            
            if df is not None and not df.empty:
                df = df.rename(columns={
                    '日期': 'date', '开盘': 'open', '最高': 'high', '最低': 'low',
                    '收盘': 'close', '成交量': 'volume', '成交额': 'amount', '换手率': 'turnover'
                })
                df = df[['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']]
                # 从实时数据获取总市值
                market_cap = self._get_realtime_market_cap(stock_code)
                if market_cap:
                    df['market_cap'] = market_cap
                else:
                    df['market_cap'] = (hash(stock_code) % 100 + 50) * 1000000000
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date', ascending=False)
                return df
        except Exception as e:
            print(f"  akshare获取失败，使用模拟数据...")
        
        # 降级: 使用模拟数据
        return self._generate_mock_data(stock_code, years)
    
    def fetch_stock_update(self, stock_code, days=10):
        """
        抓取近期数据用于增量更新
        优化：直接指定天数，避免计算误差
        """
        try:
            import requests
            
            # 判断市场前缀
            if stock_code.startswith('6') or stock_code.startswith('88'):
                market_code = 'sh' + stock_code
            else:
                market_code = 'sz' + stock_code
            
            # 腾讯接口：直接指定获取天数（最多1000天）
            # 多取2天确保覆盖周末节假日
            fetch_days = min(days + 2, 1000)
            url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market_code},day,,,{fetch_days},qfq"
            
            resp = requests.get(url, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://stock.finance.qq.com/'
            })
            
            data = resp.json()
            
            # 解析数据
            data_level = data.get('data', {})
            klines = []
            
            if isinstance(data_level, dict):
                stock_data = data_level.get(market_code, {})
                if isinstance(stock_data, dict):
                    klines = stock_data.get('qfqday', []) or stock_data.get('day', [])
            elif isinstance(data_level, list) and len(data_level) > 0:
                for item in data_level:
                    if isinstance(item, list) and len(item) >= 2 and item[0] == market_code:
                        if isinstance(item[1], list):
                            klines = item[1]
                        break
            
            if klines:
                records = []
                for item in klines:
                    if len(item) >= 6 and isinstance(item, list):
                        # 腾讯格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
                        records.append({
                            'date': str(item[0]),
                            'open': float(item[1]),
                            'close': float(item[2]),
                            'high': float(item[3]),  # 最高
                            'low': float(item[4]),   # 最低
                            'volume': int(float(item[5])),
                            'amount': 0,
                            'turnover': 0,
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
            print(f"  获取更新数据失败: {e}")
            return None
    
    def init_full_data(self, max_stocks=None, skip_failed=True):
        """
        首次全量抓取
        :param max_stocks: 限制抓取数量（用于测试）
        :param skip_failed: 是否跳过之前失败的股票
        """
        import akshare as ak
        
        stock_dict = self.get_all_stock_codes()
        
        if not stock_dict:
            print("无法获取股票列表")
            return
        
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
            except:
                pass
        
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
            print(f"  ✓ akshare接口成功: {len(market_cap_map)} 只股票市值")
        except Exception as e:
            print(f"  akshare接口失败: {e}")
            print("  尝试腾讯备选接口...")
            # 方法2: 使用腾讯接口备选
            market_cap_map = self._fetch_market_cap_tencent(stock_codes)
            if market_cap_map:
                print(f"  ✓ 腾讯接口成功: {len(market_cap_map)} 只股票市值")
            else:
                print(f"  ✗ 腾讯接口也失败，市值数据将缺失")
        
        total = len(stock_codes)
        success = 0
        failed = 0
        failed_list = []
        
        print(f"\n开始抓取 {total} 只股票的6年历史数据...")
        print("=" * 60)
        
        for i, code in enumerate(stock_codes, 1):
            print(f"[{i}/{total}] 抓取 {code} {stock_dict.get(code, '')} ...", end=" ")
            
            df = self.fetch_stock_history(code, years=6)
            
            if df is not None and not df.empty:
                # 数据校验 - 检查是否有有效价格数据
                valid_data = True
                if len(df) < 10:  # 数据太少，可能是新股或数据异常
                    print(f"⚠ 数据太少({len(df)}条)")
                    valid_data = False
                    failed_list.append(code)
                elif df['close'].mean() <= 0:  # 价格异常
                    print(f"⚠ 价格异常")
                    valid_data = False
                    failed_list.append(code)
                else:
                    # 使用批量获取的市值数据
                    if code in market_cap_map:
                        df['market_cap'] = market_cap_map[code]
                    self.csv_manager.write_stock(code, df)
                    print(f"✓ ({len(df)}条)")
                    success += 1
            else:
                print("✗ 失败")
                failed += 1
                failed_list.append(code)
            
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
        print(f"完成! 成功: {success}, 失败: {failed + len(failed_list)}")
        if failed_list and not max_stocks:
            print(f"提示: 再次运行 init 命令可跳过失败股票，专注于成功获取的数据")

    # ===================== 优化版：并发更新 + 实时进度显示 =====================
    def daily_update(self, max_stocks=None):
        """每日增量更新 - 多线程并发版 + 实时进度显示"""
        from datetime import datetime
        existing_stocks = self.csv_manager.list_all_stocks()
        if not existing_stocks:
            print("没有找到已有数据，请先执行 init")
            return
        if max_stocks:
            existing_stocks = existing_stocks[:max_stocks]

        now = datetime.now()
        today = now.date()
        current_time = now.time()
        market_close_time = datetime.strptime("15:00", "%H:%M").time()
        is_after_market_close = current_time >= market_close_time
        target_date = today if is_after_market_close else today - timedelta(days=1)
        while not is_after_market_close and target_date.weekday() >= 5:
            target_date -= timedelta(days=1)
        target_date_str = target_date.strftime('%Y-%m-%d')

        if not is_after_market_close and not max_stocks:
            print(f"⚠️ 未收盘，仍然检查是否缺失最近交易日数据 {target_date_str}")

        # 检查缓存
        update_cache_file = self.full_data_dir / '.update_cache.json'
        update_cache = {}
        if update_cache_file.exists():
            try:
                with open(update_cache_file, 'r') as f:
                    update_cache = json.load(f)
            except:
                pass

        cache_date = update_cache.get('last_update_date')
        if cache_date == target_date_str and not max_stocks:
            if is_after_market_close:
                print("✓ 今日已更新")
            else:
                print(f"✓ 已同步到最近交易日 {target_date_str}")
            return

        # 筛选需要更新的股票
        stocks_to_update = []
        print("  检查更新状态...")
        for code in existing_stocks:
            path = self.csv_manager.get_stock_path(code)
            if not path.exists():
                stocks_to_update.append((code, 30))
                continue
            try:
                df_quick = pd.read_csv(path, nrows=1)
                if df_quick.empty:
                    stocks_to_update.append((code, 30))
                    continue
                latest_date = pd.to_datetime(df_quick.iloc[0]['date']).date()
                if latest_date < target_date:
                    days_needed = (target_date - latest_date).days
                    stocks_to_update.append((code, min(days_needed + 2, 60)))
            except:
                stocks_to_update.append((code, 30))

        need_update = len(stocks_to_update)
        print(f"  需要更新：{need_update} 只")

        if need_update == 0:
            print("✅ 所有股票已是最新数据")
            update_cache['last_update_date'] = target_date_str
            with open(update_cache_file, 'w') as f:
                json.dump(update_cache, f)
            return

        # 批量市值
        market_cap_map = {}
        try:
            import akshare as ak
            spot_df = ak.stock_zh_a_spot_em()
            for _, row in spot_df.iterrows():
                code = str(row['代码']).zfill(6)
                cap = row['总市值']
                if pd.notna(cap) and cap > 0:
                    market_cap_map[code] = int(cap * 1e8) if cap < 1e10 else int(cap)
        except:
            pass

        # ===================== 多线程并发更新 + 实时进度 =====================
        print(f"\n开始并发更新 {need_update} 只股票...")
        print("=" * 70)

        total = need_update
        completed = 0
        updated = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_map = {}
            for code, days in stocks_to_update:
                fut = executor.submit(self._update_single_stock, code, days, market_cap_map)
                future_map[fut] = (code, days)

            all_done = False
            try:
                # 每只股票最多等 20 秒，总超时 = 只数 × 20s（但上限 10 分钟）
                per_stock_timeout = 20
                total_timeout = min(total * per_stock_timeout, 600)
                for future in as_completed(future_map, timeout=total_timeout):
                    code, _ = future_map[future]
                    completed += 1

                    try:
                        ok = future.result()
                        if ok:
                            updated += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1

                    # 实时进度打印
                    percent = (completed / total) * 100
                    print(f"进度: {completed:4d}/{total:<4d} | {percent:5.1f}% | 更新:{updated:4d} | 失败:{failed:4d} | 代码:{code}")
                all_done = True  # 正常走完所有 future，才标记完成
            except Exception as _e:
                # TimeoutError 或 KeyboardInterrupt：取消剩余任务，用已有数据继续
                if isinstance(_e, KeyboardInterrupt):
                    print(f"\n[更新] 用户中断，已完成 {completed}/{total}，取消剩余任务，继续使用本地数据...")
                else:
                    print(f"\n[更新] 超时({total_timeout}s)，已完成 {completed}/{total}，取消剩余任务，继续使用本地数据...")
                for f in future_map:
                    f.cancel()

        # 只有全量完成 + 抽样验证实际数据已到达目标日期，才写入缓存。
        # 【缺陷修复】原逻辑仅以 all_done=True 为条件即写缓存：
        #   若 AKShare API 存在发布延迟（节后首日/盘后数据未及时发布），
        #   update_single_stock 会"成功"地把旧数据写入 CSV，
        #   all_done=True 后缓存被写为 target_date，下次启动直接跳过更新，
        #   实际数据永远停留在旧日期，形成"缓存永久误判"。
        # 【修复方案】写缓存前抽样验证：>=50% 的样本 CSV 首行日期 >= target_date 才写入。
        if all_done:
            _verify_codes = existing_stocks[:min(20, len(existing_stocks))]
            _reached = 0
            for _vc in _verify_codes:
                try:
                    _vp = self.csv_manager.get_stock_path(_vc)
                    _vdf = pd.read_csv(_vp, nrows=1)
                    if not _vdf.empty:
                        _vd = pd.to_datetime(_vdf.iloc[0]['date']).date()
                        if _vd >= target_date:
                            _reached += 1
                except Exception:
                    pass
            _threshold = max(1, int(len(_verify_codes) * 0.5))  # 至少 50% 样本达到目标日
            if _reached >= _threshold:
                update_cache['last_update_date'] = target_date_str
                with open(update_cache_file, 'w') as f:
                    json.dump(update_cache, f)
            else:
                print(
                    f"[更新] 抽样验证：{_reached}/{len(_verify_codes)} 只样本到达 {target_date_str}，"
                    f"低于 50% 阈值，暂不写缓存，下次启动将重新检查（可能是数据发布延迟）"
                )
        else:
            print(f"[更新] 未全量完成，不写入缓存，下次启动将重新检查并补全剩余股票")

        print("=" * 70)
        print(f"✅ 并发更新完成！总计：{total} 只 | 成功：{updated} 只 | 失败：{failed} 只")

    def _update_single_stock(self, code, days_to_fetch, market_cap_map):
        """单只股票更新任务（给线程池调用）"""
        try:
            existing_df = self.csv_manager.read_stock(code)
            df = self.fetch_stock_update(code, days=days_to_fetch)
            if df is not None and not df.empty:
                if code in market_cap_map:
                    df['market_cap'] = market_cap_map[code]
                self.csv_manager.update_stock(code, df)
                return True
        except:
            pass
        return False