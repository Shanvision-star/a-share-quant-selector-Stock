"""验证 backtest_lab 最小样本对比。

实验层只能读取固定样本并输出对比结果，不能修改生产回测引擎。
"""

from backtest_lab.compare import run_minimal_comparison


def test_backtest_lab_minimal_sample_matches_reference_model():
    """同一股票、同一信号、20 日样本下，项目引擎应和参考事件模型对齐。"""
    result = run_minimal_comparison(include_backtesting_py=False)

    assert result["sample"]["code"] == "000001"
    assert result["sample"]["bar_count"] == 20
    assert result["project_engine"]["trade_count"] == 1
    assert result["reference_event_model"]["trade_count"] == 1
    assert result["diffs"] == []
    assert result["project_engine"]["buy_date"] == result["reference_event_model"]["buy_date"]
    assert result["project_engine"]["sell_date"] == result["reference_event_model"]["sell_date"]
    assert abs(result["project_engine"]["return_pct"] - result["reference_event_model"]["return_pct"]) <= 0.01


def test_backtest_lab_reports_external_adapter_status():
    """外部框架适配器必须结构化报告状态，便于后续判断是否可纳入对比。"""
    result = run_minimal_comparison(include_backtesting_py=True)

    assert "backtesting_py" in result
    assert result["backtesting_py"]["status"] in {"passed", "missing", "failed"}
