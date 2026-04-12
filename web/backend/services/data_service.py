"""数据状态与更新服务"""
import sys
import random
import asyncio
import concurrent.futures
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

from utils.csv_manager import CSVManager
from utils.akshare_fetcher import AKShareFetcher

csv_manager = CSVManager(str(project_root / "data"))
fetcher = AKShareFetcher(str(project_root / "data"))


def get_data_status() -> dict:
    """
    获取数据状态报告
    - 列出各板块(00/30/60/68)的股票数量
    - 抽样检查各板块最新数据日期
    - 计算数据过期比例
    """
    all_stocks = csv_manager.list_all_stocks()

    boards = {'00': [], '30': [], '60': [], '68': []}
    for code in all_stocks:
        prefix = code[:2]
        if prefix in boards:
            boards[prefix].append(code)

    from web.backend.services.strategy_service import get_latest_trade_date
    expected_date = get_latest_trade_date()

    board_status = {}
    latest_dates = []
    stale_count = 0
    checked = 0

    for board_name, codes in boards.items():
        sample = random.sample(codes, min(10, len(codes))) if codes else []
        board_latest = None
        board_stale = 0

        for code in sample:
            df = csv_manager.read_stock(code)
            if not df.empty:
                stock_date = df.iloc[0]['date'].strftime('%Y-%m-%d') if hasattr(df.iloc[0]['date'], 'strftime') else str(df.iloc[0]['date'])[:10]
                if stock_date < expected_date:
                    board_stale += 1
                    stale_count += 1
                if board_latest is None or stock_date > board_latest:
                    board_latest = stock_date
                checked += 1

        board_status[board_name] = {
            'total': len(codes),
            'latest_date': board_latest or '-',
            'stale_ratio': round(board_stale / max(len(sample), 1) * 100, 1),
        }
        if board_latest:
            latest_dates.append(board_latest)

    return {
        'total_stocks': len(all_stocks),
        'latest_date': max(latest_dates) if latest_dates else '-',
        'stale_count': stale_count,
        'checked_count': checked,
        'is_fresh': stale_count / max(checked, 1) < 0.3,
        'boards': board_status,
    }


async def run_data_update():
    """
    异步执行数据更新，通过 yield 返回进度消息（SSE）
    AKShareFetcher.daily_update() 是同步方法，在线程中运行
    """
    yield {
        "event": "start",
        "data": {"status": "start", "progress": 5, "message": "开始更新数据..."},
    }

    def do_update():
        fetcher.daily_update()

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        yield {
            "event": "progress",
            "data": {"status": "running", "progress": 20, "message": "正在从 AKShare 获取最新数据..."},
        }
        try:
            await loop.run_in_executor(pool, do_update)
        except Exception as exc:
            yield {
                "event": "error",
                "data": {"status": "error", "progress": 100, "message": f"数据更新失败: {exc}"},
            }
            return

    yield {
        "event": "complete",
        "data": {"status": "done", "progress": 100, "message": "数据更新完成"},
    }
