"""验证人工选股池的批量导入入口（txt / paste / from-strategy）。

P1 阶段三入口都收敛到 `import_codes_batch`，避免每个入口重复一套
upsert 逻辑；测试覆盖：解析、去重、保序、重复触发 update、非法代码、
import_type 写入 source_payload。
"""

import sqlite3

import pytest

from web.backend.services import manual_selection_service as service


def _memory_conn() -> sqlite3.Connection:
    """构造内存连接并预建 manual_selections 表，用于隔离测试。

    与生产 schema 字段一致；不引入 init_database 以避免触发全部 11 张
    表的迁移逻辑（保持测试只关心被测对象）。
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


@pytest.fixture
def patched_conn(monkeypatch):
    """把 manual_selection_service 的 get_connection 替换为内存连接。"""
    conn = _memory_conn()
    monkeypatch.setattr(service, "get_connection", lambda: conn)
    return conn


def test_parse_codes_from_text_extracts_six_digit_codes_with_dedup_and_order():
    """解析含杂音的文本：保留 6 位数字代码，去重，保序。

    场景：用户从研报、聊天记录粘贴；可能夹带价格 7.55 / 中文 / 重复。
    """
    text = """
    今日关注：
    002100 天康生物
    7.55 是价格不是代码
    000559, 万向钱潮
    002100  # 重复
    abc 123456 def
    """
    codes = service.parse_codes_from_text(text)

    # 保序：002100 先出现 → 排第一；000559 第二；123456 最后
    assert codes == ["002100", "000559", "123456"]


def test_parse_codes_from_text_returns_empty_for_no_match():
    """无任何 6 位数字的文本应返回空列表，不抛异常。"""
    assert service.parse_codes_from_text("hello world") == []
    assert service.parse_codes_from_text("") == []


def test_import_codes_batch_inserts_with_import_type_tag(patched_conn):
    """txt 入口：写入后 source_payload 应包含 import_type=txt。"""
    result = service.import_codes_batch(
        selection_date="2026-05-26",
        codes=["002100", "000559"],
        import_type="txt",
    )

    assert result["inserted"] == 2
    assert result["updated"] == 0
    assert result["invalid"] == []

    items = service.list_selections(selection_date="2026-05-26")
    assert len(items) == 2
    payload_types = {item["source_payload"].get("import_type") for item in items}
    assert payload_types == {"txt"}


def test_import_codes_batch_strategy_pick_carries_strategy_and_trade_date(patched_conn):
    """from-strategy 入口：strategy_name + source_trade_date 应落库。"""
    result = service.import_codes_batch(
        selection_date="2026-05-26",
        codes=["002100"],
        import_type="strategy_pick",
        strategy_name="B1CaseAnalyzer",
        source_trade_date="2026-05-23",
    )

    assert result["inserted"] == 1
    item = service.get_selection("2026-05-26", "002100")
    assert item["strategy_name"] == "B1CaseAnalyzer"
    assert item["source_trade_date"] == "2026-05-23"
    assert item["source_payload"]["import_type"] == "strategy_pick"


def test_import_codes_batch_dedup_updates_existing(patched_conn):
    """相同 (selection_date, code) 再次导入应触发 update 而非 duplicate insert。"""
    service.import_codes_batch(
        selection_date="2026-05-26",
        codes=["002100"],
        import_type="paste",
    )
    second = service.import_codes_batch(
        selection_date="2026-05-26",
        codes=["002100", "000559"],
        import_type="strategy_pick",
        strategy_name="B1CaseAnalyzer",
    )

    assert second["inserted"] == 1  # 仅 000559
    assert second["updated"] == 1   # 002100 触发覆盖
    items = service.list_selections(selection_date="2026-05-26")
    assert len(items) == 2  # 唯一约束生效，不重复

    # 002100 的来源标签被覆盖为最新 import_type
    updated = service.get_selection("2026-05-26", "002100")
    assert updated["source_payload"]["import_type"] == "strategy_pick"
    assert updated["strategy_name"] == "B1CaseAnalyzer"


def test_import_codes_batch_collects_invalid_codes(patched_conn):
    """非 6 位数字代码应进入 invalid 列表，不阻塞合法代码导入。"""
    result = service.import_codes_batch(
        selection_date="2026-05-26",
        codes=["002100", "12345", "abcdef", "000559"],
        import_type="paste",
    )

    assert result["inserted"] == 2
    assert sorted(result["invalid"]) == ["12345", "abcdef"]
    items = service.list_selections(selection_date="2026-05-26")
    assert {item["code"] for item in items} == {"002100", "000559"}
