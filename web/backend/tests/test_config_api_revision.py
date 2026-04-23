import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from fastapi.testclient import TestClient

from web.backend.main import app
from web.backend.services.config_service import CONFIG_FILE
from web.backend.services.strategy_service import update_strategy_config
from strategy.strategy_registry import get_registry


class ConfigRevisionApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self._original_config_text = CONFIG_FILE.read_text(encoding="utf-8")

    def tearDown(self):
        CONFIG_FILE.write_text(self._original_config_text, encoding="utf-8")
        get_registry("config/strategy_params.yaml").reload_params()

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


if __name__ == "__main__":
    unittest.main()
