"""P5 跟踪规则评估编排服务测试：批量评估活跃跟踪 + 自动级联开关。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import pytest


def _make_frame(days: int = 200, base: float = 10.0) -> pd.DataFrame:
    """构造单调上涨的升序 OHLC 测试数据，足够触发短线判据。"""
    start = datetime(2026, 1, 1)
    dates = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    closes = [round(base + i * 0.1, 2) for i in range(days)]
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * days,
        }
    )


def _make_breakdown_frame(days: int = 200) -> pd.DataFrame:
    """末段急跌的数据，确保短线规则会触发告警。"""
    df = _make_frame(days)
    df.loc[df.index[-3:], "close"] = [5.0, 4.5, 4.0]
    df.loc[df.index[-3:], "open"] = [6.0, 5.0, 4.5]
    df.loc[df.index[-3:], "high"] = [6.1, 5.1, 4.6]
    df.loc[df.index[-3:], "low"] = [4.9, 4.4, 3.9]
    return df


@pytest.fixture
def service(monkeypatch):
    """构造内存版 TrackingEvaluationService 单元，注入桩 frame_loader / template / alert。"""
    from web.backend.services import tracking_alert_service as alert_module
    from web.backend.services import tracking_evaluation_service as eval_module
    from web.backend.services.tracking_alert_service import TrackingAlertService

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    alert_svc = TrackingAlertService(connection_factory=lambda: conn)

    class _StubTrackingService:
        def __init__(self) -> None:
            self.items: list[dict] = []

        def list_items(self, status=None, code=None, limit=100) -> list[dict]:
            if status in (None, "all"):
                return list(self.items)
            return [i for i in self.items if i.get("status") == status]

    class _StubTemplateService:
        def build_engine_inputs(self) -> dict:
            return {"params_overrides": {}, "enabled_rules": None}

    stub_tracking = _StubTrackingService()
    stub_template = _StubTemplateService()

    svc = eval_module.TrackingEvaluationService(
        tracking_service=stub_tracking,
        template_service=stub_template,
        alert_service=alert_svc,
        frame_loader=lambda code: _make_breakdown_frame() if code == "000001" else _make_frame(),
    )
    return svc, stub_tracking, alert_svc


def test_evaluate_active_items_persists_alerts(service) -> None:
    svc, tracking, alert_svc = service
    tracking.items = [
        {
            "tracking_id": "trk_a",
            "code": "000001",
            "status": "holding",
            "signal_date": "2026-01-10",
        }
    ]
    summary = svc.evaluate_active_items(eval_date="2026-07-19")
    assert summary["evaluated"] == 1
    assert summary["alerts_created"] >= 1
    listed = alert_svc.list_alerts(tracking_id="trk_a")
    assert len(listed) == summary["alerts_created"]


def test_evaluate_skips_inactive_status(service) -> None:
    svc, tracking, alert_svc = service
    tracking.items = [
        {"tracking_id": "trk_a", "code": "000001", "status": "closed", "signal_date": "2026-01-10"},
        {"tracking_id": "trk_b", "code": "000002", "status": "holding", "signal_date": "2026-01-10"},
    ]
    summary = svc.evaluate_active_items(eval_date="2026-07-19")
    # 仅评估 holding；closed 跳过
    assert summary["evaluated"] == 1


def test_evaluate_is_idempotent_via_dedup(service) -> None:
    svc, tracking, alert_svc = service
    tracking.items = [
        {"tracking_id": "trk_a", "code": "000001", "status": "holding", "signal_date": "2026-01-10"},
    ]
    first = svc.evaluate_active_items(eval_date="2026-07-19")
    second = svc.evaluate_active_items(eval_date="2026-07-19")
    assert first["alerts_created"] >= 1
    # 相同日期重跑 → 全部 dedup_key 命中
    assert second["alerts_created"] == 0
    assert second["alerts_skipped_dup"] == first["alerts_created"]


def test_evaluate_returns_zero_when_frame_empty(service) -> None:
    svc, tracking, _ = service
    tracking.items = [
        {"tracking_id": "trk_x", "code": "EMPTY", "status": "holding", "signal_date": "2026-01-10"},
    ]
    # frame_loader 仅对 000001 返回 breakdown，其它返回单调上涨 → 无告警但 evaluated=1
    summary = svc.evaluate_active_items(eval_date="2026-07-19")
    assert summary["evaluated"] == 1
    assert summary["alerts_created"] == 0
