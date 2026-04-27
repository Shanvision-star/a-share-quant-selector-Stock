#!/usr/bin/env python3
"""
A股量化选股系统 - 主程序
================================================
项目架构：
  1. 数据层：utils/akshare_fetcher.py    股票数据抓取
  2. 存储层：utils/csv_manager.py        CSV 文件读写
  3. 策略层：strategy/                   多策略选股引擎
  4. 通知层：utils/dingtalk_notifier.py  钉钉推送
  5. 工具层：utils/tdx_exporter.py       通达信文件导出
  6. 调度层：schedule / crontab          定时任务

执行命令：
    python main.py init      # 首次全量抓取历史数据
    python main.py update    # 每日增量更新
    python main.py select    # 仅执行选股
    python main.py run       # 完整流程（更新+BowlReboundStrategy+B1CaseStrategy+通知）
    python main.py schedule  # 内置定时调度
================================================
"""
import sys
import os
import argparse
import platform
from pathlib import Path
from datetime import datetime
from utils.akshare_fetcher import get_last_trading_day, is_trading_day

# ===================== 系统路径初始化 =====================
# 获取当前文件所在目录，作为项目根目录
project_root = Path(__file__).parent
# 将根目录加入Python搜索路径，确保模块可被导入
sys.path.insert(0, str(project_root))

# 版本信息
__version__ = "1.0.0"

from quant_system import QuantSystem
from utils.backtrace_analyzer import BacktraceAnalyzer

