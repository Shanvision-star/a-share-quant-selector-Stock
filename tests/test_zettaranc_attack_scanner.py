"""ZettarancAttackScanner 单元测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.csv_manager import CSVManager
from web.backend.services.zettaranc_attack_scanner import ZettarancAttackScanner


def _build_csv(tmp_dir: Path, code: str, df: pd.DataFrame) -> None:
    prefix = code[:2]
    sub = tmp_dir / prefix
    sub.mkdir(parents=True, exist_ok=True)
    df.to_csv(sub / f"{code}.csv", index=False)


def _attack_df(n: int = 160) -> pd.DataFrame:
    """构造能触发 zettaranc 规则的合成 K 线（倒序，最新在前）。"""
    import numpy as np
    rng = np.random.default_rng(1)
    base = np.linspace(20.0, 30.0, n)
    noise = rng.normal(0, 0.15, n)
    close = base + noise
    open_ = close - rng.uniform(0.05, 0.3, n)
    high = np.maximum(open_, close) + rng.uniform(0.05, 0.3, n)
    low = np.minimum(open_, close) - rng.uniform(0.05, 0.3, n)
    volume = rng.uniform(8_000_000, 12_000_000, n)
    dates = pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "date": dates, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume, "market_cap": [8e9] * n,
    })
    return df.iloc[::-1].reset_index(drop=True)


def test_scan_returns_list_and_does_not_crash(tmp_path: Path) -> None:
    _build_csv(tmp_path, "000001", _attack_df())
    (tmp_path / "stock_names.json").write_text(
        json.dumps({"000001": "测试一号"}), encoding="utf-8"
    )
    scanner = ZettarancAttackScanner(
        csv_manager=CSVManager(str(tmp_path)),
        data_dir=tmp_path,
    )
    result = scanner.scan_today()
    assert isinstance(result, list)
    # 不强制必出信号（合成数据噪声）；但结构必须健壮


def test_scan_skips_short_history(tmp_path: Path) -> None:
    short_df = _attack_df(n=30)
    _build_csv(tmp_path, "000002", short_df)
    scanner = ZettarancAttackScanner(
        csv_manager=CSVManager(str(tmp_path)),
        data_dir=tmp_path,
    )
    result = scanner.scan_today()
    assert result == []


def test_scan_with_explicit_pool(tmp_path: Path) -> None:
    _build_csv(tmp_path, "000001", _attack_df())
    _build_csv(tmp_path, "000002", _attack_df())
    scanner = ZettarancAttackScanner(
        csv_manager=CSVManager(str(tmp_path)),
        data_dir=tmp_path,
    )
    # 显式池子，limit 生效
    result = scanner.scan_today(pool=["000001", "000002"], limit=1)
    assert isinstance(result, list)


def test_scan_reads_recent_window_for_latest_attack_check(tmp_path: Path) -> None:
    class RecordingCsv:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def read_stock(self, code, **kwargs):
            self.calls.append({"code": code, **kwargs})
            return _attack_df()

    class PassiveStrategy:
        def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
            return df

        def select_stocks(self, df: pd.DataFrame, stock_name: str = "") -> list[dict]:
            return []

    csv = RecordingCsv()
    scanner = ZettarancAttackScanner(
        csv_manager=csv,
        strategy=PassiveStrategy(),
        data_dir=tmp_path,
    )

    scanner.scan_today(pool=["000001"], limit=1)

    assert csv.calls == [{"code": "000001", "nrows": 320}]


def test_scan_name_map_fallback_to_code(tmp_path: Path) -> None:
    _build_csv(tmp_path, "000001", _attack_df())
    # 无 stock_names.json，name 应当 fallback 到 code
    scanner = ZettarancAttackScanner(
        csv_manager=CSVManager(str(tmp_path)),
        data_dir=tmp_path,
    )
    result = scanner.scan_today()
    for c in result:
        assert c["name"] == c["code"]
