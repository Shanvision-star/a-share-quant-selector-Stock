"""P4 跟踪告警事件持久化 + 钉钉分发桩 测试。

设计要点：
1. 入库幂等：同 dedup_key 第二次写入不会重复，返回 skipped_dup；
2. 优先级分层（按 docs/Tracking/tracking_agent_plan.md §6 钉钉调度）：
   - priority < 30  必发（强制触达，无视 slot 容量）
   - 30 <= priority < 60  按规模（每个 slot 限额）
   - priority >= 60  聚合（合并到 daily roll-up，不立即推送）
3. 三个 slot 09:00 / 11:30 / 15:30；每次 dispatch 只处理 ui_status=pending 的事件；
4. 通知器接口（notifier.send(slot, alerts) -> None）默认无操作，便于测试桩；
5. list 支持按 tracking_id / eval_date / ui_status 过滤。
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

import pytest

from web.backend.services.tracking_alert_service import TrackingAlertService


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class _RecordingNotifier:
    """测试桩通知器：记录每次 send 调用，不做真实 HTTP。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict]]] = []

    def send(self, slot: str, alerts: Iterable[dict]) -> None:
        self.calls.append((slot, list(alerts)))


def _make_alert(
    tracking_id: str,
    rule_id: str,
    eval_date: str,
    priority: int,
    *,
    code: str = "000001",
    category: str = "short_term",
    action_label: str = "TREND_BREAK",
    name: str = "测试规则",
    message: str = "测试消息",
    evidence: dict | None = None,
) -> dict:
    return {
        "tracking_id": tracking_id,
        "rule_id": rule_id,
        "code": code,
        "eval_date": eval_date,
        "priority": priority,
        "category": category,
        "action_label": action_label,
        "name": name,
        "message": message,
        "evidence": evidence or {"k": "v"},
        "dedup_key": f"{tracking_id}|{rule_id}|{eval_date}",
    }


@pytest.fixture
def service() -> TrackingAlertService:
    conn = _memory_conn()
    return TrackingAlertService(connection_factory=lambda: conn)


def test_persist_alerts_inserts_and_returns_created_count(service: TrackingAlertService) -> None:
    alerts = [
        _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10),
        _make_alert("t2", "rule_break_bull_bear", "2026-05-01", 20),
    ]
    result = service.persist_alerts(alerts)
    assert result == {"created": 2, "skipped_dup": 0}

    items = service.list_alerts()
    assert len(items) == 2
    assert {it["tracking_id"] for it in items} == {"t1", "t2"}


def test_persist_alerts_is_idempotent_on_dedup_key(service: TrackingAlertService) -> None:
    alert = _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10)
    service.persist_alerts([alert])

    # 二次写入完全相同的 dedup_key，应被去重
    result = service.persist_alerts([alert, _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10, message="不同消息")])
    assert result == {"created": 0, "skipped_dup": 2}

    items = service.list_alerts()
    assert len(items) == 1


def test_list_alerts_supports_filters(service: TrackingAlertService) -> None:
    service.persist_alerts(
        [
            _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10),
            _make_alert("t1", "rule_short_overshoot", "2026-05-02", 50),
            _make_alert("t2", "rule_break_bull_bear", "2026-05-01", 20),
        ]
    )

    by_tracking = service.list_alerts(tracking_id="t1")
    assert {it["rule_id"] for it in by_tracking} == {"rule_break_short_trend", "rule_short_overshoot"}

    by_date = service.list_alerts(eval_date="2026-05-01")
    assert len(by_date) == 2

    by_status = service.list_alerts(ui_status="pending")
    assert len(by_status) == 3


def test_dispatch_pending_alerts_priority_tier_must_send(service: TrackingAlertService) -> None:
    """priority<30 一律推送（必发层）。"""
    notifier = _RecordingNotifier()
    service.notifier = notifier
    service.persist_alerts(
        [
            _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10),
            _make_alert("t2", "rule_break_bull_bear", "2026-05-01", 20),
        ]
    )

    summary = service.dispatch_pending_alerts(slot="09:00")
    assert summary["dispatched"] == 2
    assert summary["aggregated"] == 0
    assert len(notifier.calls) == 1
    sent_slot, sent_alerts = notifier.calls[0]
    assert sent_slot == "09:00"
    assert {a["rule_id"] for a in sent_alerts} == {"rule_break_short_trend", "rule_break_bull_bear"}

    # 二次 dispatch 不应重复发送
    summary2 = service.dispatch_pending_alerts(slot="09:00")
    assert summary2["dispatched"] == 0


def test_dispatch_pending_alerts_priority_tier_aggregated(service: TrackingAlertService) -> None:
    """priority>=60 聚合层：不立即推送，仅标记为 aggregated。"""
    notifier = _RecordingNotifier()
    service.notifier = notifier
    service.persist_alerts(
        [
            _make_alert("t1", "rule_stall_exit", "2026-05-01", 60),
            _make_alert("t2", "rule_long_dead_cross", "2026-05-01", 70),
        ]
    )

    summary = service.dispatch_pending_alerts(slot="09:00")
    assert summary["dispatched"] == 0
    assert summary["aggregated"] == 2
    assert notifier.calls == []  # 聚合层不推送

    # 状态被标记为 aggregated，不再属于 pending
    pending = service.list_alerts(ui_status="pending")
    assert len(pending) == 0
    aggregated = service.list_alerts(ui_status="aggregated")
    assert len(aggregated) == 2


def test_dispatch_pending_alerts_priority_tier_scale_limited(service: TrackingAlertService) -> None:
    """30<=priority<60 按规模推送：受 per_slot_limit 限制；本测试设 limit=2。"""
    notifier = _RecordingNotifier()
    service.notifier = notifier
    service.persist_alerts(
        [
            _make_alert("t1", "rule_short_overshoot", "2026-05-01", 50, code="000001"),
            _make_alert("t2", "rule_short_overshoot", "2026-05-01", 50, code="000002"),
            _make_alert("t3", "rule_short_overshoot", "2026-05-01", 50, code="000003"),
        ]
    )

    summary = service.dispatch_pending_alerts(slot="11:30", per_slot_limit=2)
    assert summary["dispatched"] == 2
    assert summary["deferred"] == 1
    assert len(notifier.calls) == 1
    assert len(notifier.calls[0][1]) == 2

    # 剩余 1 条仍 pending，下个 slot 可以继续发
    pending = service.list_alerts(ui_status="pending")
    assert len(pending) == 1


def test_update_alert_status_acknowledges_existing_alert(service: TrackingAlertService) -> None:
    service.persist_alerts([
        _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10),
    ])
    alert = service.list_alerts()[0]

    updated = service.update_alert_status(alert["alert_id"], "acknowledged")

    assert updated["alert_id"] == alert["alert_id"]
    assert updated["ui_status"] == "acknowledged"
    assert service.list_alerts(ui_status="pending") == []


def test_update_alert_status_rejects_invalid_status(service: TrackingAlertService) -> None:
    service.persist_alerts([
        _make_alert("t1", "rule_break_short_trend", "2026-05-01", 10),
    ])
    alert = service.list_alerts()[0]

    with pytest.raises(ValueError, match="unsupported alert status"):
        service.update_alert_status(alert["alert_id"], "sent")
