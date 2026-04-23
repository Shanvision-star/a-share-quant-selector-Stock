import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.backend.main import app
from web.backend.services.config_service import CONFIG_FILE
from web.backend.services import strategy_service
from web.backend.services.strategy_service import ConfigRefreshError, update_strategy_config
from strategy.strategy_registry import get_registry


class ConfigRevisionApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self._original_config_text = CONFIG_FILE.read_text(encoding="utf-8")
        self._original_resolved_items_cache = deepcopy(strategy_service._RESOLVED_ITEMS_CACHE)
        self._original_resolved_items_cache_version = strategy_service._RESOLVED_ITEMS_CACHE_VERSION

    def tearDown(self):
        CONFIG_FILE.write_text(self._original_config_text, encoding="utf-8")
        get_registry("config/strategy_params.yaml").reload_params()
        strategy_service._RESOLVED_ITEMS_CACHE.clear()
        strategy_service._RESOLVED_ITEMS_CACHE.update(deepcopy(self._original_resolved_items_cache))
        strategy_service._RESOLVED_ITEMS_CACHE_VERSION = self._original_resolved_items_cache_version

    def _make_changed_value(self, value):
        if isinstance(value, bool):
            return not value
        if isinstance(value, int):
            return value + 1
        if isinstance(value, float):
            return value + 0.1
        if isinstance(value, str):
            return f"{value}-updated"
        self.fail(f"Unsupported param type for test mutation: {type(value)!r}")

    def test_get_config_returns_revision(self):
        res = self.client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("revision", body)
        self.assertIn("updated_at", body)
        self.assertIn("configs", body)

    def test_post_config_rejects_stale_revision(self):
        first = self.client.get("/api/config").json()
        config = deepcopy(first["configs"][0])
        strategy_name = config["strategy_name"]
        param_name, original_value = next(iter(config["params"].items()))
        updated_value = self._make_changed_value(original_value)
        payload = {
            "strategy_name": strategy_name,
            "params": {param_name: updated_value},
            "expected_revision": first["revision"],
        }
        first_write = self.client.post("/api/config", json=payload)
        self.assertEqual(first_write.status_code, 200)

        stale_payload = {
            "strategy_name": strategy_name,
            "params": {param_name: original_value},
            "expected_revision": first["revision"],
        }
        res = self.client.post("/api/config", json=stale_payload)
        self.assertEqual(res.status_code, 409)

    def test_post_config_requires_expected_revision(self):
        first = self.client.get("/api/config").json()
        config = deepcopy(first["configs"][0])
        strategy_name = config["strategy_name"]
        param_name, original_value = next(iter(config["params"].items()))
        updated_value = self._make_changed_value(original_value)
        payload = {
            "strategy_name": strategy_name,
            "params": {param_name: updated_value},
        }

        res = self.client.post("/api/config", json=payload)
        self.assertEqual(res.status_code, 422)

    def test_concurrent_posts_allow_only_one_winner_per_revision(self):
        first = self.client.get("/api/config").json()
        config = deepcopy(first["configs"][0])
        strategy_name = config["strategy_name"]
        param_name, original_value = next(iter(config["params"].items()))
        winner_value = self._make_changed_value(original_value)
        loser_value = self._make_changed_value(winner_value)

        def post_update(value):
            payload = {
                "strategy_name": strategy_name,
                "params": {param_name: value},
                "expected_revision": first["revision"],
            }
            with TestClient(app) as client:
                return client.post("/api/config", json=payload).status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(post_update, (winner_value, loser_value)))

        self.assertCountEqual(statuses, [200, 409])

    def test_post_config_refreshes_runtime_params(self):
        first = self.client.get("/api/config").json()
        config = deepcopy(first["configs"][0])
        strategy_name = config["strategy_name"]
        param_name, original_value = next(iter(config["params"].items()))
        updated_value = self._make_changed_value(original_value)
        payload = {
            "strategy_name": strategy_name,
            "params": {param_name: updated_value},
            "expected_revision": first["revision"],
        }

        res = self.client.post("/api/config", json=payload)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("data", body)
        self.assertIn("revision", body["data"])
        self.assertNotEqual(body["data"]["revision"], first["revision"])

        refreshed = self.client.get("/api/config").json()
        target = next(item for item in refreshed["configs"] if item["strategy_name"] == strategy_name)
        self.assertEqual(target["params"][param_name], updated_value)

        registry = get_registry("config/strategy_params.yaml")
        self.assertEqual(registry.get_strategy(strategy_name).params[param_name], updated_value)

        restore_ok, _ = update_strategy_config(strategy_name, {param_name: original_value}, refreshed["revision"])
        self.assertTrue(restore_ok)

    def _pick_web_strategy_param(self):
        first = self.client.get("/api/config").json()
        _, selected_items = strategy_service.get_resolved_strategy_items()
        strategy_name = selected_items[0][1]
        config = next(item for item in first["configs"] if item["strategy_name"] == strategy_name)
        param_name, original_value = next(iter(config["params"].items()))
        return first, strategy_name, param_name, original_value

    def test_update_strategy_config_refreshes_resolved_items_cache_on_success(self):
        first, strategy_name, param_name, original_value = self._pick_web_strategy_param()
        updated_value = self._make_changed_value(original_value)

        _, stale_items = strategy_service.get_resolved_strategy_items()
        stale_strategy = next(item[2] for item in stale_items if item[1] == strategy_name)
        self.assertEqual(stale_strategy.params[param_name], original_value)

        success, revision = update_strategy_config(
            strategy_name,
            {param_name: updated_value},
            first["revision"],
        )

        self.assertTrue(success)
        self.assertNotEqual(revision, first["revision"])
        self.assertEqual(
            strategy_service._RESOLVED_ITEMS_CACHE,
            {"items": None, "names": None, "ts": 0},
        )

        _, refreshed_items = strategy_service.get_resolved_strategy_items()
        refreshed_strategy = next(item[2] for item in refreshed_items if item[1] == strategy_name)
        self.assertEqual(refreshed_strategy.params[param_name], updated_value)

    def test_update_strategy_config_refreshes_resolved_items_cache_after_rollback(self):
        first, strategy_name, param_name, original_value = self._pick_web_strategy_param()
        updated_value = self._make_changed_value(original_value)

        strategy_service.get_resolved_strategy_items()

        with patch(
            "web.backend.services.strategy_service._invalidate_persisted_strategy_results",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(ConfigRefreshError):
                update_strategy_config(
                    strategy_name,
                    {param_name: updated_value},
                    first["revision"],
                )

        self.assertEqual(
            strategy_service._RESOLVED_ITEMS_CACHE,
            {"items": None, "names": None, "ts": 0},
        )
        _, refreshed_items = strategy_service.get_resolved_strategy_items()
        refreshed_strategy = next(item[2] for item in refreshed_items if item[1] == strategy_name)
        self.assertEqual(refreshed_strategy.params[param_name], original_value)

    def test_update_strategy_config_prevents_inflight_stale_cache_repopulation(self):
        first, strategy_name, param_name, original_value = self._pick_web_strategy_param()
        updated_value = self._make_changed_value(original_value)
        strategy_service._clear_resolved_items_cache()

        original_resolve_selected = strategy_service._resolve_selected_web_strategies
        stale_items_ready = threading.Event()
        continue_resolution = threading.Event()
        call_count = {"value": 0}

        def blocking_resolve_selected(resolved_strategies, strategy_filter):
            result = original_resolve_selected(resolved_strategies, strategy_filter)
            call_count["value"] += 1
            if call_count["value"] == 1:
                stale_items_ready.set()
                continue_resolution.wait(timeout=5)
            return result

        results = {}

        with patch(
            "web.backend.services.strategy_service._resolve_selected_web_strategies",
            side_effect=blocking_resolve_selected,
        ):
            worker = threading.Thread(
                target=lambda: results.setdefault("value", strategy_service.get_resolved_strategy_items()),
            )
            worker.start()
            self.assertTrue(stale_items_ready.wait(timeout=5))

            success, revision = update_strategy_config(
                strategy_name,
                {param_name: updated_value},
                first["revision"],
            )
            self.assertTrue(success)
            self.assertNotEqual(revision, first["revision"])

            continue_resolution.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())

        _, worker_items = results["value"]
        worker_strategy = next(item[2] for item in worker_items if item[1] == strategy_name)
        self.assertEqual(worker_strategy.params[param_name], updated_value)

        _, cached_items = strategy_service.get_resolved_strategy_items()
        cached_strategy = next(item[2] for item in cached_items if item[1] == strategy_name)
        self.assertEqual(cached_strategy.params[param_name], updated_value)


if __name__ == "__main__":
    unittest.main()
