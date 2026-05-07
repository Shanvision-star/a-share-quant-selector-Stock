"""行情入口。

DataPortal 负责把不同来源的行情标准化给执行器；策略和执行器不关心
行情来自 CSV、内存测试数据、QMT，还是其他实时数据源。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Optional, Protocol

import pandas as pd

from utils.csv_manager import CSVManager
from utils.technical import calculate_zhixing_trend
from web.backend.backtest_engine.models import MinuteBar


class DailyDataPortal(Protocol):
    """日线行情读取协议。"""

    def get_daily_frame(self, code: str) -> pd.DataFrame:
        """返回按日期升序排列的日线 DataFrame。"""


class MinuteDataPortal(Protocol):
    """分钟线行情读取协议。"""

    def get_minute_bars(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[MinuteBar]:
        """返回按时间升序排列的分钟线。"""


class FunctionDailyDataPortal:
    """用已有函数包装成日线 DataPortal，便于渐进迁移旧服务。"""

    def __init__(self, loader: Callable[[str], pd.DataFrame]):
        self.loader = loader

    def get_daily_frame(self, code: str) -> pd.DataFrame:
        return self.loader(code)


class InMemoryDailyDataPortal:
    """测试用日线行情入口。"""

    def __init__(self, frames: Mapping[str, pd.DataFrame]):
        self.frames = dict(frames)

    def get_daily_frame(self, code: str) -> pd.DataFrame:
        frame = self.frames.get(code, pd.DataFrame())
        return frame.copy()


class CsvDailyDataPortal:
    """CSV 日线行情入口，保持和当前 data/<prefix>/<code>.csv 结构兼容。"""

    def __init__(self, data_dir: str | Path):
        self.csv_manager = CSVManager(str(data_dir))

    def get_daily_frame(self, code: str) -> pd.DataFrame:
        frame = self.csv_manager.read_stock(code)
        if frame.empty:
            return frame
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
        trend = calculate_zhixing_trend(frame)
        frame["short_term_trend"] = trend["short_term_trend"]
        frame["bull_bear_line"] = trend["bull_bear_line"]
        return frame


class InMemoryMinuteDataPortal:
    """测试用分钟线行情入口。"""

    def __init__(self, bars: Mapping[str, list[MinuteBar]]):
        self.bars = {code: list(items) for code, items in bars.items()}

    def get_minute_bars(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[MinuteBar]:
        return _filter_minute_bars(self.bars.get(code, []), start_date, end_date)


class CsvMinuteDataPortal:
    """CSV 分钟线入口。

    默认兼容以下文件位置：
    - data/minute/<prefix>/<code>.csv
    - data/minute/<code>.csv
    - data/minute/<prefix>/<code>_<YYYY-MM-DD>.csv
    """

    def __init__(self, minute_dir: str | Path):
        self.minute_dir = Path(minute_dir)

    def get_minute_bars(
        self,
        code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[MinuteBar]:
        paths = self._candidate_paths(code, start_date, end_date)
        bars: list[MinuteBar] = []
        for path in paths:
            if path.exists() and path.stat().st_size > 0:
                bars.extend(self._read_csv(code, path))
        return _filter_minute_bars(bars, start_date, end_date)

    def _candidate_paths(self, code: str, start_date: Optional[str], end_date: Optional[str]) -> list[Path]:
        prefix = code[:2] if len(code) >= 2 else code
        paths = [
            self.minute_dir / prefix / f"{code}.csv",
            self.minute_dir / f"{code}.csv",
        ]
        if start_date and end_date:
            for date in pd.date_range(start_date, end_date, freq="D"):
                paths.append(self.minute_dir / prefix / f"{code}_{date.strftime('%Y-%m-%d')}.csv")
        return paths

    def _read_csv(self, code: str, path: Path) -> list[MinuteBar]:
        try:
            frame = pd.read_csv(path)
        except Exception:
            return []
        bars: list[MinuteBar] = []
        for _, row in frame.iterrows():
            try:
                bars.append(MinuteBar.from_mapping(code, row.to_dict()))
            except Exception:
                continue
        return bars


def _filter_minute_bars(
    bars: list[MinuteBar],
    start_date: Optional[str],
    end_date: Optional[str],
) -> list[MinuteBar]:
    filtered = []
    start_ts = pd.to_datetime(start_date).date() if start_date else None
    end_ts = pd.to_datetime(end_date).date() if end_date else None
    for bar in bars:
        bar_date = bar.ts.date()
        if start_ts and bar_date < start_ts:
            continue
        if end_ts and bar_date > end_ts:
            continue
        filtered.append(bar)
    return sorted(filtered, key=lambda item: item.ts)
