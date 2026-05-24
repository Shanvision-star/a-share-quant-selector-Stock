"""CSV 管理器回归测试。

这些测试覆盖行情更新的文件写入边界，避免数据源已经返回可用 K 线时，
因为字段补全逻辑异常导致整只股票被记为更新失败。
"""

import pandas as pd

from utils.csv_manager import CSVManager


def test_update_stock_all_false_turnover_mask_does_not_raise(tmp_path):
    """无可估算换手率时应跳过赋值，不应让慢路径更新失败。"""
    csv_manager = CSVManager(tmp_path)
    stock_code = "002007"
    csv_manager.write_stock(
        stock_code,
        pd.DataFrame(
            [
                {
                    "date": "2026-05-19",
                    "open": 13.98,
                    "high": 14.08,
                    "low": 13.97,
                    "close": 14.07,
                    "volume": 6492818,
                    "amount": 91048390.0,
                    "turnover": 0.41,
                    "market_cap": 22135000000.0,
                }
            ]
        ),
    )

    csv_manager.update_stock(
        stock_code,
        pd.DataFrame(
            [
                {
                    "date": "2026-05-22",
                    "open": 13.92,
                    "high": 13.93,
                    "low": 13.77,
                    "close": 13.86,
                    "volume": 7704457,
                    "amount": 0.0,
                    "turnover": 0.0,
                    "market_cap": 0.0,
                }
            ]
        ),
    )

    refreshed = pd.read_csv(csv_manager.get_stock_path(stock_code), nrows=1)
    assert refreshed.iloc[0]["date"] == "2026-05-22"
    assert refreshed.iloc[0]["amount"] > 0
    assert refreshed.iloc[0]["turnover"] == 0
