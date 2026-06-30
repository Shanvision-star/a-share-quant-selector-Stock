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


def test_auto_register_includes_zettaranc_combo_strategy():
    registry = StrategyRegistry("config/strategy_params.yaml")

    registry.auto_register_from_directory("strategy")

    strategy = registry.get_strategy("ZettarancComboStrategy")
    assert strategy.__class__.__name__ == "ZettarancComboStrategy"
    assert strategy.params["J_BUY"] == 0
    assert strategy.params["VOL_RATIO_MIN"] == 1.3
