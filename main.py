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
    python main.py run       # 完整流程（更新+选股+通知）
    python main.py schedule  # 内置定时调度
================================================
"""
import sys
import os
import argparse
import platform
from pathlib import Path
from datetime import datetime

# ===================== 系统路径初始化 =====================
# 获取当前文件所在目录，作为项目根目录
project_root = Path(__file__).parent
# 将根目录加入Python搜索路径，确保模块可被导入
sys.path.insert(0, str(project_root))

# 版本信息
__version__ = "1.0.0"

from quant_system import QuantSystem

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
  python main.py run                           # 标准完整流程
  python main.py run --b1-match                # 完整版流程（选股+B1匹配+导出双TXT）
  python main.py backtest                      # 执行3天回溯扫描
  python main.py backtest --backtest-days 3 --k-threshold 20 --trend-drop-pct 5
  python main.py schedule                      # 启动内置定时
        """
    )

    parser.add_argument('--version', action='store_true', help='显示版本信息')
    parser.add_argument('command', choices=['init', 'run', 'web', 'schedule', 'backtest'], nargs='?', help='命令')
    parser.add_argument('--max-stocks', type=int, default=None, help='限制股票数量')
    parser.add_argument('--config', default='config/config.yaml', help='配置文件')
    parser.add_argument('--host', default='0.0.0.0', help='web监听地址')
    parser.add_argument('--port', type=int, default=5000, help='web端口')
    parser.add_argument('--category', type=str, choices=['all', 'bowl_center', 'near_duokong', 'near_short_trend'], default='all', help='分类')
    parser.add_argument('--min-similarity', type=float, default=None, help='最小相似度')
    parser.add_argument('--b1-match', action='store_true', help='启用B1匹配')
    parser.add_argument('--lookback-days', type=int, default=None, help='回看天数')
    parser.add_argument('--backtest-days', type=int, default=3, help='回溯天数（连续K小于阈值的天数）')
    parser.add_argument('--k-threshold', type=float, default=20.0, help='K值阈值')
    parser.add_argument('--trend-drop-pct', type=float, default=5.0, help='短期趋势线最大容忍回落百分比')
    parser.add_argument('--workers', type=int, default=None, help='选股并发线程数')

    args = parser.parse_args()

    if args.version:
        print_version()
        sys.exit(0)
    if not args.command:
        parser.print_help()
        sys.exit(1)

    os.chdir(project_root)
    quant = QuantSystem(args.config)

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


if __name__ == '__main__':
    main()

