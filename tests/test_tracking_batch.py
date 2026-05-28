"""验证从 manual_selections 批量加入 tracking 跟踪。

P1 边界：
- batch_from_selection 复用 create_item，单条失败不影响其他条；
- 同 code 已存在 active（watch_buy / holding）的跟踪 → 计为 skipped，不重复创建；
- selection_date 无对应记录时返回 0 条且不抛异常。
"""

import sqlite3

import pandas as pd
import pytest

from web.backend.services import manual_selection_service as ms_service
from web.backend.services.tracking_service import TrackingService


def _memory_conn() -> sqlite3.Connection:
    """单一内存连接同时承载 manual_selections + tracking_items + tracking_events。

    TrackingService 通过 _ensure_schema 自建 tracking 两表；manual_selections
    需要测试预建。共享同一连接以模拟生产环境同库写入。
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE manual_selections (
            selection_id INTEGER PRIMARY KEY AUTOINCREMENT,
            selection_date TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            strategy_name TEXT,
            source_trade_date TEXT,
            source_signal_date TEXT,
            source_payload_json TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_manual_selection_date_code ON manual_selections(selection_date, code)"
    )
    return conn


def _fake_loader(code: str) -> pd.DataFrame:
    """跟踪建仓不需要真实日线；提供空 DataFrame 让 evaluate 路径不被触发。"""
    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])


@pytest.fixture
def env(monkeypatch):
    conn = _memory_conn()
    monkeypatch.setattr(ms_service, "get_connection", lambda: conn)
    service = TrackingService(connection_factory=lambda: conn, daily_loader=_fake_loader)
    return conn, service


def _seed_selection(date: str, codes: list[str], strategy: str = "B1CaseAnalyzer"):
    for code in codes:
        ms_service.upsert_selection(
            {
                "selection_date": date,
                "code": code,
                "name": "",
                "strategy_name": strategy,
                "source_trade_date": date,
                "source_signal_date": date,
                "source_payload": {"import_type": "paste"},
            }
        )


def test_batch_from_selection_creates_tracking_items_for_each_code(env):
    conn, tracking = env
    _seed_selection("2026-05-26", ["002100", "000559"])

    result = tracking.batch_from_selection(selection_date="2026-05-26")

    assert result["created"] == 2
    assert result["skipped"] == 0
    assert result["failed"] == []
    items = tracking.list_items()
    assert {item["code"] for item in items} == {"002100", "000559"}
    # 来源标签清晰记录为 manual_selection，便于回溯
    assert all(item["source"] == "manual_selection" for item in items)


def test_batch_from_selection_skips_when_active_tracking_exists(env):
    """同 code 已存在 watch_buy 的活跃跟踪，应跳过且计入 skipped。"""
    conn, tracking = env
    _seed_selection("2026-05-26", ["002100"])
    # 预先手动加入一条同 code 的活跃跟踪
    tracking.create_item(
        {
            "code": "002100",
            "name": "天康生物",
            "strategy_name": "manual",
            "source": "manual",
            "source_date": "2026-05-20",
            "signal_date": "2026-05-20",
        }
    )

    result = tracking.batch_from_selection(selection_date="2026-05-26")

    assert result["created"] == 0
    assert result["skipped"] == 1
    assert result["skipped_codes"] == ["002100"]


def test_batch_from_selection_returns_zero_when_no_selection(env):
    conn, tracking = env

    result = tracking.batch_from_selection(selection_date="2099-01-01")

    assert result == {"created": 0, "skipped": 0, "skipped_codes": [], "failed": []}


def test_batch_from_selection_supports_code_filter(env):
    """可选传入 codes 子集，仅导入勾选项；未在 selection 中的 code 计入 failed。"""
    conn, tracking = env
    _seed_selection("2026-05-26", ["002100", "000559", "600000"])

    result = tracking.batch_from_selection(
        selection_date="2026-05-26",
        codes=["002100", "999999"],
    )

    assert result["created"] == 1
    assert result["failed"] == ["999999"]
    items = tracking.list_items()
    assert {item["code"] for item in items} == {"002100"}