# ===================== 版本信息 =====================
def print_version():
    """打印系统环境版本信息"""
    import akshare
    import pandas
    print(f"A-Share Quant v{__version__}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"akshare: {akshare.__version__}")
    print(f"pandas: {pandas.__version__}")
    print(f"System: {platform.system()}")


# ===================== 命令行入口 =====================
def main():
    """
    命令行主入口
    根据输入命令执行对应流程
    支持：init / run / schedule / web
    其中 run 默认执行 BowlReboundStrategy 与 B1CaseStrategy 两个核心策略
    """
    print("\n" + "=" * 60)
    print("📢  当日量化选股开始执行！")
    print("=" * 60 + "\n")

    # 启动通知
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        quant_notify = QuantSystem("config/config.yaml")
        quant_notify.notifier.send_text(f"📢 量化选股系统已启动\n⏰ 启动时间：{now}\n🎯 开始执行今日选股任务...")
        print("✅ 钉钉启动通知已发送\n")
    except Exception as e:
        print(f"⚠️ 钉钉启动通知发送失败：{str(e)}\n")

    # 命令行解析
    parser = argparse.ArgumentParser(
        description='A股量化选股系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py init                          # 首次抓取6年历史数据
    python main.py run                           # 标准完整流程（默认执行 BowlReboundStrategy + B1CaseStrategy）
    python main.py run --b1-match                # 完整版流程（选股+B1匹配+导出双TXT，自动并发/单核降级）
  python main.py backtest                      # 执行3天回溯扫描
  python main.py backtest --backtest-days 3 --k-threshold 20 --trend-drop-pct 5
  python main.py schedule                      # 启动内置定时
  python main.py research                      # 显示研究论文知识库统计
  python main.py research --paper-file paper.txt --paper-title '策略标题'  # 分析论文
  python main.py research --paper-file paper.txt --research-output strategy/new.py  # 分析并生成策略代码
        """
    )

    parser.add_argument('--version', action='store_true', help='显示版本信息')
    parser.add_argument('command', choices=['init', 'run', 'web', 'schedule', 'backtest', 'backtrace', 'research'], nargs='?', help='命令')
    parser.add_argument('--max-stocks', type=int, default=None, help='限制股票数量')
    parser.add_argument('--config', default='config/config.yaml', help='配置文件')
    parser.add_argument('--host', default='0.0.0.0', help='web监听地址')
    parser.add_argument('--port', type=int, default=5000, help='web端口')
    parser.add_argument('--category', type=str, choices=['all', 'bowl_center', 'near_duokong', 'near_short_trend', 'stage_b1_setup'], default='all', help='分类')
    parser.add_argument('--min-similarity', type=float, default=None, help='B1/B2图形匹配最小相似度（默认B1=60%%, B2=55%%）')
    parser.add_argument('--b1-match', action='store_true', help='启用B1匹配')
    parser.add_argument('--b2-match', action='store_true', help='启用B2突破图形匹配（规则扫描版）')
    parser.add_argument('--b2-today', action='store_true', help='当日收盘B2选股：仅输出当日触发B2信号的股票')
    parser.add_argument('--b2-pattern-match', action='store_true', help='启用B2完美图形匹配（规则扫描+相似度打分，参考B1逻辑）')
    parser.add_argument('--lookback-days', type=int, default=None, help='回看天数')
    parser.add_argument('--backtest-days', type=int, default=3, help='回溯天数（连续K小于阈值的天数）')
    parser.add_argument('--k-threshold', type=float, default=20.0, help='K值阈值')
    parser.add_argument('--trend-drop-pct', type=float, default=5.0, help='短期趋势线最大容忍回落百分比')
    parser.add_argument('--paper-file', type=str, help='论文文本文件路径（research 命令使用）')
    parser.add_argument('--paper-title', type=str, help='论文标题（research 命令使用）')
    parser.add_argument('--research-output', type=str, default='', help='生成策略代码的输出路径（research 命令可选）')
    parser.add_argument('--kb-path', type=str, default='', help='知识库文件路径（research 命令可选）')
    parser.add_argument('--workers', type=int, default=None, help='选股并发线程数（默认自动；单核设备会自动降级为1）')
    parser.add_argument('--stock-code', type=str, help='股票代码')
    parser.add_argument('--date', type=str, help='回溯日期，格式为YYYY-MM-DD')

    args = parser.parse_args()

    if args.version:
        print_version()
        sys.exit(0)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    os.chdir(project_root)
    quant = QuantSystem(args.config)

    # 检查未收盘状态和数据同步逻辑
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    if now.hour < 15:
        print("⚠️ 当前时间尚未收盘，检查最近交易日数据...")
        last_trading_day = get_last_trading_day()
        if last_trading_day != today:
            print(f"⚠️ 最近交易日数据未更新：{last_trading_day}，开始更新...")
            quant.update_data(date=last_trading_day)
        else:
            print("✅ 最近交易日数据已更新，无需操作。")
    else:
        print("✅ 当前已收盘，开始正常流程。")

    # 非交易日提示，但不跳过选股（对最近交易日数据执行策略仍有意义）
    if not is_trading_day(today):
        print(f"ℹ️ 今天 {today} 不是交易日，将基于最近交易日数据执行选股任务。")

    # 命令路由
    if args.command == 'init':
        quant.init_data(max_stocks=args.max_stocks)
    elif args.command == 'run':
        if args.b1_match:
            min_sim = args.min_similarity if args.min_similarity is not None else 60.0
            lookback = args.lookback_days if args.lookback_days is not None else 60
            quant.run_with_b1_match(
                category=args.category,
                max_stocks=args.max_stocks,
                min_similarity=min_sim,
                lookback_days=lookback,
                max_workers=args.workers
            )
        elif args.b2_match:
            quant.run_with_b2_match(
                max_stocks=args.max_stocks,
                max_workers=args.workers
            )
        elif args.b2_today:
            quant.run_with_b2_today(
                max_stocks=args.max_stocks,
                max_workers=args.workers
            )
        elif args.b2_pattern_match:
            min_sim = args.min_similarity if args.min_similarity is not None else 55.0
            quant.run_with_b2_pattern_match(
                max_stocks=args.max_stocks,
                max_workers=args.workers,
                min_similarity=min_sim,
            )
        else:
            quant.run_full(category=args.category, max_stocks=args.max_stocks, max_workers=args.workers)
    elif args.command == 'backtest':
        quant.run_backtest_3day(
            max_stocks=args.max_stocks,
            lookback_days=args.backtest_days,
            k_threshold=args.k_threshold,
            max_drop_pct=args.trend_drop_pct
        )
    elif args.command == 'web':
        from web_server import run_web_server
        run_web_server(host=args.host, port=args.port)
    elif args.command == 'schedule':
        quant.run_schedule()
    elif args.command == 'backtrace':
        if not args.stock_code or not args.date:
            print("⚠️ 请输入股票代码和日期 (--stock-code 和 --date)")
            return

        try:
            data_directory = "data"
            analyzer = BacktraceAnalyzer(data_directory)
            results = analyzer.backtrace(args.stock_code, args.date)
            if results:
                print(f"匹配的策略: {results}")
            else:
                print("未匹配到任何策略。")
        except Exception as e:
            print(f"回溯分析失败: {e}")
        return

    elif args.command == 'research':
        from research.paper_agent import PaperAgent

        kb_path = args.kb_path if args.kb_path else None
        agent = PaperAgent(kb_path=kb_path)

        if args.paper_file:
            # 分析指定论文文件
            try:
                with open(args.paper_file, 'r', encoding='utf-8') as f:
                    paper_text = f.read()
            except Exception as e:
                print(f"⚠️ 读取论文文件失败: {e}")
                return
            title = args.paper_title or ''
            print(f"\n📚 正在分析论文: {args.paper_file}")
            report = agent.analyze_text(paper_text, title=title, generate_code=True, save_to_kb=True)
            print(agent.format_report(report))
            if args.research_output and report.generated_code:
                if agent.save_generated_strategy(report, args.research_output):
                    print(f"\n✅ 策略代码已保存到: {args.research_output}")
        else:
            # 无文件时显示知识库统计
            stats = agent.knowledge_base.get_stats()
            print("\n📊 研究论文知识库统计")
            print("=" * 50)
            print(f"  论文总数: {stats.total_papers}")
            if stats.total_papers > 0:
                print(f"  策略类型分布: {stats.strategy_type_dist}")
                print(f"  最常用指标: {dict(list(stats.factor_frequency.items())[:5])}")
                print(f"  市场分布: {stats.universe_dist}")
                print(f"  最近添加: {stats.latest_added[:10] if stats.latest_added else '—'}")
                gaps = agent.knowledge_base.identify_research_gaps()
                print(f"\n🔍 研究空白:")
                print(f"  缺失策略类型: {gaps.get('missing_strategy_types', [])}")
                print(f"  未覆盖常用指标: {gaps.get('missing_common_factors', [])}")
            else:
                print("\n  知识库为空。使用 --paper-file 参数分析论文：")
                print("  python main.py research --paper-file paper.txt --paper-title '策略标题'")
                print("  python main.py research --paper-file paper.txt --research-output strategy/new_strategy.py")


if __name__ == '__main__':
    main()

