import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from web.backend.routers import stock as stock_router
from web.backend.services.stock_list_service import build_stock_list_response, paginate_codes


class StockListServiceTest(unittest.TestCase):
    def test_get_stock_list_runs_service_in_threadpool(self):
        stock_codes = ["000001", "000002", "abc", "12345"]
        expected_payload = {"data": [], "total": 0}

        with patch("web.backend.services.kline_service._load_stock_names", return_value={"000001": "平安银行"}), \
             patch("web.backend.services.kline_service.csv_manager") as mock_csv_manager, \
             patch("web.backend.routers.stock.build_stock_list_response") as mock_build_response, \
             patch("web.backend.routers.stock.run_in_threadpool", new_callable=AsyncMock, create=True) as mock_run_in_threadpool:
            mock_csv_manager.list_all_stocks.return_value = stock_codes
            mock_build_response.return_value = {"should": "not be returned directly"}
            mock_run_in_threadpool.return_value = expected_payload

            from web.backend.routers.stock import get_stock_list

            payload = asyncio.run(
                get_stock_list(
                    page=1,
                    per_page=50,
                    search="",
                    sort_by="code",
                    sort_order="asc",
                )
            )

            self.assertEqual(payload, expected_payload)
            mock_run_in_threadpool.assert_awaited_once()
            call_args = mock_run_in_threadpool.await_args
            self.assertIs(call_args.args[0], mock_build_response)
            self.assertEqual(call_args.kwargs["stocks"], ["000001", "000002"])
            self.assertEqual(call_args.kwargs["stock_names"], {"000001": "平安银行"})
            self.assertIs(call_args.kwargs["csv_manager"], mock_csv_manager)
            self.assertEqual(call_args.kwargs["page"], 1)
            self.assertEqual(call_args.kwargs["per_page"], 50)
            self.assertEqual(call_args.kwargs["search"], "")
            self.assertEqual(call_args.kwargs["sort_by"], "code")
            self.assertEqual(call_args.kwargs["sort_order"], "asc")
            self.assertIsNotNone(call_args.kwargs["ensure_metric_snapshot"])
            self.assertIsNotNone(call_args.kwargs["build_stock_item"])
            self.assertIsNotNone(call_args.kwargs["trigger_metric_snapshot_prewarm"])

    def test_paginate_codes_respects_page_and_size(self):
        codes = [f"{i:06d}" for i in range(1, 21)]
        page_codes, total = paginate_codes(codes, page=2, per_page=5)
        self.assertEqual(total, 20)
        self.assertEqual(page_codes, ["000006", "000007", "000008", "000009", "000010"])

    def test_build_stock_list_response_uses_metric_snapshot_order(self):
        stocks = ["000001", "000002", "000003"]
        stock_names = {"000001": "甲", "000002": "乙", "000003": "丙"}
        calls = {"ensure": 0, "build": []}

        def ensure_metric_snapshot(codes, *_args, **_kwargs):
            calls["ensure"] += 1
            self.assertEqual(codes, stocks)
            return {
                "sorted_codes": {
                    "change_pct": ["000002", "000001", "000003"],
                }
            }

        def build_stock_item(code, *_args, include_mini_kline, **_kwargs):
            calls["build"].append((code, include_mini_kline))
            return {"code": code}

        payload = build_stock_list_response(
            stocks=stocks,
            stock_names=stock_names,
            csv_manager=object(),
            page=1,
            per_page=10,
            search="",
            sort_by="change_pct",
            sort_order="desc",
            ensure_metric_snapshot=ensure_metric_snapshot,
            build_stock_item=build_stock_item,
            trigger_metric_snapshot_prewarm=lambda *_args: self.fail("prewarm should not run"),
        )

        self.assertEqual(calls["ensure"], 1)
        self.assertEqual(payload["total"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000003", "000001", "000002"])
        self.assertEqual(calls["build"], [("000003", True), ("000001", True), ("000002", True)])

    def test_build_stock_list_response_falls_back_when_snapshot_missing(self):
        stocks = ["000001", "000002", "000003"]
        stock_names = {"000001": "甲", "000002": "乙", "000003": "丙"}
        calls = {"build": []}
        metric_values = {
            "000001": 3.0,
            "000002": 1.0,
            "000003": 2.0,
        }

        def build_stock_item(code, *_args, include_mini_kline, **_kwargs):
            calls["build"].append((code, include_mini_kline))
            return {"code": code, "change_pct": metric_values[code]}

        payload = build_stock_list_response(
            stocks=stocks,
            stock_names=stock_names,
            csv_manager=object(),
            page=1,
            per_page=10,
            search="",
            sort_by="change_pct",
            sort_order="asc",
            ensure_metric_snapshot=lambda *_args, **_kwargs: None,
            build_stock_item=build_stock_item,
            trigger_metric_snapshot_prewarm=lambda *_args: self.fail("prewarm should not run"),
        )

        self.assertEqual(payload["total"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000002", "000003", "000001"])
        self.assertEqual(
            calls["build"],
            [
                ("000001", False),
                ("000002", False),
                ("000003", False),
                ("000002", True),
                ("000003", True),
                ("000001", True),
            ],
        )

    def test_build_stock_list_response_falls_back_when_snapshot_payload_malformed(self):
        stocks = ["000001", "000002", "000003"]
        stock_names = {"000001": "甲", "000002": "乙", "000003": "丙"}
        metric_values = {
            "000001": 3.0,
            "000002": 1.0,
            "000003": 2.0,
        }

        def build_stock_item(code, *_args, include_mini_kline, **_kwargs):
            item = {"code": code, "change_pct": metric_values[code]}
            if include_mini_kline:
                item["mini_kline"] = []
            return item

        payload = build_stock_list_response(
            stocks=stocks,
            stock_names=stock_names,
            csv_manager=object(),
            page=1,
            per_page=10,
            search="",
            sort_by="change_pct",
            sort_order="asc",
            ensure_metric_snapshot=lambda *_args, **_kwargs: {"items_by_code": {}},
            build_stock_item=build_stock_item,
            trigger_metric_snapshot_prewarm=lambda *_args: self.fail("prewarm should not run"),
        )

        self.assertEqual(payload["total"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000002", "000003", "000001"])

    def test_build_stock_list_response_normalizes_invalid_pagination(self):
        stocks = ["000002", "000001", "000003"]
        stock_names = {"000001": "A", "000002": "C", "000003": "B"}

        payload = build_stock_list_response(
            stocks=stocks,
            stock_names=stock_names,
            csv_manager=object(),
            page=0,
            per_page=0,
            search="",
            sort_by="code",
            sort_order="asc",
            ensure_metric_snapshot=lambda *_args, **_kwargs: self.fail("snapshot should not run"),
            build_stock_item=lambda code, *_args, **_kwargs: {"code": code},
            trigger_metric_snapshot_prewarm=lambda *_args: None,
        )

        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["per_page"], 10)
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["total_pages"], 1)
        self.assertEqual([item["code"] for item in payload["data"]], ["000001", "000002", "000003"])

    def test_build_stock_list_response_non_metric_sort_triggers_prewarm(self):
        stocks = ["000002", "000001", "000003"]
        stock_names = {"000001": "A", "000002": "C", "000003": "B"}
        calls = {"prewarm": 0, "build": []}

        def build_stock_item(code, *_args, include_mini_kline, **_kwargs):
            calls["build"].append((code, include_mini_kline))
            return {"code": code}

        def trigger_metric_snapshot_prewarm(codes, *_args):
            calls["prewarm"] += 1
            self.assertEqual(codes, stocks)

        payload = build_stock_list_response(
            stocks=stocks,
            stock_names=stock_names,
            csv_manager=object(),
            page=1,
            per_page=10,
            search="",
            sort_by="name",
            sort_order="asc",
            ensure_metric_snapshot=lambda *_args, **_kwargs: self.fail("snapshot should not run"),
            build_stock_item=build_stock_item,
            trigger_metric_snapshot_prewarm=trigger_metric_snapshot_prewarm,
        )

        self.assertEqual(calls["prewarm"], 1)
        self.assertEqual(payload["total"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000001", "000003", "000002"])
        self.assertEqual(calls["build"], [("000001", True), ("000003", True), ("000002", True)])

    def test_build_stock_list_response_metric_snapshot_uses_full_stocks_for_search(self):
        stocks = ["000001", "000002", "000003"]
        stock_names = {"000001": "甲", "000002": "乙", "000003": "丙"}

        def ensure_metric_snapshot(codes, *_args, **_kwargs):
            self.assertEqual(codes, stocks)
            return {
                "sorted_codes": {
                    "change_pct": ["000003", "000002", "000001"],
                }
            }

        payload = build_stock_list_response(
            stocks=stocks,
            stock_names=stock_names,
            csv_manager=object(),
            page=1,
            per_page=10,
            search="乙",
            sort_by="change_pct",
            sort_order="asc",
            ensure_metric_snapshot=ensure_metric_snapshot,
            build_stock_item=lambda code, *_args, **_kwargs: {"code": code},
            trigger_metric_snapshot_prewarm=lambda *_args: self.fail("prewarm should not run"),
        )

        self.assertEqual(payload["total"], 1)
        self.assertEqual([item["code"] for item in payload["data"]], ["000002"])

    def test_build_stock_list_response_non_metric_prewarm_uses_full_stocks_for_search(self):
        stocks = ["000002", "000001", "000003"]
        stock_names = {"000001": "甲", "000002": "乙", "000003": "丙"}

        def trigger_metric_snapshot_prewarm(codes, *_args):
            self.assertEqual(codes, stocks)

        payload = build_stock_list_response(
            stocks=stocks,
            stock_names=stock_names,
            csv_manager=object(),
            page=1,
            per_page=10,
            search="乙",
            sort_by="code",
            sort_order="asc",
            ensure_metric_snapshot=lambda *_args, **_kwargs: self.fail("snapshot should not run"),
            build_stock_item=lambda code, *_args, **_kwargs: {"code": code},
            trigger_metric_snapshot_prewarm=trigger_metric_snapshot_prewarm,
        )

        self.assertEqual(payload["total"], 1)
        self.assertEqual([item["code"] for item in payload["data"]], ["000002"])

    def test_build_metric_snapshot_sets_event_when_build_is_superseded(self):
        original_state = {}
        with stock_router._METRIC_SNAPSHOT_LOCK:
            original_state = dict(stock_router._METRIC_SNAPSHOT_STATE)
            stock_router._METRIC_SNAPSHOT_STATE["generation"] = 99
            stock_router._METRIC_SNAPSHOT_STATE["signature"] = ("999999",)
            stock_router._METRIC_SNAPSHOT_STATE["building"] = True
            stock_router._METRIC_SNAPSHOT_STATE["ready"] = False
            stock_router._METRIC_SNAPSHOT_STATE["event"] = threading.Event()
            stock_router._METRIC_SNAPSHOT_STATE["items_by_code"] = {}
            stock_router._METRIC_SNAPSHOT_STATE["sorted_codes"] = {}

        build_event = threading.Event()
        try:
            with patch("web.backend.routers.stock._build_stock_item", return_value={
                "code": "000001",
                "latest_price": 1.0,
                "change_pct": 1.0,
                "market_cap": 1.0,
                "latest_date": "2026-01-01",
                "k_value": 1.0,
                "d_value": 1.0,
                "j_value": 1.0,
            }):
                stock_router._build_metric_snapshot(
                    stocks=["000001"],
                    stock_names={},
                    csv_manager=object(),
                    signature=("000001",),
                    generation=1,
                    build_event=build_event,
                )
            self.assertTrue(build_event.is_set())
        finally:
            with stock_router._METRIC_SNAPSHOT_LOCK:
                stock_router._METRIC_SNAPSHOT_STATE.clear()
                stock_router._METRIC_SNAPSHOT_STATE.update(original_state)


