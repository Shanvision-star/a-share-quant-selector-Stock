"""
Zettaranc 攻击日扫描服务
==========================

提供「当下扫描」入口：对本地全市场或自定义池子，每只股票评估最新一根 K 线是否
命中 ``ZettarancComboStrategy`` 的入场规则；返回命中候选列表，供前端看板和钉钉
推送使用。

设计与离线回测脚本互补：
  * 离线回测：枚举历史 K 线，逐笔模拟成交 → 评估策略可行性。
  * 攻击扫描：只看「最新一根」 → 当天能不能进场。

性能：单次扫描 ~5000 只 CSV，预期 30~60 秒；提供 ``limit`` 参数便于前端先小池子
试一下。
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategy.zettaranc_combo import MIN_HISTORY, ZettarancComboStrategy  # noqa: E402
from utils.csv_manager import CSVManager  # noqa: E402


def list_local_codes(data_dir: Path) -> list[str]:
    codes: set[str] = set()
    for sub in data_dir.iterdir():
        if not sub.is_dir():
            continue
        for csv_path in sub.glob("*.csv"):
            stem = csv_path.stem
            if stem.isdigit() and len(stem) == 6:
                codes.add(stem)
    return sorted(codes)


@dataclass
class AttackCandidate:
    """单条攻击日候选。"""

    code: str
    name: str
    signal_date: str
    close: float
    stop_loss: float
    J: float
    bbi: float
    vol_ratio: float
    category: str
    extra: dict = field(default_factory=dict)


class ZettarancAttackScanner:
    """对本地股池跑「今天是不是攻击日」。

    实例化时可注入自定义 strategy（用于测试调阈值），默认使用线上 baseline。
    """

    def __init__(
        self,
        *,
        csv_manager: CSVManager | None = None,
        strategy: ZettarancComboStrategy | None = None,
        data_dir: Path | str | None = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else (ROOT / "data")
        self._csv = csv_manager or CSVManager(str(self._data_dir))
        self._strategy = strategy or ZettarancComboStrategy()

    def _load_name_map(self) -> dict[str, str]:
        """从 data/stock_names.json 读取代码→名称映射（缺失则返回空）。"""
        path = self._data_dir / "stock_names.json"
        if not path.exists():
            return {}
        try:
            import json
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                # raw 可能是 {code: name} 或 {code: {"name": ...}}
                out: dict[str, str] = {}
                for code, val in raw.items():
                    if isinstance(val, str):
                        out[str(code)] = val
                    elif isinstance(val, dict) and "name" in val:
                        out[str(code)] = str(val["name"])
                return out
        except (OSError, ValueError):
            pass
        return {}

    def scan_today(self, *, pool: list[str] | None = None, limit: int = 0) -> list[dict]:
        """扫描指定股池，返回今天命中入场规则的候选列表。

        ``pool`` 为空时扫本地全市场；``limit>0`` 时只取前 N 只（便于演示）。
        """
        codes = pool if pool else list_local_codes(self._data_dir)
        if limit > 0:
            codes = codes[:limit]

        name_map = self._load_name_map()
        candidates: list[AttackCandidate] = []
        for code in codes:
            df = self._csv.read_stock(code)
            if df.empty or len(df) < MIN_HISTORY or "date" not in df.columns:
                continue
            try:
                df = df.copy()
                df["date"] = df["date"].astype(str).str[:10]
                indicators = self._strategy.calculate_indicators(df)
                signals = self._strategy.select_stocks(indicators, name_map.get(code, ""))
            except Exception:  # noqa: BLE001
                continue
            if not signals:
                continue
            sig = signals[0]
            candidates.append(AttackCandidate(
                code=code,
                name=name_map.get(code, code),
                signal_date=str(sig.get("signal_date", "")),
                close=float(sig.get("close", 0)),
                stop_loss=float(sig.get("stop_loss", 0)),
                J=float(sig.get("J", 0)),
                bbi=float(sig.get("bbi", 0)),
                vol_ratio=float(sig.get("vol_ratio", 0)),
                category=str(sig.get("category", "")),
                extra={
                    "short_term_trend": sig.get("short_term_trend"),
                    "bull_bear_line": sig.get("bull_bear_line"),
                    "market_cap_yi": sig.get("market_cap_yi"),
                },
            ))
        # 按量比降序（最猛的攻击日排前）
        candidates.sort(key=lambda c: c.vol_ratio, reverse=True)
        return [asdict(c) for c in candidates]


_default_scanner: ZettarancAttackScanner | None = None


def get_default_scanner() -> ZettarancAttackScanner:
    global _default_scanner
    if _default_scanner is None:
        _default_scanner = ZettarancAttackScanner()
    return _default_scanner
