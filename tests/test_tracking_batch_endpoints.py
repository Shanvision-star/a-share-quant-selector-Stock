"""验证 TXT/粘贴 批量导入 与 批量/单条删除 三个新端点。

回归边界：
- parse_codes 必须把 "sh600000"/"600000.SH"/"abc" 这类脏字符串过滤干净；
- batch_create_codes 对已存在 active（watch_buy/holding）的代码计 skipped；
- batch_delete 对不存在的 id 计 not_found，不抛错；
- 创建后立即评估能落 entry_price/latest_return_pct（用桩 loader 验证）。
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from web.backend.services.tracking_service import TrackingService


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _frame_with_close(close: float) -> pd.DataFrame:
    """构造最小可用日线：两根 K，最后一根收盘价 = close，满足 _buy_row 偏移=1。"""
    return pd.DataFrame(
        [
            {"date": "2026-04-01", "open": close, "high": close, "low": close, "close": close, "volume": 1},
            {"date": "2026-04-02", "open": close, "high": close, "low": close, "close": close, "volume": 1},
        ]
    )


@pytest.fixture
def svc_no_data():
    """无行情：evaluate 走 _record_no_data，entry_price 保持 None。"""
    conn = _memory_conn()
    return TrackingService(
        connection_factory=lambda: conn,
        daily_loader=lambda code: pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"]),
    )


@pytest.fixture
def svc_with_data():
    """有行情：evaluate 把 watch_buy 推进到 holding，落 entry_price。"""
    conn = _memory_conn()
    return TrackingService(
        connection_factory=lambda: conn,
        daily_loader=lambda code: _frame_with_close(10.0),
    )


# ---------- parse_codes ----------


def test_parse_codes_filters_noise():
    valid, invalid = TrackingService.parse_codes(
        "600000\n000001, sh600519; 600000\nabc\n600000.SH\n12345"
    )
    # 600000 出现 3 次（含带后缀的），但应去重为 1 个
    assert valid == ["600000", "000001", "600519"]
    # "abc" 与 "12345" 进入 invalid
    assert "abc" in invalid
    assert "12345" in invalid


def test_parse_codes_empty():
    assert TrackingService.parse_codes("") == ([], [])
    assert TrackingService.parse_codes("   \n  ") == ([], [])


# ---------- batch_create_codes ----------


def test_batch_create_codes_dedup_and_format(svc_no_data: TrackingService):
    result = svc_no_data.batch_create_codes(
        codes=["600000", "600000", "abcdef", "000001"],
        signal_date="2026-04-01",
        evaluate_now=False,
    )
    created_codes = [item["code"] for item in result["created"]]
    assert sorted(created_codes) == ["000001", "600000"]
    failed_codes = [f["code"] for f in result["failed"]]
    assert "abcdef" in failed_codes


def test_batch_create_codes_skips_active(svc_no_data: TrackingService):
    svc_no_data.create_item({"code": "600000", "signal_date": "2026-04-01"})
    result = svc_no_data.batch_create_codes(
        codes=["600000", "000001"],
        signal_date="2026-04-02",
        evaluate_now=False,
    )
    assert [item["code"] for item in result["created"]] == ["000001"]
    skipped_codes = [s["code"] for s in result["skipped"]]
    assert skipped_codes == ["600000"]


def test_batch_create_codes_evaluates_and_fills_entry_price(svc_with_data: TrackingService):
    """有行情数据时，evaluate_now=True 应让 entry_price 落地（解决前端看不到买入点）。"""
    result = svc_with_data.batch_create_codes(
        codes=["600000"], signal_date="2026-04-01", evaluate_now=True
    )
    assert len(result["created"]) == 1
    item = result["created"][0]
    # 立即评估后应已切到 holding 并写入 entry_price
    assert item["entry_price"] is not None
    assert item["entry_price"] == pytest.approx(10.0, rel=1e-3)
    assert item["status"] == "holding"


# ---------- delete_item / batch_delete ----------


def test_delete_item_removes_row_and_events(svc_no_data: TrackingService):
    item = svc_no_data.create_item({"code": "600000", "signal_date": "2026-04-01"})
    tid = item["tracking_id"]
    assert svc_no_data.delete_item(tid) is True
    # 二次删除返回 False，符合幂等约定
    assert svc_no_data.delete_item(tid) is False
    assert svc_no_data.get_item(tid) is None


def test_batch_delete_partial_missing(svc_no_data: TrackingService):
    item = svc_no_data.create_item({"code": "600000", "signal_date": "2026-04-01"})
    result = svc_no_data.batch_delete([item["tracking_id"], "not_exist_xxx", item["tracking_id"]])
    # 同一 id 重复不重复处理
    assert result["deleted"] == [item["tracking_id"]]
    assert result["not_found"] == ["not_exist_xxx"]


# ---------- 路由端点烟测（最小覆盖，复用 main:app 真实连接） ----------


def test_router_batch_endpoints_smoke(monkeypatch):
    """端点烟测：确认请求能命中处理器并返回 200/4xx，而不是路由 404。"""
    from fastapi.testclient import TestClient

    from web.backend.main import app

    client = TestClient(app)

    # 空 codes/text → 400 业务错误而非 404
    resp = client.post("/api/tracking/batch-create", json={})
    assert resp.status_code in (400, 422)
    assert resp.headers.get("content-type", "").startswith("application/json")

    # 批量删除空数组应被 pydantic 拦在 422
    resp = client.post("/api/tracking/batch-delete", json={"tracking_ids": []})
    assert resp.status_code == 422

    # 单条删除不存在 id → 业务 404
    resp = client.delete("/api/tracking/trk_definitely_not_exist_zzz")
    assert resp.status_code == 404
    assert resp.headers.get("content-type", "").startswith("application/json")
