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


def test_update_stock_drops_malformed_existing_date_rows(tmp_path):
    """历史 CSV 中混入坏日期行时，应清洗坏行后继续合并，不能让整只股票更新失败。"""
    csv_manager = CSVManager(tmp_path)
    stock_code = "000838"
    path = csv_manager.get_stock_path(stock_code)
    path.write_text(
        "\n".join(
            [
                "date,open,high,low,close,volume,amount,turnover,market_cap",
                "2026-04-28,1.89,1.89,1.84,1.89,58149971,0,0,2035855014.5",
                "001,295.25715717414613,2035855014.5",
                "2026-04-27,1.73,1.8,1.62,1.8,109565409,0,0,2035855014.5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    csv_manager.update_stock(
        stock_code,
        pd.DataFrame(
            [
                {
                    "date": "2026-05-22",
                    "open": 1.95,
                    "high": 2.01,
                    "low": 1.9,
                    "close": 1.99,
                    "volume": 1000,
                    "amount": 199000.0,
                    "turnover": 0.1,
                    "market_cap": 2035855014.5,
                }
            ]
        ),
    )

    refreshed = pd.read_csv(path)
    assert refreshed.iloc[0]["date"] == "2026-05-22"
    assert "001" not in refreshed["date"].astype(str).tolist()
    assert pd.to_datetime(refreshed["date"], errors="coerce").notna().all()
