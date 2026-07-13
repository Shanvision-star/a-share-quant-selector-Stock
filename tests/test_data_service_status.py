"""数据状态报告的稳定性回归测试。"""

from utils.status_sampling import select_status_sample


def test_status_sample_is_deterministic_and_spread_across_board():
    """同一股票池每次检查应采样同一批股票，且尽量覆盖首尾位置。"""
    codes = [f"600{i:03d}" for i in range(20)]

    first = select_status_sample(codes, sample_size=4)
    second = select_status_sample(codes, sample_size=4)

    assert first == second
    assert first == ["600000", "600006", "600012", "600019"]
