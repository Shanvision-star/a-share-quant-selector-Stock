"""P5 自动级联开关测试：app_meta.tracking_auto_cascade。

- 默认 OFF：batch_from_selection 不调用规则评估
- ON：batch_from_selection 调用一次评估，并把 evaluate 摘要并入返回
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def tracking_module(monkeypatch):
    """构造内存 sqlite + 桩 manual_selection_service / 评估服务的隔离环境。"""
    from web.backend.services import sqlite_service as sqlite_module
    from web.backend.services import tracking_service as tracking_module_

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    monkeypatch.setattr(sqlite_module, "get_connection", lambda: conn)
    sqlite_module.init_database()

    # 桩 manual_selection_service.list_selections：返回单条候选
    from web.backend.services import manual_selection_service as mss_module

    def _stub_list_selections(selection_date, **_kwargs):
        return [
            {
                "code": "000001",
                "name": "TestA",
                "strategy_name": "B1",
                "source_trade_date": selection_date,
                "source_signal_date": selection_date,
            }
        ]

    monkeypatch.setattr(mss_module, "list_selections", _stub_list_selections)

    # 重建 TrackingService 时显式注入内存连接，避免污染真实 DB
    svc = tracking_module_.TrackingService(connection_factory=lambda: conn)
    return svc, tracking_module_, conn


def test_batch_default_does_not_cascade(tracking_module, monkeypatch) -> None:
    svc, tracking_module_, _conn = tracking_module

    called = {"n": 0}

    class _Eval:
        def evaluate_active_items(self, eval_date=None, only_codes=None):
            called["n"] += 1
            return {"evaluated": 1, "alerts_created": 0, "alerts_skipped_dup": 0}

    monkeypatch.setattr(
        tracking_module_, "tracking_evaluation_service", _Eval(), raising=False
    )

    result = svc.batch_from_selection(selection_date="2026-07-19", codes=["000001"])
    assert result["created"] == 1
    # 默认开关 OFF → 不应触发评估
    assert called["n"] == 0
    assert "evaluation" not in result


def test_batch_with_cascade_on_invokes_evaluation(tracking_module, monkeypatch) -> None:
    from web.backend.services.sqlite_service import set_app_meta

    svc, tracking_module_, _conn = tracking_module

    called = {"n": 0, "only": None}

    class _Eval:
        def evaluate_active_items(self, eval_date=None, only_codes=None):
            called["n"] += 1
            called["only"] = list(only_codes) if only_codes else None
            return {"evaluated": 1, "alerts_created": 2, "alerts_skipped_dup": 0}

    monkeypatch.setattr(
        tracking_module_, "tracking_evaluation_service", _Eval(), raising=False
    )

    set_app_meta("tracking_auto_cascade", "on")
    result = svc.batch_from_selection(selection_date="2026-07-19", codes=["000001"])
    assert called["n"] == 1
    assert called["only"] == ["000001"]
    assert result.get("evaluation", {}).get("alerts_created") == 2
