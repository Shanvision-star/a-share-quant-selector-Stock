"""zettaranc 路由集成测试（TestClient）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_backtest_run_defaults_match_optimized_params():
    from web.backend.routers.zettaranc import BacktestRunIn

    payload = BacktestRunIn()

    assert payload.j_buy == 0.0
    assert payload.vol_ratio == 1.3


@pytest.fixture
def client(tmp_path, monkeypatch):
    # 隔离持仓 JSON 与 latest 回测文件
    from web.backend.services import zettaranc_holdings_service as svc_mod

    storage = tmp_path / "holdings.json"

    class _StubCsv:
        def read_stock(self, code, parse_dates=False, nrows=None, usecols=None):
            import pandas as pd
            mp = {"000001": 9.0, "600000": 12.0}
            if code not in mp:
                return pd.DataFrame()
            return pd.DataFrame({"close": [mp[code]]})

    monkeypatch.setattr(
        svc_mod, "_default_service",
        svc_mod.ZettarancHoldingsService(storage, csv_manager=_StubCsv()),
    )

    # 准备一个假的回测 latest 文件
    from web.backend.routers import zettaranc as router_mod
    fake_latest = tmp_path / "fake_latest.json"
    fake_latest.write_text(json.dumps({"total_trades": 4, "win_rate": 50.0}), encoding="utf-8")
    monkeypatch.setattr(router_mod, "BACKTEST_LATEST", fake_latest)

    from web.backend.main import app
    return TestClient(app)


def test_holdings_crud_via_api(client):
    r = client.get("/api/zettaranc/holdings")
    assert r.status_code == 200 and r.json()["success"] is True

    payload = {
        "code": "000001", "name": "平安", "entry_date": "2026-05-01",
        "entry_price": 10.0, "qty": 100, "stop_loss": 9.5,
    }
    r = client.post("/api/zettaranc/holdings", json=payload)
    assert r.status_code == 200 and r.json()["data"]["code"] == "000001"

    r = client.patch("/api/zettaranc/holdings/000001", json={"qty": 200})
    assert r.status_code == 200 and r.json()["data"]["qty"] == 200

    r = client.get("/api/zettaranc/holdings/alerts?today=2026-05-05")
    assert r.status_code == 200
    body = r.json()["data"]
    assert "alerts" in body and "summary" in body
    # 9.0 < 9.5 → critical stop_loss
    rules = [a["rule"] for a in body["alerts"]]
    assert "stop_loss" in rules

    r = client.delete("/api/zettaranc/holdings/000001")
    assert r.status_code == 200


def test_backtest_latest_via_api(client):
    r = client.get("/api/zettaranc/backtest/latest")
    assert r.status_code == 200
    assert r.json()["data"]["total_trades"] == 4


def test_attack_scan_endpoint(client):
    r = client.get("/api/zettaranc/attack-scan?limit=1")
    assert r.status_code == 200
    assert "candidates" in r.json()["data"]
