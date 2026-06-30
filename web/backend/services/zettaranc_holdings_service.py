"""
Zettaranc 持仓纪律服务
=======================

目标：把 zettaranc-skill 「持仓即纪律」的核心约束落成可查可推的接口：
  1) 持仓 CRUD（JSON 文件持久化，data/zettaranc_holdings.json）
  2) 纪律巡检：
     * 跌破入场低点（X1 止损）
     * 累计涨幅 ≥ take_profit_pct（X4 止盈提示，默认 15%）
     * 持仓天数 ≥ hold_days_limit（X3 时间止损提示，默认 20）
     * 单票实际仓位 > max_position_pct（违反组合上限，默认 10%）
  3) 钉钉推送钩子（可选；测试中不会真正调用）

为什么不复用 tracking_service：tracking 已是「策略候选 → LLM → 告警」完整工作流，
zettaranc 持仓只关心人工录入的实际持仓与硬性纪律告警；独立 JSON 文件 + 独立服务
可零回归对待 tracking 现有 18 项测试与缓存语义。
"""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.csv_manager import CSVManager  # noqa: E402


DEFAULT_HOLDINGS_PATH = ROOT / "data" / "zettaranc_holdings.json"


@dataclass
class Holding:
    """单条 zettaranc 持仓记录。"""

    code: str
    name: str
    entry_date: str            # YYYY-MM-DD
    entry_price: float
    qty: int                   # 持股数量
    stop_loss: float           # 硬止损价（一般 = 入场日最低）
    take_profit_pct: float = 15.0
    hold_days_limit: int = 20
    max_position_pct: float = 10.0    # 单票最大仓位占比
    total_capital: float = 1_000_000.0  # 用于换算单票仓位占比
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class HoldingAlert:
    """单条纪律告警。"""

    code: str
    name: str
    rule: str          # stop_loss / take_profit / time_stop / position_overflow / missing_data
    severity: str      # critical / warn / info
    message: str
    extra: dict = field(default_factory=dict)


