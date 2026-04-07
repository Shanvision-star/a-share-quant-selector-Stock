#!/usr/bin/env python3
"""
A股量化选股系统 - 核心业务模块
"""
import os
import time
from pathlib import Path
from datetime import datetime, time as dt_time, timedelta

import yaml

from utils.akshare_fetcher import AKShareFetcher
from utils.csv_manager import CSVManager
from utils.dingtalk_notifier import DingTalkNotifier
from strategy.strategy_registry import get_registry
from utils.kline_chart import generate_kline_chart
from utils.tdx_exporter import export_strategy_tdx, export_total_tdx, export_b1_match_tdx
from strategy.b2_strategy import B2CaseAnalyzer, B2PatternLibrary


class QuantSystem:
    """
    量化系统核心调度类
    作用：统一调度 数据、策略、通知、文件、调度
    设计模式：统一入口 + 模块化解耦
    """

    def __init__(self, config_file="config/config.yaml"):
        """
        构造函数：系统初始化
        1. 加载配置
        2. 初始化各模块实例
        """
        # 加载配置文件
        self.config = self._load_config(config_file)
        # 数据存储目录
        self.data_dir = self.config.get('data_dir', 'data')
        # CSV文件管理器
        self.csv_manager = CSVManager(self.data_dir)
        # 数据抓取器
        self.fetcher = AKShareFetcher(self.data_dir)
        # 钉钉通知器
        self.notifier = self._init_notifier()
        # 策略注册中心（自动加载strategy目录下所有策略）
        self.registry = get_registry("config/strategy_params.yaml")

    def _load_config(self, config_file):
        """加载YAML配置文件，私有方法"""
        config_path = Path(config_file)
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}

    def _init_notifier(self):
        """初始化钉钉通知机器人"""
        webhook = self.config.get('dingtalk', {}).get('webhook_url')
        secret = self.config.get('dingtalk', {}).get('secret')
        return DingTalkNotifier(webhook, secret)

    def _get_expected_latest_trade_date(self):
        """获取当前应当同步的最新交易日日期（未收盘时取最近一个已收盘的交易日）。"""
        now = datetime.now()
        market_close_time = dt_time(15, 0)
        if now.time() >= market_close_time:
            return now.date()

        target_date = now.date() - timedelta(days=1)
        while target_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
            target_date -= timedelta(days=1)
        return target_date

    def _format_eta(self, seconds):
        """将剩余秒数格式化为易读的 ETA。"""
        if seconds is None or seconds < 0:
            return "--:--"
        total_seconds = int(seconds)
        minutes, sec = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{sec:02d}"
        return f"{minutes:02d}:{sec:02d}"

    def _build_progress_bar(self, processed, total, width=24):
        """生成文本进度条。"""
        if total <= 0:
            return "[" + "-" * width + "]"
        ratio = min(max(processed / total, 0.0), 1.0)
        filled = min(width, int(ratio * width))
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    def _print_progress(
        self,
        prefix,
        processed,
        total,
        started_at,
        extra_text="",
        stage_name="",
        total_started_at=None,
    ):
        """统一进度输出：阶段名、进度条、速度、阶段耗时、总耗时、ETA。"""
        if total <= 0:
            return
        now_ts = time.time()
        elapsed = max(now_ts - started_at, 1e-6)
        total_elapsed = max(now_ts - (total_started_at or started_at), 1e-6)
        rate = processed / elapsed
        remaining = max(total - processed, 0)
        eta = remaining / rate if rate > 0 else None
        pct = processed / total * 100
        progress_bar = self._build_progress_bar(processed, total)
        label = f"{prefix}[{stage_name}]" if stage_name else prefix
        suffix = f" {extra_text}" if extra_text else ""
        print(
            f"  {label}: {progress_bar} [{processed}/{total}] {pct:5.1f}% | "
            f"{rate:.1f}只/秒 | 阶段耗时 {self._format_eta(elapsed)} | "
            f"总耗时 {self._format_eta(total_elapsed)} | ETA {self._format_eta(eta)}{suffix}"
        )

    def _resolve_worker_count(self, requested_workers, task_count, default_cap=8, label="任务"):
        """
        统一解析并发线程数。

        规则：
        1. 用户显式传入 --workers 时优先采用；
        2. 未传入时按 CPU 核心数自动估算；
        3. 检测到单核设备时自动从并发模式降级为单线程；
        4. 最终线程数不会超过待处理任务数。
        """
        if task_count <= 1:
            return 1

        cpu_count = os.cpu_count() or 1
        if requested_workers is None:
            resolved = min(default_cap, max(1, cpu_count * 2))
        else:
            resolved = max(1, int(requested_workers))

        if cpu_count <= 1 and resolved > 1:
            print(f"  [并发] {label}: 检测到单核设备，自动从并发模式降级为单线程执行")
            resolved = 1

        resolved = min(resolved, task_count)
        if resolved > 1:
            print(f"  [并发] {label}: 使用 {resolved} 个并发线程（CPU核心数: {cpu_count}）")
        else:
            print(f"  [并发] {label}: 使用单线程执行")
        return resolved

    def _load_stock_names(self, stock_data):
        """
        加载股票名称映射表
        优先本地缓存，无缓存则从网络获取
        """
        names_file = Path(self.data_dir) / 'stock_names.json'
        if names_file.exists():
            try:
                import json
                with open(names_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass

        try:
            stock_names = self.fetcher.get_all_stock_codes()
            if stock_names:
                import json
                with open(names_file, 'w', encoding='utf-8') as f:
                    json.dump(stock_names, f, ensure_ascii=False)
                return stock_names
        except:
            pass

        if names_file.exists():
            try:
                import json
                with open(names_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass

        return {code: f"股票{code}" for code in stock_data.keys()}

    # ===================== 数据抓取模块 =====================
    def init_data(self, max_stocks=None):
        """首次全量初始化：抓取6年历史数据"""
        print("=" * 60)
        print("🚀 首次全量数据抓取")
        print("=" * 60)
        self.fetcher.init_full_data(max_stocks=max_stocks)
        print("\n✓ 数据初始化完成")

    def _smart_update(self, max_stocks=None, check_latest=True):
        """
        智能数据更新
        逻辑：15:00前不更新 | 检查数据是否已是今日最新
        """
        from datetime import datetime
        import pandas as pd
        today = datetime.now().date()
        current_time = datetime.now().time()
        market_close_time = datetime.strptime("15:00", "%H:%M").time()

        expected_date = self._get_expected_latest_trade_date()
        if current_time < market_close_time:
            print("\n⏰ 当前时间尚未收盘 (15:00)")
            print(f"  检查本地数据是否已同步到最近交易日 {expected_date}")

        # 抽样检查数据是否已是最新
        if check_latest:
            print("\n🔍 检查数据更新状态...")
            stock_codes = self.csv_manager.list_all_stocks()
            if max_stocks:
                stock_codes = stock_codes[:max_stocks]

            total = len(stock_codes)
            has_today = 0
            no_today = 0
            check_limit = min(100, total)
            sample_codes = stock_codes
            if total > check_limit:
                import random
                sample_codes = random.sample(stock_codes, check_limit)

            for code in sample_codes:
                df = self.csv_manager.read_stock(code)
                if not df.empty:
                    latest_date = pd.to_datetime(df.iloc[0]['date']).date()
                    if latest_date == expected_date:
                        has_today += 1
                    else:
                        no_today += 1

            if check_limit > 0 and has_today == check_limit:
                print(f"  ✓ 已检查 {check_limit} 只股票，全部已有最新交易日数据 {expected_date}")
                print("  数据已是最新，跳过网络更新")
                return
            elif current_time < market_close_time:
                print(f"  ⚠ 检查到本地数据缺少最新交易日 {expected_date}，继续执行增量更新")

        # 执行增量更新
        print("\n🔄 执行数据更新...")
        self.fetcher.daily_update(max_stocks=max_stocks)
        print("\n✓ 数据更新完成")

    def update_data(self, max_stocks=None):
        """手动触发每日更新"""
        print("=" * 60)
        print("🔄 每日增量更新")
        print("=" * 60)
        self.fetcher.daily_update(max_stocks=max_stocks)
        print("\n✓ 数据更新完成")

    # ===================== 策略选股核心模块 =====================
    def select_stocks(self, category='all', max_stocks=None, return_data=False, max_workers=None):
        """
        统一选股入口
        逻辑：
          1. 加载所有策略
          2. 遍历股票 → 计算指标 → 策略选股
          3. 导出通达信文件
          4. 返回选股结果
        """
        print("=" * 60)
        print("🎯 执行选股策略")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print("=" * 60)

        # 自动加载 strategy 目录下所有策略
        print("\n加载策略...")
        self.registry.auto_register_from_directory("strategy")

        if not self.registry.list_strategies():
            print("✗ 没有找到可用策略")
            return {}, {}

        print(f"已加载 {len(self.registry.list_strategies())} 个策略")

        # 打印策略参数
        print("\n当前策略参数:")
        for strategy_name, strategy_obj in self.registry.strategies.items():
            print(f"\n  🎯 {strategy_name}:")
            for param_name, param_value in strategy_obj.params.items():
                note = ""
                if param_name == 'N':
                    note = " (成交量倍数)"
                elif param_name == 'M':
                    note = " (回溯天数)"
                elif param_name == 'CAP':
                    note = f" ({param_value / 1e8:.0f}亿市值门槛)"
                elif param_name == 'J_VAL':
                    note = " (J值上限)"
                elif param_name in ['M1', 'M2', 'M3', 'M4']:
                    note = " (MA周期)"
                print(f"      {param_name}: {param_value}{note}")

        # 获取股票列表
        print("\n执行选股（流式处理，降低内存占用）...")
        stock_codes = self.csv_manager.list_all_stocks()

        if not stock_codes:
            print("✗ 没有股票数据，请先执行 init 或 update")
            return {}, {}

        print(f"共 {len(stock_codes)} 只股票")
        stock_names = self._load_stock_names({})

        results = {}
        indicators_dict = {}
        category_count = {}
        process_codes = stock_codes[:max_stocks] if max_stocks else stock_codes
        total_codes = []
        selection_started_at = time.time()
        strategy_items = list(self.registry.strategies.items())
        results = {strategy_name: [] for strategy_name, _ in strategy_items}
        selected_codes = set()
        max_workers = self._resolve_worker_count(max_workers, len(process_codes), default_cap=8, label="默认选股")

        # ===================== 遍历股票 + 执行策略 =====================
        print("\n执行多策略联合选股（单只股票只读取一次，减少重复IO与重复指标计算）...")
        valid_count = 0
        invalid_count = 0
        progress_started_at = time.time()
        last_progress_at = 0.0

        def _process_stock(code):
            df = self.csv_manager.read_stock(code)
            name = stock_names.get(code, '未知')
            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in name for kw in invalid_keywords):
                return 'invalid', code, None, None
            if name.startswith('ST') or name.startswith('*ST'):
                return 'invalid', code, None, None
            if df.empty or len(df) < 60:
                return 'skip', code, None, None

            strategy_hits = []
            for strategy_name, strategy in strategy_items:
                try:
                    df_with_indicators = strategy.calculate_indicators(df.copy())
                    signal_list = strategy.select_stocks(df_with_indicators, name)
                    if signal_list:
                        strategy_hits.append((strategy_name, signal_list, df_with_indicators))
                except Exception:
                    continue

            if not strategy_hits:
                return 'no_signal', code, name, df
            return 'ok', code, name, strategy_hits, df

        from concurrent.futures import ThreadPoolExecutor, as_completed
        future_to_code = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for code in process_codes:
                future = executor.submit(_process_stock, code)
                future_to_code[future] = code

            processed = 0
            for future in as_completed(future_to_code):
                processed += 1
                try:
                    result = future.result()
                except Exception:
                    invalid_count += 1
                    continue

                if not result:
                    continue

                status = result[0]
                if status == 'ok':
                    _, code, name, strategy_hits, raw_df = result
                    valid_count += 1
                    for strategy_name, signal_list, df_with_indicators in strategy_hits:
                        filtered_signals = []
                        for s in signal_list:
                            cat = s.get('category', 'unknown')
                            category_count[cat] = category_count.get(cat, 0) + 1
                            if category == 'all' or cat == category:
                                filtered_signals.append(s)

                        if filtered_signals:
                            results[strategy_name].append({
                                'code': code,
                                'name': name,
                                'signals': filtered_signals,
                            })
                            selected_codes.add(code)
                            if return_data:
                                indicators_dict[code] = df_with_indicators

                    if return_data and code not in indicators_dict:
                        indicators_dict[code] = raw_df
                elif status == 'no_signal':
                    valid_count += 1
                elif status == 'invalid':
                    invalid_count += 1

                now_ts = time.time()
                if processed == len(process_codes) or processed % 100 == 0 or (now_ts - last_progress_at) >= 5:
                    last_progress_at = now_ts
                    self._print_progress(
                        "进度",
                        processed,
                        len(process_codes),
                        progress_started_at,
                        extra_text=f"| 有效 {valid_count} 只 | 命中 {len(selected_codes)} 只",
                        stage_name="联合策略并发选股",
                        total_started_at=selection_started_at,
                    )

        for strategy_name, signals in results.items():
            print(f"  ✓ {strategy_name}: 共 {len(signals)} 只")
            strategy_codes = [s['code'] for s in signals]
            exported = export_strategy_tdx(strategy_codes, strategy_name)
            total_codes.extend(exported)

        # 导出所有策略汇总 → 通达信文件
        export_total_tdx(total_codes)

        # 打印结果
        print("\n" + "=" * 60)
        print("📊 选股结果汇总")
        print("=" * 60)
        for strategy_name, signals in results.items():
            print(f"\n{strategy_name}: {len(signals)} 只")
            for signal in signals:
                code = signal['code']
                name = signal.get('name', stock_names.get(code, '未知'))
                for s in signal['signals']:
                    cat_emoji = {
                        'bowl_center': '🥣',
                        'near_duokong': '📊',
                        'near_short_trend': '📈',
                        'stage_b1_setup': '🧭',
                    }.get(s.get('category'), '❓')
                    print(f"  {cat_emoji} {code} {name}: 价格={s['close']}, J={s['J']}, 理由={s['reasons']}")

        print("\n" + "-" * 60)
        print("分类统计:")
        print(f"  🥣 回落碗中: {category_count.get('bowl_center', 0)} 只")
        print(f"  📊 靠近多空线: {category_count.get('near_duokong', 0)} 只")
        print(f"  📈 靠近短期趋势线: {category_count.get('near_short_trend', 0)} 只")
        print(f"  🧭 阶段型B1预警: {category_count.get('stage_b1_setup', 0)} 只")
        print("-" * 60)

        if return_data:
            return results, stock_names, indicators_dict
        return results, stock_names

    # ===================== 完整流程（默认执行 Bowl + B1 阶段预警） =====================
    def run_full(self, category='all', max_stocks=None, max_workers=None):
        """
        标准完整流程：
        数据更新 → 默认策略组选股 → 钉钉通知

        默认策略组当前包含：
          1. BowlReboundStrategy
          2. B1CaseStrategy
        """
        print("=" * 60)
        print("🚀 执行完整流程")
        print("=" * 60)
        self._smart_update(max_stocks=max_stocks)
        results, stock_names, stock_data_dict = self.select_stocks(category=category, max_stocks=max_stocks, return_data=True, max_workers=max_workers)
        if results:
            strategy_obj = self.registry.strategies.get('BowlReboundStrategy') if self.registry.strategies else None
            self.notifier.send_stock_selection_with_charts(
                results, stock_names, category_filter=category,
                stock_data_dict=stock_data_dict,
                params=strategy_obj.params if strategy_obj else {},
                send_text_first=True
            )
        return results

    def run_backtest_3day(self, max_stocks=None, lookback_days=3, k_threshold=20, max_drop_pct=5):
        """
        回溯扫描：检查最近 lookback_days 天是否连续 K 值小于 k_threshold，
        且最低价始终不破短期趋势线 max_drop_pct%。
        """
        print("=" * 60)
        print("🔍 执行 3 天回溯扫描")
        print(f"   条件: 最近 {lookback_days} 天 K < {k_threshold} 且 不破短期趋势线 {max_drop_pct}%")
        print("   且 短期趋势线 > 多空线 (多头状态)")
        print("=" * 60)

        stock_codes = self.csv_manager.list_all_stocks()
        if not stock_codes:
            print("✗ 没有股票数据，请先执行 init 或 update")
            return []

        stock_names = self._load_stock_names({})
        process_codes = stock_codes[:max_stocks] if max_stocks else stock_codes
        print(f"\n开始回溯扫描 {len(process_codes)} 只股票，使用并发线程加速处理...")
        results = []
        stock_data_dict = {}
        scan_started_at = time.time()

        from concurrent.futures import ThreadPoolExecutor, as_completed
        from utils.technical import KDJ, calculate_zhixing_trend

        max_workers = self._resolve_worker_count(None, len(process_codes), default_cap=16, label="3天回溯扫描")

        def _process_code(code):
            df = self.csv_manager.read_stock(code)
            name = stock_names.get(code, '未知')

            invalid_keywords = ['退', '未知', '退市', '已退']
            if any(kw in name for kw in invalid_keywords):
                return None
            if name.startswith('ST') or name.startswith('*ST'):
                return None
            if df.empty or len(df) < (lookback_days + 5):
                return None

            indicators = df.copy()
            try:
                trend_df = calculate_zhixing_trend(indicators)
                indicators['short_term_trend'] = trend_df['short_term_trend']
                indicators['bull_bear_line'] = trend_df['bull_bear_line']
                kdj_df = KDJ(indicators, n=9, m1=3, m2=3)
                indicators['K'] = kdj_df['K']
                indicators['D'] = kdj_df['D']
                indicators['J'] = kdj_df['J']
            except Exception:
                return None

            last_period = indicators.head(lookback_days)
            if len(last_period) < lookback_days:
                return None

            if not (last_period['K'] < k_threshold).all():
                return None

            if last_period.iloc[0]['short_term_trend'] <= last_period.iloc[0]['bull_bear_line']:
                return None

            trend_floor = last_period['short_term_trend'] * (1 - max_drop_pct / 100)
            if (last_period['low'] < trend_floor).any():
                return None

            last_date = last_period.iloc[0]['date']
            last_close = float(last_period.iloc[0]['close'])
            k_values = [round(float(x), 2) for x in last_period['K'].tolist()]
            deviations = ((last_period['close'] - last_period['short_term_trend']) / last_period['short_term_trend'] * 100).round(2).tolist()
            min_k = round(float(min(k_values)), 2)
            max_drawdown = round(float(min(deviations)), 2)

            return {
                'code': code,
                'name': name,
                'last_date': str(last_date),
                'last_close': round(last_close, 2),
                'k_values': k_values,
                'min_k': min_k,
                'deviation_pct': deviations,
                'max_drawdown_pct': max_drawdown,
                'key_dates': [str(d) for d in last_period['date'].tolist()],
                'indicators': indicators
            }

        future_map = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for code in process_codes:
                future = executor.submit(_process_code, code)
                future_map[future] = code

            processed = 0
            last_progress_at = 0.0
            for future in as_completed(future_map):
                processed += 1
                try:
                    result = future.result()
                except Exception:
                    result = None

                if result:
                    stock_data_dict[result['code']] = result.pop('indicators')
                    results.append(result)

                now_ts = time.time()
                if processed == len(process_codes) or processed % 50 == 0 or (now_ts - last_progress_at) >= 5:
                    last_progress_at = now_ts
                    self._print_progress(
                        "回溯进度",
                        processed,
                        len(process_codes),
                        scan_started_at,
                        extra_text=f"| 命中 {len(results)} 只",
                        stage_name="3天回溯扫描",
                    )

        if not results:
            self.notifier.send_text(
                f"🔍 3天回溯扫描完成：共扫描 {len(process_codes)} 只股票，符合条件 0 只。"
            )
            print("✗ 未发现符合条件的股票")
            return []

        results.sort(key=lambda x: x['min_k'])

        self.notifier.send_backtest_results_with_charts(
            results,
            stock_names=stock_names,
            stock_data_dict=stock_data_dict,
            params={
                'lookback_days': lookback_days,
                'k_threshold': k_threshold,
                'max_drop_pct': max_drop_pct
            }
        )

        return results

    def _is_b1_fallback_error(self, exc):
        """判断是否属于应自动回退到原模式的B1异常。"""
        if isinstance(exc, MemoryError):
            return True
        msg = str(exc).lower()
        error_markers = [
            'out of memory',
            'unable to allocate',
            'cannot allocate memory',
            'memoryerror',
            "not 'series'",
            'shape mismatch',
            'broadcast',
            'index out of bounds',
        ]
        return any(marker in msg for marker in error_markers)

    @staticmethod
    def _safe_float(value, default=1e9):
        try:
            if value in (None, '-', ''):
                return default
            return float(value)
        except Exception:
            return default

    def _flatten_b1_candidates(self, results, stock_names):
        """将策略结果压平成按股票去重后的候选列表。"""
        candidates = {}
        for strategy_name, signals in results.items():
            for signal in signals:
                code = signal.get('code')
                if not code:
                    continue
                if code in candidates:
                    continue
                s = signal.get('signals', [{}])[0] if signal.get('signals') else {}
                candidates[code] = {
                    'code': code,
                    'name': signal.get('name', stock_names.get(code, '未知')),
                    'strategy': strategy_name,
                    'category': s.get('category', 'unknown'),
                    'close': s.get('close', '-'),
                    'J': s.get('J', '-'),
                }
        return list(candidates.values())

    # ===================== B1 形态匹配核心 =====================
    def select_with_b1_match(self, category='all', max_stocks=None, min_similarity=None, lookback_days=None, max_workers=None):
        """
        B1完美图形匹配流程
        逻辑：
          1. 先执行原始策略选股
          2. 对选出股票进行形态匹配
          3. 按相似度排序输出
        """
        from strategy.pattern_config import (
            MIN_SIMILARITY_SCORE,
            DEFAULT_LOOKBACK_DAYS,
            AUTO_FALLBACK_TO_CLASSIC,
            B1_MATCH_MAX_CANDIDATES,
            B1_MATCH_WORKERS,
            B1_PREFILTER_BY_J,
        )
        if min_similarity is None:
            min_similarity = MIN_SIMILARITY_SCORE
        if lookback_days is None:
            lookback_days = DEFAULT_LOOKBACK_DAYS
        auto_fallback = bool(AUTO_FALLBACK_TO_CLASSIC)

        print("=" * 60)
        print("🎯 执行选股 + B1完美图形匹配")
        print(f"   相似度阈值: {min_similarity}%")
        print(f"   回看天数: {lookback_days}天")
        print(f"   自动回退: {'开启' if auto_fallback else '关闭'}")
        print("=" * 60)
        flow_started_at = time.time()

        # 步骤1：执行基础选股
        print("\n[1/3] 执行策略选股...")
        results, stock_names, stock_data_dict = self.select_stocks(category=category, max_stocks=max_stocks, return_data=True, max_workers=max_workers)
        total_selected = sum(len(signals) for signals in results.values())
        if total_selected == 0:
            print("\n✗ 策略未选出任何股票，跳过匹配")
            return {
                'results': results,
                'stock_names': stock_names,
                'stock_data_dict': stock_data_dict,
                'matched': [],
                'total_selected': total_selected,
                'fallback_to_classic': False,
                'fallback_reason': '',
            }
        print(f"\n✓ 策略选出 {total_selected} 只股票")

        candidates = self._flatten_b1_candidates(results, stock_names)
        if B1_PREFILTER_BY_J:
            candidates.sort(key=lambda x: self._safe_float(x.get('J')))
        max_candidates = max(0, int(B1_MATCH_MAX_CANDIDATES or 0))
        if max_candidates and len(candidates) > max_candidates:
            print(f"   候选裁剪: {len(candidates)} -> {max_candidates}（按J值低位优先）")
            candidates = candidates[:max_candidates]

        # 步骤2：加载形态库
        print("\n[2/3] 初始化B1完美图形库...")
        try:
            from strategy.pattern_library import B1PatternLibrary
            library = B1PatternLibrary(self.csv_manager)
            if not library.cases:
                print("⚠️ 警告: 案例库为空")
                return {
                    'results': results,
                    'stock_names': stock_names,
                    'stock_data_dict': stock_data_dict,
                    'matched': [],
                    'total_selected': total_selected,
                    'fallback_to_classic': auto_fallback,
                    'fallback_reason': '案例库为空',
                }
            print(f"✓ 案例库加载完成: {len(library.cases)} 个案例")
        except Exception as e:
            print(f"✗ 初始化案例库失败: {e}")
            fallback_reason = f"初始化案例库失败: {e}"
            return {
                'results': results,
                'stock_names': stock_names,
                'stock_data_dict': stock_data_dict,
                'matched': [],
                'total_selected': total_selected,
                'fallback_to_classic': auto_fallback,
                'fallback_reason': fallback_reason,
            }

        # 步骤3：执行形态匹配
        print("\n[3/3] 执行B1完美图形匹配...")
        matched_results = []
        fallback_reason = ''

        def _match_one(candidate):
            code = candidate['code']
            if code not in stock_data_dict:
                return None
            df = stock_data_dict[code]
            if df.empty:
                return None

            match_result = library.find_best_match(code, df, lookback_days=lookback_days)
            best = match_result.get('best_match')
            stage_case = match_result.get('best_stage_case')
            # 前瞻扫描结果：阶段1-5已通过，等待大阳买点确认
            pre_signal = match_result.get('pre_signal', {})
            pre_signal_detected = bool(pre_signal.get('detected', False))

            score = best.get('similarity_score', 0) if best else 0
            include_result = (
                (best is not None and score >= min_similarity)
                or (stage_case is not None)
                or pre_signal_detected  # 前瞻信号也纳入结果
            )
            if not include_result:
                return None

            stage_summary = stage_case.get('summary', {}) if stage_case else {}
            return {
                'stock_code': code,
                'stock_name': candidate['name'],
                'strategy': candidate['strategy'],
                'category': candidate['category'],
                'close': candidate['close'],
                'J': candidate['J'],
                'similarity_score': score,
                'matched_case': best.get('case_name', '') if best else '',
                'matched_date': best.get('case_date', '') if best else '',
                'matched_code': best.get('case_code', '') if best else '',
                'breakdown': best.get('breakdown', {}) if best else {},
                'tags': best.get('tags', []) if best else [],
                'all_matches': match_result.get('all_matches', []),
                'stage_case_passed': stage_case is not None,
                'stage_case_name': stage_case.get('case_name', '') if stage_case else '',
                'stage_case_code': stage_case.get('case_code', '') if stage_case else '',
                'stage_case_buy_date': stage_case.get('buy_date', '') if stage_case else '',
                'stage_case_tags': stage_case.get('tags', []) if stage_case else [],
                'stage_case_description': stage_case.get('description', '') if stage_case else '',
                'stage_case_summary': stage_summary,
                'stage_case_analysis': stage_case.get('analysis', {}) if stage_case else {},
                # 前瞻扫描字段：阶段1-5 通过，等待大阳确认买点
                'pre_signal_detected': pre_signal_detected,
                'pre_signal_anchor_date': pre_signal.get('anchor_date'),
                'pre_signal_anchor_j': pre_signal.get('anchor_j'),
                'pre_signal_setup_start': pre_signal.get('setup_window_start'),
                'pre_signal_current_j': pre_signal.get('current_j'),
                'pre_signal_dist_pct': pre_signal.get('current_dist_pct'),
                'pre_signal_support_price': pre_signal.get('support_price'),
                'pre_signal_stage_passed': pre_signal.get('stage_passed', {}),
                'pre_signal_message': pre_signal.get('message', ''),
            }

        from concurrent.futures import ThreadPoolExecutor, as_completed
        requested_b1_workers = int(B1_MATCH_WORKERS or 0) or max_workers
        b1_workers = self._resolve_worker_count(
            requested_b1_workers,
            len(candidates),
            default_cap=8,
            label="B1完美图形匹配",
        )

        processed = 0
        progress_started_at = time.time()
        last_progress_at = 0.0
        with ThreadPoolExecutor(max_workers=b1_workers) as executor:
            future_map = {executor.submit(_match_one, c): c['code'] for c in candidates}
            for future in as_completed(future_map):
                processed += 1
                code = future_map[future]
                try:
                    row = future.result()
                    if row:
                        matched_results.append(row)
                except Exception as e:
                    if auto_fallback and self._is_b1_fallback_error(e):
                        fallback_reason = f"B1匹配异常，自动切换原模式: {e}"
                        break
                    print(f"  ⚠️ 匹配 {code} 失败: {e}")

                now_ts = time.time()
                if processed == len(candidates) or processed % 100 == 0 or (now_ts - last_progress_at) >= 5:
                    last_progress_at = now_ts
                    self._print_progress(
                        "B1进度",
                        processed,
                        len(candidates),
                        progress_started_at,
                        extra_text=f"| 命中 {len(matched_results)} 只",
                        stage_name="3/3 B1完美图形匹配",
                        total_started_at=flow_started_at,
                    )

        if fallback_reason:
            print(f"\n⚠️ {fallback_reason}")
            return {
                'results': results,
                'stock_names': stock_names,
                'stock_data_dict': stock_data_dict,
                'matched': [],
                'total_selected': total_selected,
                'fallback_to_classic': True,
                'fallback_reason': fallback_reason,
            }

        # 按相似度从高到低排序
        matched_results.sort(
            key=lambda x: (
                x.get('stage_case_passed', False),
                x.get('pre_signal_detected', False),
                x['similarity_score'],
            ),
            reverse=True,
        )
        print(f"\n✓ 匹配完成: {len(matched_results)} 只股票超过阈值")

        # 打印TOP结果
        from strategy.pattern_config import TOP_N_RESULTS
        if matched_results:
            print("\n" + "=" * 60)
            print(f"📊 Top {TOP_N_RESULTS} B1完美图形匹配结果")
            print("=" * 60)
            for i, r in enumerate(matched_results[:TOP_N_RESULTS], 1):
                emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                print(f"{emoji} {r['stock_code']} {r['stock_name']}")
                print(f"   相似度: {r['similarity_score']}% | 匹配: {r['matched_case']}")
                bd = r.get('breakdown', {})
                print(f"   趋势:{bd.get('trend_structure', 0)}%  KDJ:{bd.get('kdj_state', 0)}%  量能:{bd.get('volume_pattern', 0)}%  形态:{bd.get('price_shape', 0)}%")
                if r.get('stage_case_passed'):
                    stage_summary = r.get('stage_case_summary', {})
                    print(
                        "   阶段B1: "
                        f"{r.get('stage_case_name', '')} | setup {stage_summary.get('setup_date', '-') }"
                        f" -> buy {stage_summary.get('buy_date', '-') }"
                        f" | 回溯 {stage_summary.get('anchor_lookback_days', '-')}/{stage_summary.get('support_lookback_days', '-')}天"
                    )

        return {
            'results': results,
            'stock_names': stock_names,
            'stock_data_dict': stock_data_dict,
            'matched': matched_results,
            'total_selected': total_selected,
            'fallback_to_classic': False,
            'fallback_reason': '',
        }

    # ===================== 完整流程（带B1 + 导出文件） =====================
    def run_with_b1_match(self, category='all', max_stocks=None, min_similarity=60.0, lookback_days=60, max_workers=None):
        """
        项目最终完整版流程：
        数据更新 → 选股 → B1形态匹配 → 钉钉通知 → 导出通达信TOP30
        """
        print("=" * 60)
        print("🚀 执行完整流程（含B1完美图形匹配）")
        print("=" * 60)

        # 1. 智能更新数据
        self._smart_update(max_stocks=max_stocks)

        # 2. 选股 + B1匹配
        match_result = self.select_with_b1_match(
            category=category,
            max_stocks=max_stocks,
            min_similarity=min_similarity,
            lookback_days=lookback_days,
            max_workers=max_workers
        )

        if match_result.get('fallback_to_classic'):
            fallback_reason = match_result.get('fallback_reason', 'B1匹配出现异常')
            print(f"\n⚠️ 已自动回退到原选股模式: {fallback_reason}")
            self.notifier.send_text(f"⚠️ B1匹配异常，已自动回退原选股模式\n原因: {fallback_reason}")
            strategy_obj = self.registry.strategies.get('BowlReboundStrategy') if self.registry.strategies else None
            params = strategy_obj.params if strategy_obj else {}
            self.notifier.send_stock_selection_with_charts(
                match_result.get('results', {}),
                match_result.get('stock_names', {}),
                category_filter=category,
                stock_data_dict=match_result.get('stock_data_dict', {}),
                params=params,
                send_text_first=True,
            )
            return match_result

        # 3. 钉钉通知 + 导出文件
        if match_result.get('matched'):
            print("\n📤 发送钉钉通知...")
            self.notifier.send_b1_match_results(
                match_result['matched'],
                match_result.get('total_selected', 0)
            )
            print("✓ 通知发送完成")

            # 导出 B1 匹配 TOP30 → 通达信文件
            export_b1_match_tdx(match_result['matched'])
        else:
            print("\n⚠️ 没有匹配结果，跳过通知")

        return match_result

    def run_with_b2_match(self, max_stocks=None, max_workers=None):
        """
        B2突破图形匹配全流程：
        数据更新 → 全市场 B2 扫描 → TXT导出 → 钉钉通知
        """
        print("=" * 60)
        print("执行完整流程（含B2突破图形匹配）")
        print("=" * 60)

        # 1. 智能更新数据
        self._smart_update(max_stocks=max_stocks)

        # 2. 获取股票列表
        stock_list = self.csv_manager.list_all_stocks()
        if max_stocks:
            stock_list = stock_list[:max_stocks]

        # 3. 读取股票名称
        stock_names = {}
        try:
            import json, os
            names_file = os.path.join(self.data_dir, "stock_names.json")
            if os.path.exists(names_file):
                with open(names_file, "r", encoding="utf-8") as f:
                    stock_names = json.load(f)
        except Exception:
            pass

        # 4. B2 扫描
        from strategy.b2_strategy import B2PatternLibrary
        import time as _time
        b2_library = B2PatternLibrary()

        total = len(stock_list)
        start_ts = _time.time()

        def _progress(done, total, code):
            pct  = done * 100 // total
            elapsed = _time.time() - start_ts
            speed = done / elapsed if elapsed > 0 else 0
            eta   = (total - done) / speed if speed > 0 else 0
            bar   = "#" * (pct // 5) + "-" * (20 - pct // 5)
            try:
                print(
                    f"\r[B2] [{bar}] {pct:3d}% {done}/{total} "
                    f"{code} {speed:.1f}只/s ETA {eta:.0f}s   ",
                    end="", flush=True
                )
            except Exception:
                pass

        results = b2_library.scan_all(stock_list, self.csv_manager, progress_callback=_progress)
        print(flush=True)
        print(f"\n[B2] 扫描完成，共命中 {len(results)} 只")

        # 5. 导出 + 钉钉
        b2_library.notify_and_export(
            results=results,
            notifier=self.notifier if results else None,
            stock_names=stock_names,
        )

        return results

    def run_with_b2_today(self, max_stocks=None, max_workers=None):
        """
        当日收盘B2选股：扫描全市场，仅保留 B2突破日==今日 的结果。
        适合在每日收盘后运行，快速筛选当日刚触发B2信号的股票。
        """
        import datetime as _dt
        today_str = _dt.date.today().strftime("%Y-%m-%d")

        print("=" * 60)
        print(f"执行当日收盘B2选股（{today_str}）")
        print("=" * 60)

        # 1. 智能更新数据
        self._smart_update(max_stocks=max_stocks)

        # 2. 获取股票列表
        stock_list = self.csv_manager.list_all_stocks()
        if max_stocks:
            stock_list = stock_list[:max_stocks]

        # 3. 读取股票名称
        stock_names = {}
        try:
            import json, os
            names_file = os.path.join(self.data_dir, "stock_names.json")
            if os.path.exists(names_file):
                with open(names_file, "r", encoding="utf-8") as f:
                    stock_names = json.load(f)
        except Exception:
            pass

        # 4. B2 全市场扫描
        from strategy.b2_strategy import B2PatternLibrary
        import time as _time
        b2_library = B2PatternLibrary()

        total = len(stock_list)
        start_ts = _time.time()

        def _progress(done, total, code):
            pct     = done * 100 // total
            elapsed = _time.time() - start_ts
            speed   = done / elapsed if elapsed > 0 else 0
            eta     = (total - done) / speed if speed > 0 else 0
            bar     = "#" * (pct // 5) + "-" * (20 - pct // 5)
            try:
                print(
                    f"\r[B2今日] [{bar}] {pct:3d}% {done}/{total} "
                    f"{code} {speed:.1f}只/s ETA {eta:.0f}s   ",
                    end="", flush=True
                )
            except Exception:
                pass

        all_results = b2_library.scan_all(stock_list, self.csv_manager, progress_callback=_progress)
        print(flush=True)

        # 5. 过滤：仅保留 B2突破日 == 今日 的结果
        today_results = [r for r in all_results if r.get("b2_date", "")[:10] == today_str]

        # 检测数据中最新可用日期，判断今日数据是否已更新
        latest_data_date = ""
        if all_results:
            latest_data_date = max(
                (r.get("b2_date", "")[:10] for r in all_results), default=""
            )
        # 也可直接从CSV取最新行日期
        if not latest_data_date and stock_list:
            try:
                sample_df = self.csv_manager.read_stock(stock_list[0])
                if sample_df is not None and not sample_df.empty:
                    latest_data_date = str(sample_df.iloc[0]["date"])[:10]
            except Exception:
                pass

        print(f"\n[B2今日] 今日({today_str}) | 数据最新日期: {latest_data_date or '未知'}")
        print(f"[B2今日] 今日触发B2信号: {len(today_results)} 只 / 全市场历史命中 {len(all_results)} 只")

        # 6. 若今日数据尚未更新，给出明确提示并退出
        if latest_data_date and latest_data_date < today_str:
            msg = (
                f"[B2今日] 今日({today_str})数据尚未更新\n"
                f"数据最新日期: {latest_data_date}\n"
                f"请在今日收盘后数据同步完成后再运行 --b2-today"
            )
            print(msg)
            if self.notifier:
                try:
                    self.notifier.send_text(msg)
                except Exception:
                    pass
            return []

        # 7. 今日数据已更新但无信号
        if not today_results:
            msg = f"[B2今日] {today_str} 今日无B2信号命中（全市场扫描完成）"
            print(msg)
            if self.notifier:
                try:
                    self.notifier.send_text(msg)
                except Exception:
                    pass
            return []

        # 8. 有今日信号 → 导出 + 钉钉通知
        print(f"[B2今日] 命中 {len(today_results)} 只，开始导出...")
        b2_library._results = today_results
        b2_library.notify_and_export(
            results=today_results,
            notifier=self.notifier,
            stock_names=stock_names,
        )

        return today_results

    def run_with_b2_pattern_match(
        self,
        max_stocks=None,
        max_workers=None,
        min_similarity=55.0,
    ):
        """
        B2 完美图形匹配全流程：
        数据更新 → 全市场 B2 规则扫描 → 相似度打分排序 → 导出 TXT → 钉钉通知（含 K 线图）

        与 run_with_b2_match（规则扫描版）的区别：
          - 额外对规则命中股进行多维相似度打分（参考 B1 图形匹配逻辑）
          - 结果按相似度从高到低排序（而非按突破日期排序）
          - 钉钉通知包含四维分项得分 + 匹配案例信息
          - 额外生成带相似度信息的详细 TXT

        Args:
            max_stocks    : 限制扫描股票数量（调试用）
            max_workers   : 预留并发参数（当前 B2 为串行模式）
            min_similarity: 相似度阈值，低于此值不显示（默认 55%）
        """
        print("=" * 60)
        print("执行完整流程（含 B2 完美图形相似度匹配）")
        print("=" * 60)

        # 1. 智能更新数据
        self._smart_update(max_stocks=max_stocks)

        # 2. 获取股票列表
        stock_list = self.csv_manager.list_all_stocks()
        if max_stocks:
            stock_list = stock_list[:max_stocks]

        # 3. 读取股票名称
        stock_names = {}
        try:
            import json as _json, os as _os
            names_file = _os.path.join(self.data_dir, "stock_names.json")
            if _os.path.exists(names_file):
                with open(names_file, "r", encoding="utf-8") as f:
                    stock_names = _json.load(f)
        except Exception:
            pass

        # 4. 初始化 B2 图形匹配库（离线特征库，首次运行会构建并缓存）
        from strategy.b2_pattern_library import B2PatternMatchLibrary
        match_lib = B2PatternMatchLibrary(self.csv_manager)

        # 5. 完整扫描：规则扫描 → 相似度评分
        import time as _time

        start_ts = _time.time()
        total = len(stock_list)

        def _progress(done, total, code):
            pct     = done * 100 // total
            elapsed = _time.time() - start_ts
            speed   = done / elapsed if elapsed > 0 else 0
            eta     = (total - done) / speed if speed > 0 else 0
            bar     = "#" * (pct // 5) + "-" * (20 - pct // 5)
            try:
                print(
                    f"\r[B2PM] [{bar}] {pct:3d}% {done}/{total} "
                    f"{code} {speed:.1f}只/s ETA {eta:.0f}s   ",
                    end="", flush=True,
                )
            except Exception:
                pass

        scan_result = match_lib.run_full_scan(
            stock_list=stock_list,
            progress_callback=_progress,
            min_similarity=min_similarity,
        )
        print(flush=True)

        b2_hits    = scan_result.get("b2_hits", [])
        matched    = scan_result.get("matched", [])
        stock_dict = scan_result.get("stock_data_dict", {})

        # 注入名称
        for r in matched:
            r.setdefault("name", stock_names.get(r.get("code", ""), r.get("code", "")))
        for r in b2_hits:
            r.setdefault("name", stock_names.get(r.get("code", ""), r.get("code", "")))

        print(f"\n[B2PM] 规则命中 {len(b2_hits)} 只 → 相似度过滤后 {len(matched)} 只")

        if not matched:
            msg = (
                f"[B2图形匹配] 规则命中 {len(b2_hits)} 只，"
                f"但无股票达到相似度阈值 {min_similarity}%"
            )
            print(msg)
            self.notifier.send_text(msg)
            return scan_result

        # 6. 导出通达信 TXT
        from utils.tdx_exporter import export_b2_match_tdx, export_b2_pattern_match_detail_txt
        export_b2_match_tdx(matched)
        export_b2_pattern_match_detail_txt(matched, stock_names=stock_names)

        # 7. 钉钉通知（含相似度信息 + K 线图）
        print("\n[B2PM] 发送钉钉通知...")
        self.notifier.send_b2_pattern_match_results_with_charts(
            results=matched,
            stock_data_dict=stock_dict,
            stock_names=stock_names,
            total_b2_hits=len(b2_hits),
        )
        print("[B2PM] 钉钉通知发送完成")

        return scan_result

    # ===================== 内置定时任务 =====================
    def run_schedule(self):
        """内置定时调度（每天固定时间执行完整版流程）"""
        try:
            import schedule
        except ImportError:
            print("✗ 请安装 schedule: pip install schedule")
            return

        schedule_time = self.config.get('schedule', {}).get('time', '15:05')
        print("=" * 60)
        print(f"⏰ 启动定时调度")
        print(f"   每日 {schedule_time} 执行：选股 → B1匹配 → 导出TXT → 发钉钉")
        print("=" * 60)


        # 每日定时执行完整流程
        schedule.every().day.at(schedule_time).do(
            self.run_with_b1_match,
            category='all',
            lookback_days=60
        )

        print("\n按 Ctrl+C 停止")
        while True:
            schedule.run_pending()
            time.sleep(60)
