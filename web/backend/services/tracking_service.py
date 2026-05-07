"""单股跟踪服务。

tracking 模块保存“从今天开始跟踪”的状态和事件流；它可以生成
OrderIntent 建议，但不会连接券商，也不会真实下单。
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Callable
from uuid import uuid4

import pandas as pd

from web.backend.backtest_engine.models import OrderIntent, SignalCandidate
from web.backend.services.sqlite_service import get_connection


DailyLoader = Callable[[str], pd.DataFrame]


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _encode_json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _decode_json(value: Any, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _round_lot_quantity(quantity: int, lot_size: int = 100) -> int:
    if quantity <= 0 or lot_size <= 0:
        return max(0, quantity)
    return (quantity // lot_size) * lot_size


def _default_daily_loader(code: str) -> pd.DataFrame:
    from web.backend.services.backtest_service import _load_price_frame

    return _load_price_frame(code)


class TrackingService:
    """管理单股跟踪记录、事件流和每日评估。"""

    def __init__(
        self,
        connection_factory=get_connection,
        daily_loader: DailyLoader = _default_daily_loader,
    ):
        self.connection_factory = connection_factory
        self.daily_loader = daily_loader
        self._ensure_schema()

    def _conn(self):
        return self.connection_factory()

    def _ensure_schema(self):
        conn = self._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_items (
                tracking_id TEXT PRIMARY KEY,
                code TEXT NOT NULL,
                name TEXT,
                strategy_name TEXT,
                source TEXT,
                source_date TEXT,
                signal_date TEXT,
                status TEXT NOT NULL,
                entry_date TEXT,
                entry_price REAL,
                quantity INTEGER DEFAULT 0,
                remaining_pct REAL DEFAULT 100,
                last_eval_date TEXT,
                last_close REAL,
                latest_return_pct REAL DEFAULT 0,
                next_action TEXT,
                latest_intent_json TEXT,
                params_json TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                closed_at TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracking_items_code ON tracking_items(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracking_items_status ON tracking_items(status)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_id TEXT NOT NULL,
                event_date TEXT,
                event_type TEXT NOT NULL,
                action TEXT,
                message TEXT,
                payload_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tracking_events_tracking_id ON tracking_events(tracking_id)")
        conn.commit()

    def create_item(self, payload: dict) -> dict:
        tracking_id = f"trk_{uuid4().hex[:12]}"
        now = _now_text()
        params = dict(payload.get("params") or {})
        item = {
            "tracking_id": tracking_id,
            "code": str(payload.get("code") or "").strip(),
            "name": str(payload.get("name") or ""),
            "strategy_name": str(payload.get("strategy_name") or ""),
            "source": str(payload.get("source") or "manual"),
            "source_date": str(payload.get("source_date") or payload.get("trade_date") or ""),
            "signal_date": str(payload.get("signal_date") or payload.get("source_date") or ""),
            "status": "watch_buy",
            "entry_date": None,
            "entry_price": None,
            "quantity": 0,
            "remaining_pct": 100.0,
            "last_eval_date": None,
            "last_close": None,
            "latest_return_pct": 0.0,
            "next_action": "WAIT_BUY",
            "latest_intent": None,
            "params": params,
            "note": str(payload.get("note") or ""),
            "created_at": now,
            "updated_at": now,
            "closed_at": None,
        }
        if not item["code"] or not item["signal_date"]:
            raise ValueError("code 和 signal_date 不能为空")
        self._insert_item(item)
        self.add_event(
            tracking_id,
            "created",
            item["source_date"],
            "WAIT_BUY",
            "已加入单股跟踪",
            {"code": item["code"], "status": item["status"], "params": params},
        )
        return self.get_item(tracking_id)

    def list_items(self, status: str | None = None, code: str | None = None, limit: int = 100) -> list[dict]:
        where = []
        values: list[Any] = []
        if status and status != "all":
            where.append("status = ?")
            values.append(status)
        if code:
            where.append("code = ?")
            values.append(code)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn().execute(
            f"SELECT * FROM tracking_items {where_sql} ORDER BY updated_at DESC LIMIT ?",
            [*values, max(1, int(limit))],
        ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get_item(self, tracking_id: str) -> dict | None:
        row = self._conn().execute("SELECT * FROM tracking_items WHERE tracking_id = ?", (tracking_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def list_events(self, tracking_id: str, limit: int = 200) -> list[dict]:
        rows = self._conn().execute(
            """
            SELECT * FROM tracking_events
            WHERE tracking_id = ?
            ORDER BY event_id ASC
            LIMIT ?
            """,
            (tracking_id, max(1, int(limit))),
        ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["payload"] = _decode_json(item.pop("payload_json", None), {})
            events.append(item)
        return events

    def evaluate_item(self, tracking_id: str, eval_date: str | None = None) -> dict:
        item = self.get_item(tracking_id)
        if not item:
            raise KeyError(tracking_id)
        frame = self._price_frame(item["code"])
        if frame.empty:
            return self._record_no_data(item, eval_date)
        eval_row = self._resolve_eval_row(frame, eval_date)
        if eval_row is None:
            return self._record_no_data(item, eval_date)
        if item["status"] == "watch_buy":
            return self._evaluate_watch_buy(item, frame, eval_row)
        if item["status"] in {"holding", "partial_sold"}:
            return self._evaluate_holding(item, eval_row)
        return item

    def evaluate_items(self, eval_date: str | None = None) -> dict:
        items = [item for item in self.list_items(status="all", limit=1000) if item["status"] not in {"closed"}]
        evaluated = []
        for item in items:
            evaluated.append(self.evaluate_item(item["tracking_id"], eval_date))
        return {"total": len(items), "items": evaluated}

    def add_event(
        self,
        tracking_id: str,
        event_type: str,
        event_date: str | None,
        action: str,
        message: str,
        payload: dict | None = None,
    ):
        self._conn().execute(
            """
            INSERT INTO tracking_events
            (tracking_id, event_date, event_type, action, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tracking_id, event_date, event_type, action, message, _encode_json(payload or {}), _now_text()),
        )
        self._conn().commit()

    def _insert_item(self, item: dict):
        self._conn().execute(
            """
            INSERT INTO tracking_items
            (tracking_id, code, name, strategy_name, source, source_date, signal_date, status,
             entry_date, entry_price, quantity, remaining_pct, last_eval_date, last_close,
             latest_return_pct, next_action, latest_intent_json, params_json, note,
             created_at, updated_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["tracking_id"],
                item["code"],
                item["name"],
                item["strategy_name"],
                item["source"],
                item["source_date"],
                item["signal_date"],
                item["status"],
                item["entry_date"],
                item["entry_price"],
                item["quantity"],
                item["remaining_pct"],
                item["last_eval_date"],
                item["last_close"],
                item["latest_return_pct"],
                item["next_action"],
                _encode_json(item.get("latest_intent")) if item.get("latest_intent") else None,
                _encode_json(item.get("params") or {}),
                item["note"],
                item["created_at"],
                item["updated_at"],
                item["closed_at"],
            ),
        )
        self._conn().commit()

    def _update_item(self, tracking_id: str, **changes):
        if not changes:
            return
        mapping = {"params": "params_json", "latest_intent": "latest_intent_json"}
        columns = []
        values = []
        for key, value in changes.items():
            column = mapping.get(key, key)
            if column in {"params_json", "latest_intent_json"}:
                value = _encode_json(value) if value is not None else None
            columns.append(f"{column} = ?")
            values.append(value)
        columns.append("updated_at = ?")
        values.append(_now_text())
        values.append(tracking_id)
        self._conn().execute(f"UPDATE tracking_items SET {', '.join(columns)} WHERE tracking_id = ?", values)
        self._conn().commit()

    def _row_to_item(self, row) -> dict:
        item = dict(row)
        item["params"] = _decode_json(item.pop("params_json", None), {})
        item["latest_intent"] = _decode_json(item.pop("latest_intent_json", None), None)
        item["remaining_pct"] = _safe_float(item.get("remaining_pct"), 100.0)
        item["entry_price"] = None if item.get("entry_price") is None else _safe_float(item.get("entry_price"))
        item["last_close"] = None if item.get("last_close") is None else _safe_float(item.get("last_close"))
        item["latest_return_pct"] = _safe_float(item.get("latest_return_pct"), 0.0)
        item["quantity"] = _safe_int(item.get("quantity"), 0)
        return item

    def _price_frame(self, code: str) -> pd.DataFrame:
        frame = self.daily_loader(code)
        if frame is None or frame.empty:
            return pd.DataFrame()
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        for column in ("open", "high", "low", "close"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)

    def _resolve_eval_row(self, frame: pd.DataFrame, eval_date: str | None):
        if not eval_date:
            return frame.iloc[-1]
        matches = frame.index[frame["date"] <= pd.to_datetime(eval_date)]
        if len(matches) == 0:
            return None
        return frame.iloc[int(matches[-1])]

    def _buy_row(self, item: dict, frame: pd.DataFrame):
        signal_ts = pd.to_datetime(item["signal_date"])
        matches = frame.index[frame["date"] >= signal_ts]
        if len(matches) == 0:
            return None
        offset = max(0, _safe_int(item["params"].get("buy_offset_days"), 1))
        buy_index = int(matches[0]) + offset
        if buy_index >= len(frame):
            return None
        return frame.iloc[buy_index]

    def _candidate(self, item: dict) -> SignalCandidate:
        return SignalCandidate(
            code=item["code"],
            name=item.get("name") or "",
            strategy_name=item.get("strategy_name") or "",
            trade_date=item.get("source_date") or item.get("signal_date") or "",
            signal_date=item.get("signal_date") or "",
            source=item.get("source") or "tracking",
        )

    def _evaluate_watch_buy(self, item: dict, frame: pd.DataFrame, eval_row) -> dict:
        buy_row = self._buy_row(item, frame)
        eval_date = eval_row["date"].strftime("%Y-%m-%d")
        if buy_row is None or buy_row["date"] > eval_row["date"]:
            self._update_item(
                item["tracking_id"],
                last_eval_date=eval_date,
                last_close=_safe_float(eval_row.get("close")),
                next_action="WAIT_BUY",
                latest_return_pct=0.0,
            )
            self.add_event(item["tracking_id"], "evaluated", eval_date, "WAIT_BUY", "未到买入交易日", {})
            return self.get_item(item["tracking_id"])

        buy_price_field = str(item["params"].get("buy_price", "open"))
        buy_price = _safe_float(buy_row.get(buy_price_field), 0.0)
        quantity = _round_lot_quantity(
            _safe_int(item["params"].get("intent_quantity"), 0),
            max(1, _safe_int(item["params"].get("lot_size"), 100)),
        )
        intent = OrderIntent.from_candidate(
            self._candidate(item),
            side="BUY",
            planned_at=buy_row["date"],
            price_type=buy_price_field,
            target_price=buy_price,
            quantity=quantity,
        ).to_mapping()
        buy_date = buy_row["date"].strftime("%Y-%m-%d")
        self._update_item(
            item["tracking_id"],
            status="holding",
            entry_date=buy_date,
            entry_price=round(buy_price, 3),
            quantity=quantity,
            remaining_pct=100.0,
            last_eval_date=eval_date,
            last_close=_safe_float(eval_row.get("close")),
            latest_return_pct=0.0,
            next_action="BUY",
            latest_intent=intent,
        )
        self.add_event(
            item["tracking_id"],
            "buy_signal",
            buy_date,
            "BUY",
            "到达买入交易日，生成买入意图",
            {"intent": intent},
        )
        return self.get_item(item["tracking_id"])

    def _evaluate_holding(self, item: dict, eval_row) -> dict:
        eval_date = eval_row["date"].strftime("%Y-%m-%d")
        close_price = _safe_float(eval_row.get("close"), 0.0)
        entry_price = _safe_float(item.get("entry_price"), 0.0)
        return_pct = (close_price / entry_price - 1) * 100 if entry_price > 0 and close_price > 0 else 0.0
        params = item.get("params") or {}
        trigger_pct = _safe_float(params.get("profit_trigger_pct"), 5.0)
        sell_pct = max(0.0, min(100.0, _safe_float(params.get("profit_sell_pct"), 25.0)))
        keep_pct = max(0.0, min(100.0, _safe_float(params.get("profit_keep_pct"), 0.0)))
        remaining_pct = _safe_float(item.get("remaining_pct"), 100.0)

        if bool(params.get("profit_run_enabled", True)) and return_pct >= trigger_pct and remaining_pct > keep_pct:
            portion = min(sell_pct, max(0.0, remaining_pct - keep_pct))
            next_remaining = round(max(0.0, remaining_pct - portion), 2)
            intent = OrderIntent.from_candidate(
                self._candidate(item),
                side="SELL",
                planned_at=eval_row["date"],
                price_type="close",
                target_price=close_price,
                quantity=_round_lot_quantity(int(_safe_int(item.get("quantity"), 0) * (portion / 100)), 100),
            ).to_mapping()
            self._update_item(
                item["tracking_id"],
                status="partial_sold" if next_remaining > 0 else "closed",
                remaining_pct=next_remaining,
                last_eval_date=eval_date,
                last_close=close_price,
                latest_return_pct=round(return_pct, 2),
                next_action="SELL_PARTIAL",
                latest_intent=intent,
                closed_at=eval_date if next_remaining <= 0 else None,
            )
            self.add_event(
                item["tracking_id"],
                "profit_take",
                eval_date,
                "SELL_PARTIAL",
                "达到放飞阈值，生成部分卖出建议",
                {"intent": intent, "sell_pct": portion, "remaining_pct": next_remaining},
            )
            return self.get_item(item["tracking_id"])

        self._update_item(
            item["tracking_id"],
            last_eval_date=eval_date,
            last_close=close_price,
            latest_return_pct=round(return_pct, 2),
            next_action="HOLD",
            latest_intent=None,
        )
        self.add_event(item["tracking_id"], "evaluated", eval_date, "HOLD", "继续持有", {"return_pct": round(return_pct, 2)})
        return self.get_item(item["tracking_id"])

    def _record_no_data(self, item: dict, eval_date: str | None) -> dict:
        event_date = eval_date or datetime.now().strftime("%Y-%m-%d")
        self._update_item(item["tracking_id"], last_eval_date=event_date, next_action="NO_DATA")
        self.add_event(item["tracking_id"], "no_data", event_date, "NO_DATA", "未找到可评估行情", {})
        return self.get_item(item["tracking_id"])


tracking_service = TrackingService()
