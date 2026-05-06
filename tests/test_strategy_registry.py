from strategy.strategy_registry import StrategyRegistry


class DummyStrategy:
    created = 0

    def __init__(self, params=None):
        type(self).created += 1
        self.params = params or {}


def test_reload_params_reuses_same_instance_for_aliases(tmp_path):
    params_file = tmp_path / "strategy_params.yaml"
    params_file.write_text("AliasA:\n  CAP: 100\nAliasB:\n  CAP: 200\n", encoding="utf-8")
    DummyStrategy.created = 0
    registry = StrategyRegistry(params_file)

    registry.register(DummyStrategy, name="AliasA")
    registry.register(DummyStrategy, name="AliasB")
    DummyStrategy.created = 0

    registry.reload_params()

    assert DummyStrategy.created == 1
    assert registry.get_strategy("AliasA") is registry.get_strategy("AliasB")
