import unittest

from web.backend.services.stock_list_service import build_stock_list_response, paginate_codes


class StockListServiceTest(unittest.TestCase):
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
            per_page=2,
            search="",
            sort_by="change_pct",
            sort_order="desc",
            ensure_metric_snapshot=ensure_metric_snapshot,
            build_stock_item=build_stock_item,
            trigger_metric_snapshot_prewarm=lambda *_args: self.fail("prewarm should not run"),
        )

        self.assertEqual(calls["ensure"], 1)
        self.assertEqual(payload["total"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000003", "000001"])
        self.assertEqual(calls["build"], [("000003", True), ("000001", True)])

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
            per_page=2,
            search="",
            sort_by="change_pct",
            sort_order="asc",
            ensure_metric_snapshot=lambda *_args, **_kwargs: None,
            build_stock_item=build_stock_item,
            trigger_metric_snapshot_prewarm=lambda *_args: self.fail("prewarm should not run"),
        )

        self.assertEqual(payload["total"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000002", "000003"])
        self.assertEqual(
            calls["build"],
            [
                ("000001", False),
                ("000002", False),
                ("000003", False),
                ("000002", True),
                ("000003", True),
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
            per_page=2,
            search="",
            sort_by="change_pct",
            sort_order="asc",
            ensure_metric_snapshot=lambda *_args, **_kwargs: {"items_by_code": {}},
            build_stock_item=build_stock_item,
            trigger_metric_snapshot_prewarm=lambda *_args: self.fail("prewarm should not run"),
        )

        self.assertEqual(payload["total"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000002", "000003"])

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
        self.assertEqual(payload["per_page"], 1)
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["total_pages"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000001"])

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
            per_page=2,
            search="",
            sort_by="name",
            sort_order="asc",
            ensure_metric_snapshot=lambda *_args, **_kwargs: self.fail("snapshot should not run"),
            build_stock_item=build_stock_item,
            trigger_metric_snapshot_prewarm=trigger_metric_snapshot_prewarm,
        )

        self.assertEqual(calls["prewarm"], 1)
        self.assertEqual(payload["total"], 3)
        self.assertEqual([item["code"] for item in payload["data"]], ["000001", "000003"])
        self.assertEqual(calls["build"], [("000001", True), ("000003", True)])
