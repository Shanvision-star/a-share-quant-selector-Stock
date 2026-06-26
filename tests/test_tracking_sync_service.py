"""收盘同步服务测试：行情写入必须落到项目 data 目录边界内。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


class _FakeFetcher:
    """替代外部行情源，保留 fetch_stock_update 的真实调用形状。"""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)

    def fetch_stock_update(self, code: str, days: int = 30) -> pd.DataFrame:
        assert code == "000001"
        assert days == 7
        return pd.DataFrame(
            [
                {
                    "date": "2026-06-25",
                    "open": 10.0,
                    "high": 10.8,
                    "low": 9.8,
                    "close": 10.5,
                    "volume": 1000000,
                }
            ]
        )


def test_fetch_and_update_single_writes_to_configured_data_dir(tmp_path) -> None:
    from web.backend.services.tracking_sync_service import _fetch_and_update_single

    result = _fetch_and_update_single(
        "000001",
        days=7,
        data_dir=tmp_path,
        fetcher_factory=_FakeFetcher,
    )

    assert result == "ok"
    csv_path = tmp_path / "00" / "000001.csv"
    assert csv_path.exists()
    written = pd.read_csv(csv_path)
    assert written.iloc[0]["date"] == "2026-06-25"
