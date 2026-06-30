from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from web.backend.routers import config_api, kline, stock, strategy


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(config_api.router)
    app.include_router(kline.router)
    app.include_router(stock.router)
    app.include_router(strategy.router)
    return app


@pytest.mark.parametrize("code", ["abc123", "00001", "0000011"])
def test_kline_rejects_invalid_stock_code(code):
    client = TestClient(_build_test_app())

    response = client.get(f"/api/kline/{code}")

    assert response.status_code == 422


@pytest.mark.parametrize("code", ["abc123", "00001", "0000011"])
def test_strategy_history_rejects_invalid_stock_code(code):
    client = TestClient(_build_test_app())

    response = client.get("/api/strategy/results/history", params={"code": code})

    assert response.status_code == 422


def test_strategy_history_rejects_unbounded_page_size():
    client = TestClient(_build_test_app())

    response = client.get("/api/strategy/results/history", params={"per_page": 1000})

    assert response.status_code == 422


def test_strategy_results_accepts_zettaranc_filter(monkeypatch):
    from web.backend.services import strategy_service

    monkeypatch.setattr(strategy_service, "run_strategy", lambda strategy, date=None: {"strategy_filter": strategy})
    client = TestClient(_build_test_app())

    response = client.get("/api/strategy/results", params={"strategy": "zettaranc"})

    assert response.status_code == 200
    assert response.json()["data"]["strategy_filter"] == "zettaranc"


def test_backtest_request_accepts_zettaranc_strategy():
    from web.backend.routers.backtest import BacktestRequest

    payload = BacktestRequest(
        start_date="2026-01-01",
        end_date="2026-01-31",
        strategy="zettaranc",
    )

    assert payload.strategy == "zettaranc"


def test_stock_list_rejects_unbounded_page_size():
    client = TestClient(_build_test_app())

    response = client.get("/api/stock/list", params={"per_page": 1000})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "forbidden_key",
    ["data_dir", "dingtalk", "dingtalk.secret", "dingtalk.webhook_url", " DINGTALK.SECRET "],
)
def test_config_update_rejects_sensitive_params(monkeypatch, forbidden_key):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("update_strategy_config should not be called for forbidden keys")

    from web.backend.services import strategy_service

    monkeypatch.setattr(strategy_service, "update_strategy_config", fail_if_called)
    client = TestClient(_build_test_app())

    response = client.post(
        "/api/config",
        json={
            "strategy_name": "B1Strategy",
            "expected_revision": "revision",
            "params": {forbidden_key: "../outside"},
        },
    )

    assert response.status_code == 422
    assert "禁止写入配置项" in response.json()["detail"]


def test_config_update_rejects_unknown_top_level_fields():
    client = TestClient(_build_test_app())

    response = client.post(
        "/api/config",
        json={
            "strategy_name": "B1Strategy",
            "expected_revision": "revision",
            "params": {"CAP": 100},
            "data_dir": "../outside",
        },
    )

    assert response.status_code == 422