class ZettarancHoldingsService:
    """JSON 文件持久化的持仓与纪律服务（线程安全）。"""

    def __init__(
        self,
        storage_path: Path | str | None = None,
        *,
        csv_manager: CSVManager | None = None,
    ) -> None:
        self.storage_path = Path(storage_path) if storage_path else DEFAULT_HOLDINGS_PATH
        self._lock = threading.Lock()
        self._csv = csv_manager or CSVManager(str(ROOT / "data"))
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.storage_path.exists():
            self.storage_path.write_text("[]", encoding="utf-8")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def _read_raw(self) -> list[dict]:
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write_raw(self, items: list[dict]) -> None:
        # 临时文件 + 原子替换，避免写到一半被读到坏 JSON
        tmp = self.storage_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.storage_path)

    def list_holdings(self) -> list[dict]:
        return self._read_raw()

    def add_holding(self, holding: Holding | dict) -> dict:
        if isinstance(holding, dict):
            holding = Holding(**holding)
        with self._lock:
            items = self._read_raw()
            # 同一 code 视为更新（人工录入场景下不允许重复）
            items = [it for it in items if it.get("code") != holding.code]
            items.append(asdict(holding))
            self._write_raw(items)
            return asdict(holding)

    def update_holding(self, code: str, patch: dict) -> dict | None:
        with self._lock:
            items = self._read_raw()
            for it in items:
                if it.get("code") == code:
                    it.update({k: v for k, v in patch.items() if k != "code"})
                    self._write_raw(items)
                    return it
            return None

    def delete_holding(self, code: str) -> bool:
        with self._lock:
            items = self._read_raw()
            new_items = [it for it in items if it.get("code") != code]
            if len(new_items) == len(items):
                return False
            self._write_raw(new_items)
            return True

    # ------------------------------------------------------------------
    # 纪律巡检
    # ------------------------------------------------------------------
    def _latest_close(self, code: str) -> float | None:
        """读取该股最新收盘价（CSV 倒序，iloc[0]）。"""
        df = self._csv.read_stock(code, nrows=1)
        if df.empty or "close" not in df.columns:
            return None
        try:
            return float(df.iloc[0]["close"])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _days_between(entry_date: str, today: str | None = None) -> int:
        try:
            d1 = datetime.strptime(entry_date[:10], "%Y-%m-%d")
            d2 = datetime.strptime(today, "%Y-%m-%d") if today else datetime.now()
            return max(0, (d2 - d1).days)
        except (ValueError, TypeError):
            return 0

    def check_stop_alerts(self, today: str | None = None) -> list[dict]:
        """对所有持仓做一次纪律巡检，返回告警 dict 列表。

        ``today`` 仅供测试注入；默认用系统当前日期。
        告警顺序：critical 在前，warn 次之，info 最后；同级按代码升序。
        """
        alerts: list[HoldingAlert] = []
        for it in self._read_raw():
            code = str(it.get("code", ""))
            name = str(it.get("name", ""))
            close = self._latest_close(code)
            if close is None:
                alerts.append(HoldingAlert(
                    code=code, name=name, rule="missing_data", severity="warn",
                    message=f"{code} 缺少本地行情数据，无法巡检",
                ))
                continue

            stop_loss = float(it.get("stop_loss", 0) or 0)
            entry_price = float(it.get("entry_price", 0) or 0)
            tp_pct = float(it.get("take_profit_pct", 15.0))
            hold_limit = int(it.get("hold_days_limit", 20))
            max_pos = float(it.get("max_position_pct", 10.0))
            qty = int(it.get("qty", 0) or 0)
            total_cap = float(it.get("total_capital", 1_000_000.0) or 1.0)
            entry_date = str(it.get("entry_date", ""))

            # X1 跌破止损
            if stop_loss > 0 and close < stop_loss:
                alerts.append(HoldingAlert(
                    code=code, name=name, rule="stop_loss", severity="critical",
                    message=f"{code} 现价 {close:.2f} 已跌破止损 {stop_loss:.2f}，立即清仓",
                    extra={"close": close, "stop_loss": stop_loss},
                ))

            # X4 触及止盈
            if entry_price > 0:
                gain_pct = (close - entry_price) / entry_price * 100.0
                if gain_pct >= tp_pct:
                    alerts.append(HoldingAlert(
                        code=code, name=name, rule="take_profit", severity="warn",
                        message=f"{code} 浮盈 {gain_pct:.2f}% 触发止盈线 {tp_pct:.1f}%，按纪律减仓",
                        extra={"close": close, "entry_price": entry_price, "gain_pct": round(gain_pct, 2)},
                    ))

            # X3 时间止损
            held = self._days_between(entry_date, today)
            if entry_date and held >= hold_limit:
                alerts.append(HoldingAlert(
                    code=code, name=name, rule="time_stop", severity="warn",
                    message=f"{code} 持仓 {held} 日已达上限 {hold_limit}，建议主动了结",
                    extra={"held_days": held, "limit": hold_limit},
                ))

            # 仓位上限
            if qty > 0 and entry_price > 0 and total_cap > 0:
                pos_pct = qty * close / total_cap * 100.0
                if pos_pct > max_pos:
                    alerts.append(HoldingAlert(
                        code=code, name=name, rule="position_overflow", severity="warn",
                        message=f"{code} 当前仓位 {pos_pct:.2f}% 超过上限 {max_pos:.1f}%",
                        extra={"position_pct": round(pos_pct, 2), "limit": max_pos},
                    ))

        # 排序：critical → warn → info
        severity_rank = {"critical": 0, "warn": 1, "info": 2}
        alerts.sort(key=lambda a: (severity_rank.get(a.severity, 9), a.code))
        return [asdict(a) for a in alerts]


# 模块级单例（路由层共享一份）
_default_service: ZettarancHoldingsService | None = None


def get_default_service() -> ZettarancHoldingsService:
    global _default_service
    if _default_service is None:
        _default_service = ZettarancHoldingsService()
    return _default_service
