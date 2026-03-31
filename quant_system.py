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

        import gc
        results = {}
        indicators_dict = {}
        category_count = {'bowl_center': 0, 'near_duokong': 0, 'near_short_trend': 0}
        process_codes = stock_codes[:max_stocks] if max_stocks else stock_codes
        total_codes = []

        # ===================== 遍历股票 + 执行策略 =====================
        for strategy_name, strategy in self.registry.strategies.items():
            print(f"\n执行策略: {strategy_name}")
            signals = []
            valid_count = 0
            invalid_count = 0

            if max_workers is None:
                max_workers = min(8, max(1, (os.cpu_count() or 4) * 2))
            max_workers = min(max_workers, len(process_codes)) if process_codes else 1

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

                try:
                    df_with_indicators = strategy.calculate_indicators(df)
                    signal_list = strategy.select_stocks(df_with_indicators, name)
                    if not signal_list:
                        return 'no_signal', code, None, None
                    return 'ok', code, name, signal_list, df_with_indicators
                except Exception:
                    return 'error', code, None, None

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
                        _, code, name, signal_list, df_with_indicators = result
                        valid_count += 1
                        for s in signal_list:
                            cat = s.get('category', 'unknown')
                            category_count[cat] += 1
                            if category == 'all' or cat == category:
                                signals.append({
                                    'code': code,
                                    'name': name,
                                    'signals': [s]
                                })
                                if return_data:
                                    indicators_dict[code] = df_with_indicators
                    elif status == 'no_signal':
                        valid_count += 1
                    elif status == 'invalid':
                        invalid_count += 1
                    # skip / error 不计入 valid_count

                    if processed % 100 == 0 or processed == len(process_codes):
                        gc.collect()
                        print(f"  进度: [{processed}/{len(process_codes)}] 有效 {valid_count} 只，选出 {len(signals)} 只...")

            # 保存当前策略结果
            results[strategy_name] = signals
            print(f"  ✓ 选股完成: 共 {len(signals)} 只 (过滤 {invalid_count} 只)")

            # 导出当前策略 → 通达信文件
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
                    cat_emoji = {'bowl_center': '🥣', 'near_duokong': '📊', 'near_short_trend': '📈'}.get(s.get('category'), '❓')
                    print(f"  {cat_emoji} {code} {name}: 价格={s['close']}, J={s['J']}, 理由={s['reasons']}")

        print("\n" + "-" * 60)
        print("分类统计:")
        print(f"  🥣 回落碗中: {category_count.get('bowl_center', 0)} 只")
        print(f"  📊 靠近多空线: {category_count.get('near_duokong', 0)} 只")
        print(f"  📈 靠近短期趋势线: {category_count.get('near_short_trend', 0)} 只")
        print("-" * 60)

        if return_data:
            return results, stock_names, indicators_dict
        return results, stock_names

    # ===================== 完整流程（不带B1） =====================
    def run_full(self, category='all', max_stocks=None, max_workers=None):
        """
        标准完整流程：
        数据更新 → 选股 → 钉钉通知
        """
        print("=" * 60)
        print("🚀 执行完整流程")
        print("=" * 60)
        self._smart_update(max_stocks=max_stocks)
        results, stock_names, stock_data_dict = self.select_stocks(category=category, max_stocks=max_stocks, return_data=True, max_workers=max_workers)
        if results:
            self.notifier.send_stock_selection_with_charts(
                results, stock_names, category_filter=category,
                stock_data_dict=stock_data_dict,
                params=self.registry.strategies.get('BowlReboundStrategy', {}).params if self.registry.strategies else {},
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

        from concurrent.futures import ThreadPoolExecutor, as_completed
        from utils.technical import KDJ, calculate_zhixing_trend

        max_workers = min(16, max(1, (os.cpu_count() or 4) * 2))
        max_workers = min(max_workers, len(process_codes)) if process_codes else 1
        print(f"  并发线程数: {max_workers}")

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
            for future in as_completed(future_map):
                processed += 1
                try:
                    result = future.result()
                except Exception:
                    result = None

                if result:
                    stock_data_dict[result['code']] = result.pop('indicators')
                    results.append(result)

                if processed % 50 == 0 or processed == len(process_codes):
                    print(f"  进度: [{processed}/{len(process_codes)}] 发现 {len(results)} 只符合条件...")

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

    # ===================== B1 形态匹配核心 =====================
    def select_with_b1_match(self, category='all', max_stocks=None, min_similarity=None, lookback_days=None, max_workers=None):
        """
        B1完美图形匹配流程
        逻辑：
          1. 先执行原始策略选股
          2. 对选出股票进行形态匹配
          3. 按相似度排序输出
        """
        from strategy.pattern_config import MIN_SIMILARITY_SCORE, DEFAULT_LOOKBACK_DAYS
        if min_similarity is None:
            min_similarity = MIN_SIMILARITY_SCORE
        if lookback_days is None:
            lookback_days = DEFAULT_LOOKBACK_DAYS

        print("=" * 60)
        print("🎯 执行选股 + B1完美图形匹配")
        print(f"   相似度阈值: {min_similarity}%")
        print(f"   回看天数: {lookback_days}天")
        print("=" * 60)

        # 步骤1：执行基础选股
        print("\n[1/3] 执行策略选股...")
        results, stock_names, stock_data_dict = self.select_stocks(category=category, max_stocks=max_stocks, return_data=True, max_workers=max_workers)
        total_selected = sum(len(signals) for signals in results.values())
        if total_selected == 0:
            print("\n✗ 策略未选出任何股票，跳过匹配")
            return {'results': results, 'stock_names': stock_names, 'matched': []}
        print(f"\n✓ 策略选出 {total_selected} 只股票")

        # 步骤2：加载形态库
        print("\n[2/3] 初始化B1完美图形库...")
        try:
            from strategy.pattern_library import B1PatternLibrary
            library = B1PatternLibrary(self.csv_manager)
            if not library.cases:
                print("⚠️ 警告: 案例库为空")
                return {'results': results, 'stock_names': stock_names, 'matched': []}
            print(f"✓ 案例库加载完成: {len(library.cases)} 个案例")
        except Exception as e:
            print(f"✗ 初始化案例库失败: {e}")
            return {'results': results, 'stock_names': stock_names, 'matched': []}

        # 步骤3：执行形态匹配
        print("\n[3/3] 执行B1完美图形匹配...")
        matched_results = []
        for strategy_name, signals in results.items():
            for signal in signals:
                code = signal['code']
                name = signal.get('name', stock_names.get(code, '未知'))
                if code not in stock_data_dict:
                    continue
                df = stock_data_dict[code]
                if df.empty:
                    continue

                try:
                    match_result = library.find_best_match(code, df, lookback_days=lookback_days)
                    if match_result.get('best_match'):
                        best = match_result['best_match']
                        score = best.get('similarity_score', 0)
                        if score >= min_similarity:
                            s = signal['signals'][0] if signal.get('signals') else {}
                            matched_results.append({
                                'stock_code': code,
                                'stock_name': name,
                                'strategy': strategy_name,
                                'category': s.get('category', 'unknown'),
                                'close': s.get('close', '-'),
                                'J': s.get('J', '-'),
                                'similarity_score': score,
                                'matched_case': best.get('case_name', ''),
                                'matched_date': best.get('case_date', ''),
                                'matched_code': best.get('case_code', ''),
                                'breakdown': best.get('breakdown', {}),
                                'tags': best.get('tags', []),
                                'all_matches': best.get('all_matches', []),
                            })
                except Exception as e:
                    print(f"  ⚠️ 匹配 {code} 失败: {e}")
                    continue

        # 按相似度从高到低排序
        matched_results.sort(key=lambda x: x['similarity_score'], reverse=True)
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

        return {
            'results': results,
            'stock_names': stock_names,
            'matched': matched_results,
            'total_selected': total_selected,
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
