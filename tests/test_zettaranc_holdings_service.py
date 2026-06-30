"""ZettarancHoldingsService 单元测试（不读真实 CSV，用 stub csv_manager）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web.backend.services.zettaranc_holdings_service import (
    Holding,
    ZettarancHoldingsService,
)


class StubCsv:
    """假 CSVManager：按字典返回最新收盘价。"""

    def __init__(self, mapping: dict[str, float]) -> None:
        self.mapping = mapping

    def read_stock(self, code, parse_dates=False, nrows=None, usecols=None):
        if code not in self.mapping:
            return pd.DataFrame()
        return pd.DataFrame({"close": [self.mapping[code]]})


@pytest.fixture
def svc(tmp_path: Path) -> ZettarancHoldingsService:
    storage = tmp_path / "holdings.json"
    csv = StubCsv({"000001": 9.0, "600000": 12.0, "000003": 5.0})
    return ZettarancHoldingsService(storage, csv_manager=csv)


def test_crud_lifecycle(svc: ZettarancHoldingsService) -> None:
    assert svc.list_holdings() == []
    h = Holding(code="000001", name="平安银行", entry_date="2026-05-01",
                entry_price=10.0, qty=1000, stop_loss=9.5)
    svc.add_holding(h)
    assert len(svc.list_holdings()) == 1

    updated = svc.update_holding("000001", {"qty": 2000, "notes": "加仓"})
    assert updated and updated["qty"] == 2000 and updated["notes"] == "加仓"

    # 同 code add 视为覆盖
    svc.add_holding(Holding(code="000001", name="平安银行", entry_date="2026-05-02",
                            entry_price=11.0, qty=500, stop_loss=10.5))
    items = svc.list_holdings()
    assert len(items) == 1 and items[0]["qty"] == 500

    assert svc.delete_holding("000001") is True
    assert svc.delete_holding("000001") is False


def test_alert_stop_loss_triggers_critical(svc: ZettarancHoldingsService) -> None:
    svc.add_holding(Holding(code="000001", name="平安银行", entry_date="2026-05-01",
                            entry_price=10.0, qty=1000, stop_loss=9.5))
    alerts = svc.check_stop_alerts(today="2026-05-10")
    rules = [a["rule"] for a in alerts]
    assert "stop_loss" in rules
    stop = next(a for a in alerts if a["rule"] == "stop_loss")
    assert stop["severity"] == "critical"


def test_alert_take_profit_warn(svc: ZettarancHoldingsService) -> None:
    svc.add_holding(Holding(code="600000", name="浦发", entry_date="2026-05-01",
                            entry_price=10.0, qty=1000, stop_loss=9.0,
                            take_profit_pct=15.0))
    alerts = svc.check_stop_alerts(today="2026-05-10")
    rules = [a["rule"] for a in alerts]
    assert "take_profit" in rules
    tp = next(a for a in alerts if a["rule"] == "take_profit")
    assert tp["severity"] == "warn" and tp["extra"]["gain_pct"] >= 15.0


def test_alert_time_stop(svc: ZettarancHoldingsService) -> None:
    svc.add_holding(Holding(code="600000", name="浦发", entry_date="2026-04-01",
                            entry_price=10.0, qty=1000, stop_loss=9.0,
                            hold_days_limit=20))
    alerts = svc.check_stop_alerts(today="2026-05-15")
    rules = [a["rule"] for a in alerts]
    assert "time_stop" in rules


def test_alert_position_overflow(svc: ZettarancHoldingsService) -> None:
    # 仓位：qty*close / total_cap = 1000*9.0 / 10000 = 90% > 10%
    svc.add_holding(Holding(code="000001", name="平安银行", entry_date="2026-05-01",
                            entry_price=8.0, qty=1000, stop_loss=7.0,
                            max_position_pct=10.0, total_capital=10_000))
    alerts = svc.check_stop_alerts(today="2026-05-05")
    rules = [a["rule"] for a in alerts]
    assert "position_overflow" in rules


def test_alert_missing_data(svc: ZettarancHoldingsService) -> None:
    svc.add_holding(Holding(code="999999", name="未知", entry_date="2026-05-01",
                            entry_price=10.0, qty=100, stop_loss=9.0))
    alerts = svc.check_stop_alerts(today="2026-05-05")
    assert any(a["rule"] == "missing_data" for a in alerts)


def test_alerts_sorted_critical_first(svc: ZettarancHoldingsService) -> None:
    svc.add_holding(Holding(code="600000", name="浦发", entry_date="2026-05-01",
                            entry_price=10.0, qty=1000, stop_loss=9.0))  # take_profit warn
    svc.add_holding(Holding(code="000001", name="平安", entry_date="2026-05-01",
                            entry_price=10.0, qty=1000, stop_loss=9.5))  # stop_loss critical
    alerts = svc.check_stop_alerts(today="2026-05-05")
    assert alerts[0]["severity"] == "critical"
