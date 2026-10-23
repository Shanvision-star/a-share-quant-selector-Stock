"""每日流程状态的共享只读入口，桌面与 MCP 使用相同记录。"""

from datetime import datetime, time, timedelta, timezone
import json
from pathlib import Path

from utils.trading_calendar import previous_a_share_trading_day

ROOT = Path(__file__).resolve().parents[3]
SHANGHAI = timezone(timedelta(hours=8))


def latest_closed_day(now: datetime | None = None) -> str:
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    day = current.date() if current.time() >= time(15, 0) else current.date() - timedelta(days=1)
    return previous_a_share_trading_day(day).isoformat()


def read_daily_status(root: Path | None = None) -> dict:
    path = (root or ROOT) / 'data/daily-agent/latest.json'
    if not path.exists():
        return {'status': 'not_run', 'targets': {}, 'target_date': None}
    return json.loads(path.read_text(encoding='utf-8'))
