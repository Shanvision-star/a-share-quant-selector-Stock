"""P3 跟踪告警-规则模板服务测试。

模板表用于在 P2 引擎之上做"按用户偏好启用/禁用规则 + 覆盖参数"。

边界：
1. 内存 SQLite 自建 schema，create/list/get/update/delete 全闭环；
2. enabled=0 的模板会从 enabled_rules 集合中排除；
3. params_overrides 必须按 rule_id 聚合；多模板覆盖同一 rule 时，后写覆盖前写；
4. 未知 rule_id 一律拒收（返回 ValueError），避免脏数据进库；
5. delete 不存在的 id 返回 False，不抛异常。
"""

from __future__ import annotations

import sqlite3

import pytest

from web.backend.services.tracking_rule_engine import RULE_META
from web.backend.services.tracking_rule_templates import (
    TrackingRuleTemplateService,
)


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def service() -> TrackingRuleTemplateService:
    conn = _memory_conn()
    return TrackingRuleTemplateService(connection_factory=lambda: conn)


def test_create_and_list_returns_inserted_template(service: TrackingRuleTemplateService) -> None:
    record = service.create(
        {
            "name": "稳健-跌破短线",
            "rule_id": "rule_break_short_trend",
            "params": {"tolerance_pct": 1.0, "confirm_close_count": 2},
            "enabled": True,
        }
    )
    assert record["template_id"]
    assert record["rule_id"] == "rule_break_short_trend"
    assert record["params"] == {"tolerance_pct": 1.0, "confirm_close_count": 2}
    assert record["enabled"] is True

    items = service.list()
    assert len(items) == 1
    assert items[0]["template_id"] == record["template_id"]


def test_create_rejects_unknown_rule_id(service: TrackingRuleTemplateService) -> None:
    with pytest.raises(ValueError):
        service.create({"name": "x", "rule_id": "rule_does_not_exist", "params": {}})


def test_update_changes_params_and_enabled(service: TrackingRuleTemplateService) -> None:
    record = service.create(
        {"name": "A", "rule_id": "rule_short_overshoot", "params": {"overshoot_pct": 10}, "enabled": True}
    )
    updated = service.update(
        record["template_id"],
        {"params": {"overshoot_pct": 12}, "enabled": False, "name": "A2"},
    )
    assert updated["params"] == {"overshoot_pct": 12}
    assert updated["enabled"] is False
    assert updated["name"] == "A2"


def test_update_missing_template_returns_none(service: TrackingRuleTemplateService) -> None:
    assert service.update("nope", {"enabled": False}) is None


def test_delete_removes_record_and_idempotent(service: TrackingRuleTemplateService) -> None:
    record = service.create(
        {"name": "B", "rule_id": "rule_stall_exit", "params": {"stall_days": 7}}
    )
    assert service.delete(record["template_id"]) is True
    assert service.delete(record["template_id"]) is False
    assert service.list() == []


def test_build_engine_inputs_aggregates_overrides_and_enabled_rules(
    service: TrackingRuleTemplateService,
) -> None:
    service.create(
        {"name": "短线松", "rule_id": "rule_break_short_trend", "params": {"tolerance_pct": 1.0}, "enabled": True}
    )
    service.create(
        {"name": "短线严覆盖", "rule_id": "rule_break_short_trend", "params": {"confirm_close_count": 3}, "enabled": True}
    )
    service.create(
        {"name": "禁用放飞", "rule_id": "rule_short_overshoot", "params": {"overshoot_pct": 20}, "enabled": False}
    )
    service.create(
        {"name": "死叉", "rule_id": "rule_long_dead_cross", "params": {"fast_window": 30}, "enabled": True}
    )

    inputs = service.build_engine_inputs()
    overrides = inputs["params_overrides"]
    enabled = inputs["enabled_rules"]

    # 短线规则：两条模板都启用，后写的覆盖前写 → 合并 tolerance_pct + confirm_close_count
    assert overrides["rule_break_short_trend"] == {"tolerance_pct": 1.0, "confirm_close_count": 3}
    assert overrides["rule_long_dead_cross"] == {"fast_window": 30}
    # 放飞模板被禁用 → 不进 overrides 也不在 enabled_rules
    assert "rule_short_overshoot" not in overrides
    assert "rule_short_overshoot" not in enabled
    assert "rule_break_short_trend" in enabled
    assert "rule_long_dead_cross" in enabled


def test_build_engine_inputs_empty_returns_full_rule_set(
    service: TrackingRuleTemplateService,
) -> None:
    """无模板时默认放行全部规则，引擎走 DEFAULT_PARAMS。"""
    inputs = service.build_engine_inputs()
    assert inputs["params_overrides"] == {}
    assert inputs["enabled_rules"] == set(RULE_META.keys())
