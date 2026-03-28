#!/usr/bin/env python3
"""
A股量化选股系统 - 主程序

这个文件是整个项目的“流程编排入口”。
它主要负责：
1. 初始化配置、数据管理器、通知器、策略注册器
2. 按命令行参数决定执行什么任务
3. 串联“更新数据 -> 选股 -> 导出通达信 -> 发送通知”这条主流程
"""

import sys
import os
import argparse
import platform
import time
from pathlib import Path
import yaml

# -----------------------------------------------------------------------------
# 把项目根目录加入 Python 搜索路径，保证 import 正常
# -----------------------------------------------------------------------------
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 程序版本号
__version__ = "1.0.0"

# 导入项目内部工具类
from utils.akshare_fetcher import AKShareFetcher       # 数据拉取
from utils.csv_manager import CSVManager               # CSV 读写
from utils.dingtalk_notifier import DingTalkNotifier   # 钉钉通知
from utils.tdx_exporter import TdxExporter             # 通达信导出
from strategy.strategy_registry import get_registry     # 策略注册


class QuantSystem:
    """
    量化系统主类（总调度中心）
    负责组装：数据、策略、通知、导出等所有模块
    """

    def __init__(self, config_file="config/config.yaml"):
        """初始化系统：加载配置 → 初始化各类工具 → 创建输出目录"""
        self.config = self._load_config(config_file)

        # 数据目录
        self.data_dir = self.config.get("data_dir", "data")

        # CSV 管理：负责读写单只股票数据
        self.csv_manager = CSVManager(self.data_dir)

        # 数据拉取工具：从 akshare 获取行情
        self.fetcher = AKShareFetcher(self.data_dir)

        # 钉钉通知器
        self.notifier = self._init_notifier()

        # 策略注册器：自动加载策略
        self.registry = get_registry("config/strategy_params.yaml")

        # 输出目录（自动创建）
        self.output_dir = Path(self.config.get("output_dir", "output"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _load_config(self, config_file):
        """加载 YAML 配置文件，不存在则返回空字典"""
        config_path = Path(config_file)
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _init_notifier(self):
        """初始化钉钉通知器，从配置读取 webhook 和 secret"""
        webhook = self.config.get("dingtalk", {}).get("webhook_url")
        secret = self.config.get("dingtalk", {}).get("secret")
        return DingTalkNotifier(webhook, secret)

    def _load_stock_names(self, stock_data):
        """
        加载股票名称映射表（优先网络 → 本地缓存 → 兜底）
        """
        names_file = Path(self.data_dir) / "stock_names.json"

        # 1. 网络拉取最新映射
        try:
            stock_names = self.fetcher.get_all_stock_codes()
            if stock_names:
                import json
                with open(names_file, "w", encoding="utf-8") as f:
                    json.dump(stock_names, f, ensure_ascii=False)
                return stock_names
        except Exception:
            pass

        # 2. 读取本地缓存
        if names_file.exists():
            import json
            with open(names_file, "r", encoding="utf-8") as f:
                return json.load(f)

        # 3. 兜底映射
        return {code: f"股票{code}" for code in stock_data.keys()}

    def _export_selected_to_tdx(self, stock_list, filename_prefix, latest_filename=None):
        """
        导出选股结果到通达信 TXT
        主程序只做调用，具体格式由 TdxExporter 实现
        """
        if not stock_list:
            print("⚠️ 没有可导出的股票数据，跳过生成通达信文件")
            return None

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        archive_filename = f"{filename_prefix}_{timestamp}.txt"

        export_result = TdxExporter.export_txt(
            stocks=stock_list,
            output_dir=str(self.output_dir / "tdx"),
            filename=archive_filename,
            latest_filename=latest_filename or "tdx_stocks_latest.txt",
        )

        if export_result["count"] > 0:
            print(f"\n📄 通达信文件已生成: {export_result['file_path']}")
            if export_result.get("latest_path"):
                print(f"📄 最新文件已更新: {export_result['latest_path']}")
            print(f"   共导出 {export_result['count']} 只股票")
        else:
            print("⚠️ 导出器未生成任何记录")

        return export_result

    def _export_b1_match_to_tdx(self, matched_results):
        """导出 B1 图形匹配结果到通达信专用文件"""
        if not matched_results:
            print("⚠️ 没有 B1 匹配结果，跳过导出通达信文件")
            return None

        stock_list = [
            {"code": item["stock_code"], "name": item["stock_name"]}
            for item in matched_results
        ]

        return self._export_selected_to_tdx(
            stock_list=stock_list,
            filename_prefix="b1_match_result",
            latest_filename="b1_match_latest.txt",
        )

    def init_data(self, max_stocks=None):
        """首次全量抓取历史数据（6年）"""
        print("=" * 60)
        print("🚀 首次全量数据抓取")
        print("=" * 60)
        self.fetcher.init_full_data(max_stocks=max_stocks)
        print("\n✓ 数据初始化完成")

    def _smart_update(self, max_stocks=None, check_latest=True):
        """
        智能更新：
        15点前不更新 → 检查样本是否已有今日数据 → 决定是否更新
        """
        from datetime import datetime
        import pandas as pd

        today = datetime.now().date()
        current_time = datetime.now().time()
        market_close_time = datetime.strptime("15:00", "%H:%M").time()

        # 未收盘不更新
        if current_time < market_close_time:
            print("\n⏰ 当前时间尚未收盘 (15:00)")
            print("  使用本地已有数据，跳过网络更新")
            return

        if check_latest:
            print("\n🔍 检查数据更新状态...")
            stock_codes = self.csv_manager.list_all_stocks()
            if max_stocks:
                stock_codes = stock_codes[:max_stocks]

            total = len(stock_codes)
            has_today = 0
            no_today = 0
            check_limit = min(100, total)

            for code in stock_codes[:check_limit]:
                df = self.csv_manager.read_stock(code)
                if not df.empty:
                    latest_date = pd.to_datetime(df.iloc[0]["date"]).date()
                    if latest_date == today:
                        has_today += 1
                    else:
                        no_today += 1

            if check_limit > 0 and has_today == check_limit:
                print(f"  ✓ 已检查 {check_limit} 只股票，全部已有今天数据")
                print("  数据已是最新，跳过网络更新")
                return
            else:
                print(f"  已检查 {check_limit} 只，{has_today} 只有今天数据，{no_today} 只需要更新")

        print("\n🔄 执行数据更新...")
        self.fetcher.daily_update(max_stocks=max_stocks)
        print("\n✓ 数据更新完成")

    def update_data(self, max_stocks=None):
        """手动执行每日增量更新"""
        print("=" * 60)
        print("🔄 每日增量更新")
        print("=" * 60)
        self.fetcher.daily_update(max_stocks=max_stocks)
        print("\n✓ 数据更新完成")

    def select_stocks(self, category="all", max_stocks=None, return_data=False):
        """
        执行策略选股主逻辑
        return_data=True 会返回股票K线数据，用于画图
        """
        print("=" * 60)
        print("🎯 执行选股策略")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print("=" * 60)

        # 自动加载策略
        print("\n加载策略...")
        self.registry.auto_register_from_directory("strategy")

        if not self.registry.list_strategies():
            print("✗ 没有找到可用策略")
            return ({}, {}, {}) if return_data else ({}, {})

        print(f"已加载 {len(self.registry.list_strategies())} 个策略")

        # 打印当前策略参数
        print("\n当前策略参数:")
        for strategy_name, strategy_obj in self.registry.strategies.items():
            print(f"\n  🎯 {strategy_name}:")
            for param_name, param_value in strategy_obj.params.items():
                note = ""
                if param_name == "N":
                    note = " (成交量倍数)"
                elif param_name == "M":
                    note = " (回溯天数)"
                elif param_name == "CAP":
                    note = f" ({param_value / 1e8:.0f}亿市值门槛)"
                elif param_name == "J_VAL":
                    note = " (J值上限)"
                elif param_name in ["M1", "M2", "M3", "M4"]:
                    note = " (MA周期)"
                print(f"      {param_name}: {param_value}{note}")

        print("\n执行选股（流式处理，降低内存占用）...")
        stock_codes = self.csv_manager.list_all_stocks()

        if not stock_codes:
            print("✗ 没有股票数据，请先执行 init 或 update")
            return ({}, {}, {}) if return_data else ({}, {})

        print(f"共 {len(stock_codes)} 只股票")

        # 加载股票名称映射
        stock_names = self._load_stock_names({})

        import gc
        results = {}
        indicators_dict = {}
        category_count = {
            "bowl_center": 0,
            "near_duokong": 0,
            "near_short_trend": 0,
        }

        process_codes = stock_codes[:max_stocks] if max_stocks else stock_codes

        # 遍历策略 → 遍历股票 → 计算指标 → 选股
        for strategy_name, strategy in self.registry.strategies.items():
            print(f"\n执行策略: {strategy_name}")
            signals = []
            valid_count = 0
            invalid_count = 0

            for i, code in enumerate(process_codes, 1):
                df = self.csv_manager.read_stock(code)
                name = stock_names.get(code, "未知")

                # 过滤异常股票
                invalid_keywords = ["退", "未知", "退市", "已退"]
                if any(keyword in name for keyword in invalid_keywords):
                    invalid_count += 1
                    continue
                if name.startswith("ST") or name.startswith("*ST"):
                    invalid_count += 1
                    continue
                if df.empty or len(df) < 60:
                    continue

                valid_count += 1

                # 计算指标
                df_with_indicators = strategy.calculate_indicators(df)

                # 执行选股
                signal_list = strategy.select_stocks(df_with_indicators, name)

                if signal_list:
                    for signal in signal_list:
                        cat = signal.get("category", "unknown")
                        category_count[cat] = category_count.get(cat, 0) + 1

                        if category == "all" or cat == category:
                            signals.append({
                                "code": code,
                                "name": name,
                                "signals": [signal],
                            })
                            if return_data:
                                indicators_dict[code] = df_with_indicators

                del df, df_with_indicators

                # 定期GC，防止内存爆
                if i % 100 == 0 or i == len(process_codes):
                    gc.collect()
                    print(f"  进度: [{i}/{len(process_codes)}] 有效 {valid_count} 只，选出 {len(signals)} 只...")

            results[strategy_name] = signals
            print(f"  ✓ 选股完成: 共 {len(signals)} 只 (过滤 {invalid_count} 只)")

        # ------------------------------ 结果汇总 ------------------------------
        print("\n" + "=" * 60)
        print("📊 选股结果汇总")
        print("=" * 60)

        all_selected_stocks = []
        category_stocks = {
            "bowl_center": [],
            "near_duokong": [],
            "near_short_trend": [],
        }

        for strategy_name, signals in results.items():
            print(f"\n{strategy_name}: {len(signals)} 只")
            for signal in signals:
                code = signal["code"]
                name = signal.get("name", stock_names.get(code, "未知"))
                all_selected_stocks.append({"code": code, "name": name})

                for single_signal in signal["signals"]:
                    cat_emoji = {
                        "bowl_center": "🥣",
                        "near_duokong": "📊",
                        "near_short_trend": "📈",
                    }.get(single_signal.get("category"), "❓")

                    print(
                        f"  {cat_emoji} {code} {name}: "
                        f"价格={single_signal['close']}, "
                        f"J={single_signal['J']}, "
                        f"理由={single_signal['reasons']}"
                    )

                    cat = single_signal.get("category")
                    if cat in category_stocks:
                        category_stocks[cat].append({"code": code, "name": name})

        # 分类统计
        print("\n" + "-" * 60)
        print("分类统计:")
        print(f"  🥣 回落碗中: {category_count.get('bowl_center', 0)} 只")
        print(f"  📊 靠近多空线: {category_count.get('near_duokong', 0)} 只")
        print(f"  📈 靠近短期趋势线: {category_count.get('near_short_trend', 0)} 只")
        print("-" * 60)

        # ------------------------------ 导出通达信 ------------------------------
        print("\n" + "=" * 60)
        print("📤 生成通达信股票文件")
        print("=" * 60)

        # 全部结果
        self._export_selected_to_tdx(
            stock_list=all_selected_stocks,
            filename_prefix="select_all",
            latest_filename="select_all_latest.txt",
        )

        # 按分类导出
        for cat, stocks in category_stocks.items():
            if stocks:
                self._export_selected_to_tdx(
                    stock_list=stocks,
                    filename_prefix=f"select_{cat}",
                    latest_filename=f"select_{cat}_latest.txt",
                )

        if return_data:
            return results, stock_names, indicators_dict

        return results, stock_names

    def run_full(self, category="all", max_stocks=None):
        """
        完整流程：
        智能更新 → 选股 → 钉钉通知（带图）
        """
        print("=" * 60)
        print("🚀 执行完整流程")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print("=" * 60)

        self._smart_update(max_stocks=max_stocks)

        # 选股并返回K线数据
        results, stock_names, stock_data_dict = self.select_stocks(
            category=category,
            max_stocks=max_stocks,
            return_data=True,
        )

        # 发送钉钉通知
        if results:
            self.notifier.send_stock_selection_with_charts(
                results,
                stock_names,
                category_filter=category,
                stock_data_dict=stock_data_dict,
                params=self.registry.strategies.get("BowlReboundStrategy", {}).params
                if self.registry.strategies else {},
                send_text_first=True,
            )

        return results

    def select_with_b1_match(self, category="all", max_stocks=None, min_similarity=None, lookback_days=None):
        """
        选股 + B1完美图形匹配 + 排序
        输出最像历史成功形态的股票
        """
        from strategy.pattern_config import MIN_SIMILARITY_SCORE, DEFAULT_LOOKBACK_DAYS, TOP_N_RESULTS

        if min_similarity is None:
            min_similarity = MIN_SIMILARITY_SCORE
        if lookback_days is None:
            lookback_days = DEFAULT_LOOKBACK_DAYS

        print("=" * 60)
        print("🎯 执行选股 + B1完美图形匹配")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print(f"   相似度阈值: {min_similarity}%")
        print(f"   回看天数: {lookback_days}天")
        print("=" * 60)

        # 1. 先选股
        print("\n[1/3] 执行策略选股...")
        results, stock_names, stock_data_dict = self.select_stocks(
            category=category,
            max_stocks=max_stocks,
            return_data=True,
        )

        total_selected = sum(len(signals) for signals in results.values())
        if total_selected == 0:
            print("\n✗ 策略未选出任何股票，跳过匹配")
            return {"results": results, "stock_names": stock_names, "matched": []}

        print(f"\n✓ 策略选出 {total_selected} 只股票")

        # 2. 加载B1案例库
        print("\n[2/3] 初始化B1完美图形库...")
        try:
            from strategy.pattern_library import B1PatternLibrary
            library = B1PatternLibrary(self.csv_manager)

            if not library.cases:
                print("⚠️ 警告: 案例库为空，可能数据不足")
                return {"results": results, "stock_names": stock_names, "matched": []}

            print(f"✓ 案例库加载完成: {len(library.cases)} 个案例")
        except Exception as e:
            print(f"✗ 初始化案例库失败: {e}")
            import traceback
            traceback.print_exc()
            return {"results": results, "stock_names": stock_names, "matched": []}

        # 3. 执行匹配
        print("\n[3/3] 执行B1完美图形匹配...")
        matched_results = []

        for strategy_name, signals in results.items():
            for signal in signals:
                code = signal["code"]
                name = signal.get("name", stock_names.get(code, "未知"))

                if code not in stock_data_dict:
                    continue

                df = stock_data_dict[code]
                if df.empty:
                    continue

                try:
                    match_result = library.find_best_match(code, df, lookback_days=lookback_days)

                    if match_result.get("best_match"):
                        best = match_result["best_match"]
                        score = best.get("similarity_score", 0)

                        # 只保留超过阈值的结果
                        if score >= min_similarity:
                            first_signal = signal["signals"][0] if signal.get("signals") else {}

                            matched_results.append({
                                "stock_code": code,
                                "stock_name": name,
                                "strategy": strategy_name,
                                "category": first_signal.get("category", "unknown"),
                                "close": first_signal.get("close", "-"),
                                "J": first_signal.get("J", "-"),
                                "similarity_score": score,
                                "matched_case": best.get("case_name", ""),
                                "matched_date": best.get("case_date", ""),
                                "matched_code": best.get("case_code", ""),
                                "breakdown": best.get("breakdown", {}),
                                "tags": best.get("tags", []),
                                "all_matches": best.get("all_matches", []),
                            })
                except Exception as e:
                    print(f"  ⚠️ 匹配 {code} 失败: {e}")
                    continue

        # 按相似度从高到低排序
        matched_results.sort(key=lambda item: item["similarity_score"], reverse=True)

        print(f"\n✓ 匹配完成: {len(matched_results)} 只股票超过阈值")

        # 导出通达信
        if matched_results:
            print("\n" + "=" * 60)
            print("📤 生成B1匹配结果通达信文件")
            print("=" * 60)
            self._export_b1_match_to_tdx(matched_results)

        # 打印TOP榜单
        if matched_results:
            print("\n" + "=" * 60)
            print(f"📊 Top {TOP_N_RESULTS} B1完美图形匹配结果")
            print("=" * 60)
            for i, result in enumerate(matched_results[:TOP_N_RESULTS], 1):
                emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                print(f"{emoji} {result['stock_code']} {result['stock_name']}")
                print(f"   相似度: {result['similarity_score']}% | 匹配: {result['matched_case']}")
                bd = result.get("breakdown", {})
                print(
                    f"   趋势:{bd.get('trend_structure', 0)}% "
                    f"KDJ:{bd.get('kdj_state', 0)}% "
                    f"量能:{bd.get('volume_pattern', 0)}% "
                    f"形态:{bd.get('price_shape', 0)}%"
                )

        return {
            "results": results,
            "stock_names": stock_names,
            "matched": matched_results,
            "total_selected": total_selected,
        }

    def run_with_b1_match(self, category="all", max_stocks=None, min_similarity=60.0, lookback_days=25):
        """
        完整流程（带B1匹配）
        更新 → 选股 → B1匹配 → 钉钉通知
        """
        print("=" * 60)
        print("🚀 执行完整流程（含B1完美图形匹配）")
        if max_stocks:
            print(f"   快速测试模式：只处理前 {max_stocks} 只股票")
        print(f"   回看天数: {lookback_days}天")
        print("=" * 60)

        self._smart_update(max_stocks=max_stocks)

        match_result = self.select_with_b1_match(
            category=category,
            max_stocks=max_stocks,
            min_similarity=min_similarity,
            lookback_days=lookback_days,
        )

        if match_result.get("matched"):
            print("\n📤 发送钉钉通知...")
            self.notifier.send_b1_match_results(
                match_result["matched"],
                match_result.get("total_selected", 0),
            )
            print("✓ 通知发送完成")
        else:
            print("\n⚠️ 没有匹配结果，跳过通知")

        return match_result

    def run_schedule(self):
        """定时任务（每天15:05自动执行）"""
        try:
            import schedule
        except ImportError:
            print("✗ 请安装 schedule: pip install schedule")
            return

        schedule_time = self.config.get("schedule", {}).get("time", "15:05")

        print("=" * 60)
        print("⏰ 启动定时调度")
        print(f"   每日 {schedule_time} 执行选股任务")
        print("=" * 60)

        schedule.every().day.at(schedule_time).do(self.run_full)

        print("\n按 Ctrl+C 停止")
        while True:
            schedule.run_pending()
            time.sleep(60)


def print_version():
    """打印版本信息"""
    import akshare
    import pandas

    print(f"A-Share Quant v{__version__}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"akshare: {akshare.__version__}")
    print(f"pandas: {pandas.__version__}")
    print(f"System: {platform.system()}")
    print("B1 Pattern Match: 支持（基于双线+量比+形态三维匹配，10个历史案例）")
    print("TDX Export: 支持（首位 0/1 市场标识 + UTF-8 with BOM 编码）")


def main():
    """
    命令行入口
    解析参数 → 执行对应功能
    """
    parser = argparse.ArgumentParser(
        description="A股量化选股系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py run --max-stocks 100
  python main.py run --b1-match
""",
    )

    # 基础参数
    parser.add_argument("--version", action="store_true", help="显示版本信息")
    parser.add_argument("command", nargs="?", choices=["init", "update", "run", "web"], help="命令")
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--category", choices=["all", "bowl_center", "near_duokong", "near_short_trend"], default="all")

    # B1匹配参数
    try:
        from strategy.pattern_config import MIN_SIMILARITY_SCORE, DEFAULT_LOOKBACK_DAYS
        default_min_similarity = MIN_SIMILARITY_SCORE
        default_lookback_days = DEFAULT_LOOKBACK_DAYS
    except Exception:
        default_min_similarity = 60.0
        default_lookback_days = 25

    parser.add_argument("--min-similarity", type=float, default=None)
    parser.add_argument("--b1-match", action="store_true", help="启用B1匹配")
    parser.add_argument("--lookback-days", type=int, default=None)

    args = parser.parse_args()

    # 版本信息
    if args.version:
        print_version()
        sys.exit(0)

    # 无命令则显示帮助
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 切换到项目根目录
    os.chdir(project_root)

    # 创建系统实例
    quant = QuantSystem(args.config)

    # 执行命令
    if args.command == "init":
        quant.init_data(max_stocks=args.max_stocks)

    elif args.command == "update":
        quant.update_data(max_stocks=args.max_stocks)

    elif args.command == "run":
        # ===================== 已修复：b1-match → b1_match =====================
        if args.b1_match:
            min_sim = args.min_similarity if args.min_similarity is not None else default_min_similarity
            lookback = args.lookback_days if args.lookback_days is not None else default_lookback_days
            quant.run_with_b1_match(
                category=args.category,
                max_stocks=args.max_stocks,
                min_similarity=min_sim,
                lookback_days=lookback,
            )
        else:
            quant.run_full(category=args.category, max_stocks=args.max_stocks)

    elif args.command == "web":
        from web_server import run_web_server
        run_web_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()