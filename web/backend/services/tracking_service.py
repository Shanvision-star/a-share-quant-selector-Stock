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


# P5：评估服务的模块级占位，供 batch_from_selection 自动级联使用，也便于测试 monkeypatch。
# 真正的单例延迟在调用点 import，避免与 tracking_evaluation_service 形成循环导入。
tracking_evaluation_service = None


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
        # 关键改动：name 为空时自动按 code 查询 stock_names.json，
        # 避免批量导入 / 路由调用方忘传 name 时落库一直为空。
        # 这样做的好处：列表展示、推送、报表都能立刻拿到中文名。
        raw_code = str(payload.get("code") or "").strip()
        raw_name = str(payload.get("name") or "").strip()
        if not raw_name and raw_code:
            try:
                from web.backend.services.kline_service import get_stock_name

                resolved = get_stock_name(raw_code)
                # get_stock_name 找不到时返回 "未知"，仍然落库以保留占位
                raw_name = resolved or ""
            except Exception:
                raw_name = ""
        item = {
            "tracking_id": tracking_id,
            "code": raw_code,
            "name": raw_name,
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
        # 关键改动：
        # 1) 列表内对历史无 name 的行做"懒回填"——查 stock_names.json 拿名后
        #    UPDATE 落库；只对真空或 "未知" 的行处理，避免污染用户手填名。
        # 2) 用单次 _frame_cache 共享 CSV 加载，给 _row_to_item 计算 tracked_trading_days
        #    服用同一个 DataFrame，避免每行重读 CSV。
        try:
            from web.backend.services.kline_service import get_stock_name
        except Exception:
            get_stock_name = None  # type: ignore

        frame_cache: dict[str, pd.DataFrame] = {}
        items: list[dict] = []
        names_to_backfill: list[tuple[str, str]] = []  # (tracking_id, name)
        for row in rows:
            item = self._row_to_item(row, frame_cache=frame_cache)
            current_name = (item.get("name") or "").strip()
            if get_stock_name and item.get("code") and current_name in ("", "未知"):
                try:
                    resolved = get_stock_name(item["code"])
                    if resolved and resolved != current_name:
                        item["name"] = resolved
                        # 只有真名才回写，"未知" 不污染；下次仍会重试
                        if resolved != "未知":
                            names_to_backfill.append((item["tracking_id"], resolved))
                except Exception:
                    pass
            items.append(item)

        # 在循环外批量提交回填，避免多次 commit IO
        if names_to_backfill:
            conn = self._conn()
            now = _now_text()
            conn.executemany(
                "UPDATE tracking_items SET name = ?, updated_at = ? WHERE tracking_id = ?",
                [(name, now, tid) for tid, name in names_to_backfill],
            )
            conn.commit()
        return items

    # ---------- P-D: 单条与批量删除 ----------
    # 关键边界：
    # 1. tracking_events 通过 tracking_id 关联，删除主记录时必须级联清空事件，
    #    否则会留下孤儿事件流，影响后续审计；
    # 2. 不存在的 tracking_id 不抛错，返回 False / 写入 not_found，便于前端批量场景。
    def delete_item(self, tracking_id: str) -> bool:
        """删除单条跟踪记录及其事件流。

        Returns:
            True 表示已删除；False 表示记录不存在。
        """
        conn = self._conn()
        row = conn.execute(
            "SELECT tracking_id FROM tracking_items WHERE tracking_id = ?",
            (tracking_id,),
        ).fetchone()
        if not row:
            return False
        # 关键路径：先删事件再删主记录，事务内保证一致性
        conn.execute("DELETE FROM tracking_events WHERE tracking_id = ?", (tracking_id,))
        conn.execute("DELETE FROM tracking_items WHERE tracking_id = ?", (tracking_id,))
        conn.commit()
        return True

    def batch_delete(self, tracking_ids: list[str]) -> dict:
        """批量删除跟踪记录。

        Returns:
            {"deleted": [...], "not_found": [...]}，已去重，前端可直接展示
        """
        deleted: list[str] = []
        not_found: list[str] = []
        # 去重避免同一 id 重复处理；保持入参顺序方便前端定位
        seen: set[str] = set()
        for tid in tracking_ids:
            tid = str(tid or "").strip()
            if not tid or tid in seen:
                continue
            seen.add(tid)
            if self.delete_item(tid):
                deleted.append(tid)
            else:
                not_found.append(tid)
        return {"deleted": deleted, "not_found": not_found}

    # ---------- P-D: 批量代码导入（TXT/粘贴） ----------
    # 关键边界：
    # 1. 输入代码可能来自 TXT 文件或剪贴板，按行 + 逗号 + 空白分割再清洗；
    # 2. 仅保留 6 位纯数字代码，其余进入 failed；
    # 3. 已有活跃跟踪记录的代码进入 skipped，避免重复跟踪；
    # 4. 创建成功后立即评估一次：将 watch_buy 推进到 holding，落 entry_price 与
    #    latest_return_pct，解决前端"看不到买入点/跟踪收益"的问题。
    _CODE_PATTERN = __import__("re").compile(r"^\d{6}$")

    @classmethod
    def parse_codes(cls, text: str) -> tuple[list[str], list[str]]:
        """从粗放文本中解析股票代码列表。

        Returns:
            (valid_codes, invalid_tokens)，valid_codes 已去重保序
        """
        import re as _re

        if not text:
            return [], []
        # 按换行/逗号/分号/空白统一切分
        tokens = [t.strip() for t in _re.split(r"[\s,;，；]+", text) if t.strip()]
        valid: list[str] = []
        invalid: list[str] = []
        seen: set[str] = set()
        for tok in tokens:
            # 兼容 "sh600000" / "SZ000001" / "600000.SH" 这类前后缀写法
            digits = _re.sub(r"\D", "", tok)
            if len(digits) == 6 and cls._CODE_PATTERN.match(digits):
                if digits not in seen:
                    seen.add(digits)
                    valid.append(digits)
            else:
                invalid.append(tok)
        return valid, invalid

    def batch_create_codes(
        self,
        codes: list[str],
        signal_date: str | None = None,
        strategy_name: str = "manual_batch",
        source: str = "manual_batch",
        evaluate_now: bool = True,
    ) -> dict:
        """批量创建跟踪记录（来源：TXT/粘贴）。

        Args:
            codes: 已分词的代码列表，由路由层调用 parse_codes 解析
            signal_date: 信号日；缺省取今天，作为 watch_buy 的起点
            strategy_name: 标签，便于前端区分批量导入
            evaluate_now: 是否在创建后立即评估，把 entry_price/latest_return_pct
                          填充出来；测试可关掉避免依赖行情数据

        Returns:
            {"created": [..tracking_id..], "skipped": [{code, reason}], "failed": [{code, reason}]}
        """
        signal_date = signal_date or datetime.now().strftime("%Y-%m-%d")

        # 一次取出活跃代码，避免循环里 N 次 SELECT
        placeholders = ",".join(["?"] * len(self._ACTIVE_TRACKING_STATUS))
        active_rows = self._conn().execute(
            f"SELECT code FROM tracking_items WHERE status IN ({placeholders})",
            self._ACTIVE_TRACKING_STATUS,
        ).fetchall()
        active_codes = {row["code"] for row in active_rows}

        created: list[dict] = []
        skipped: list[dict] = []
        failed: list[dict] = []
        seen: set[str] = set()
        for code in codes:
            code = str(code or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            if not self._CODE_PATTERN.match(code):
                failed.append({"code": code, "reason": "格式非法（需 6 位数字）"})
                continue
            if code in active_codes:
                skipped.append({"code": code, "reason": "已存在活跃跟踪记录"})
                continue
            try:
                item = self.create_item(
                    {
                        "code": code,
                        "name": "",
                        "strategy_name": strategy_name,
                        "source": source,
                        "source_date": signal_date,
                        "signal_date": signal_date,
                    }
                )
                # 立即评估：尝试把 watch_buy → holding，让前端能看到 entry_price 与
                # 当前收益；evaluate 失败（无行情等）不阻塞本次导入
                if evaluate_now:
                    try:
                        item = self.evaluate_item(item["tracking_id"]) or item
                    except Exception:
                        pass
                created.append(item)
                active_codes.add(code)
            except (ValueError, KeyError) as exc:
                failed.append({"code": code, "reason": str(exc)})
        return {"created": created, "skipped": skipped, "failed": failed}

    # ---------- P1: 从人工选股池批量加入跟踪 ----------
    # 关键边界：
    # 1. 复用 create_item，不再单独写 INSERT；保证 tracking_events 自动落 "created" 事件
    # 2. 同 code 已存在 watch_buy / holding / partial_sold 的活跃记录 → 跳过，
    #    避免一只股票在跟踪表里出现多条互相干扰的记录
    # 3. 单条失败（如代码非法）不影响其他条；统一收集到 failed 列表
    _ACTIVE_TRACKING_STATUS = ("watch_buy", "holding", "partial_sold")

    def batch_from_selection(
        self,
        selection_date: str,
        codes: list[str] | None = None,
    ) -> dict:
        """从 manual_selections 批量创建 tracking_items。

        Args:
            selection_date: 人工选股池的入池日期
            codes: 可选；若提供，则仅导入指定代码（前端勾选场景）。
                   未在 selection 中的 code 进入 failed 列表
        Returns:
            {"created": int, "skipped": int, "skipped_codes": list[str], "failed": list[str]}
        """
        # 延迟导入以避免循环依赖：manual_selection_service 在测试中会被 monkeypatch
        from web.backend.services import manual_selection_service

        selections = manual_selection_service.list_selections(selection_date=selection_date)
        selection_by_code = {row["code"]: row for row in selections}

        if codes is None:
            target_codes = list(selection_by_code.keys())
            failed: list[str] = []
        else:
            target_codes = []
            failed = []
            for code in codes:
                if code in selection_by_code:
                    target_codes.append(code)
                else:
                    # 前端勾选了未入池的代码 → 提示前端，不静默丢弃
                    failed.append(code)

        # 一次性查出所有"活跃"跟踪记录的 code，避免循环里逐条 SELECT
        active_rows = self._conn().execute(
            f"SELECT code FROM tracking_items WHERE status IN ({','.join(['?'] * len(self._ACTIVE_TRACKING_STATUS))})",
            self._ACTIVE_TRACKING_STATUS,
        ).fetchall()
        active_codes = {row["code"] for row in active_rows}

        created = 0
        skipped_codes: list[str] = []
        for code in target_codes:
            if code in active_codes:
                skipped_codes.append(code)
                continue
            row = selection_by_code[code]
            try:
                self.create_item(
                    {
                        "code": code,
                        "name": row.get("name") or "",
                        "strategy_name": row.get("strategy_name") or "",
                        # source 标记为 manual_selection，区别于 backtest 入口，便于回溯
                        "source": "manual_selection",
                        "source_date": row.get("source_trade_date") or selection_date,
                        "signal_date": row.get("source_signal_date") or selection_date,
                    }
                )
                created += 1
            except (ValueError, KeyError):
                # 单条失败不阻塞其他条；记入 failed
                failed.append(code)

        result = {
            "created": created,
            "skipped": len(skipped_codes),
            "skipped_codes": skipped_codes,
            "failed": failed,
        }

        # P5：自动级联开关（默认 OFF）。开启后立即对本批新增的代码做一次规则评估。
        # 单独捕获异常：评估失败不应回滚导入结果。
        try:
            from web.backend.services.sqlite_service import get_app_meta

            cascade_flag = (get_app_meta("tracking_auto_cascade", "off") or "off").lower()
        except Exception:
            cascade_flag = "off"

        if cascade_flag in ("on", "1", "true", "yes") and created > 0:
            try:
                svc = tracking_evaluation_service
                if svc is None:
                    from web.backend.services.tracking_evaluation_service import (
                        tracking_evaluation_service as svc,  # type: ignore
                    )
                only = [
                    code for code in target_codes if code not in skipped_codes and code not in failed
                ]
                result["evaluation"] = svc.evaluate_active_items(only_codes=only)
            except Exception as exc:  # 评估异常仅记录，避免吞掉导入结果
                result["evaluation_error"] = str(exc)

        return result

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

    def evaluate_item(self, tracking_id: str, eval_date: str | None = None, force: bool = False) -> dict:
        """评估单条跟踪记录。

        force=True 时打破"同日不重算"短路（_evaluate_holding 当 last_eval_date == eval_date 默认直接返回）。
        收盘同步、手动改买入价等需要强制重算的场景必须传 force=True。
        """
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
            return self._evaluate_holding(item, eval_row, force=force)
        return item

    def evaluate_items(self, eval_date: str | None = None, force: bool = False) -> dict:
        """批量评估未结束跟踪。force 透传给 evaluate_item，用于收盘同步等强制重算路径。"""
        items = [item for item in self.list_items(status="all", limit=1000) if item["status"] not in {"closed"}]
        evaluated = []
        for item in items:
            evaluated.append(self.evaluate_item(item["tracking_id"], eval_date, force=force))
        return {"total": len(items), "items": evaluated}

    def update_entry_price(
        self,
        tracking_id: str,
        entry_price: float,
        entry_date: str | None = None,
        quantity: int | None = None,
        eval_date: str | None = None,
    ) -> dict:
        """手动修正买入价并立即强制重算收益率。

        使用场景：实际成交价与系统假设的开盘/收盘价不符，操盘手需要把真实成交价回填到跟踪记录，
        以便 latest_return_pct/last_close 反映真实盈亏。

        约束：
        - 仅允许在 holding / partial_sold 状态下修改 entry_price，避免污染 watch_buy 的入场计算；
        - entry_price 必须 > 0，否则 ValueError；
        - 修改完毕走 evaluate_item(force=True)，绕过 _evaluate_holding 同日短路；
        - 写一条 entry_price_edited 事件，留下审计痕迹。
        """
        item = self.get_item(tracking_id)
        if not item:
            raise KeyError(tracking_id)
        if item["status"] not in {"holding", "partial_sold"}:
            raise ValueError(f"仅 holding/partial_sold 可修改买入价，当前状态 {item['status']}")
        price = _safe_float(entry_price, 0.0)
        if price <= 0:
            raise ValueError("entry_price 必须大于 0")

        changes: dict = {"entry_price": round(price, 3)}
        if entry_date:
            changes["entry_date"] = entry_date
        if quantity is not None:
            changes["quantity"] = max(0, int(quantity))
        self._update_item(tracking_id, **changes)
        # 写审计事件：记录旧值/新值，便于回溯
        self.add_event(
            tracking_id,
            event_type="entry_price_edited",
            event_date=entry_date or item.get("entry_date") or item.get("last_eval_date"),
            action="EDIT",
            message="手动调整买入价",
            payload={
                "old_entry_price": item.get("entry_price"),
                "new_entry_price": round(price, 3),
                "old_entry_date": item.get("entry_date"),
                "new_entry_date": entry_date or item.get("entry_date"),
                "old_quantity": item.get("quantity"),
                "new_quantity": changes.get("quantity", item.get("quantity")),
            },
        )
        # 强制重算 latest_return_pct，避免被同日短路卡住
        return self.evaluate_item(tracking_id, eval_date, force=True)

    def confirm_intent(self, tracking_id: str, intent: dict | None = None) -> dict:
        """确认 LLM/系统建议的 OrderIntent：只落事件，不接入真实交易。

        - 未知 tracking_id 抛 KeyError，避免 404 路径误命中数据库 None；
        - 传入 intent 覆盖现有 latest_intent，便于前端编辑确认；
        - action 字段使用 intent.side 作为审计语义，默认 CONFIRM。
        """
        item = self.get_item(tracking_id)
        if not item:
            raise KeyError(tracking_id)
        effective_intent = intent if intent is not None else item.get("latest_intent") or {}
        action = str(effective_intent.get("side") or "CONFIRM").upper()
        self.add_event(
            tracking_id,
            event_type="intent_confirmed",
            event_date=item.get("last_eval_date"),
            action=action,
            message="操盘手确认 OrderIntent",
            payload={"intent": effective_intent},
        )
        if intent is not None:
            self._update_item(tracking_id, latest_intent=effective_intent)
        return self.get_item(tracking_id) or item

    def reject_intent(self, tracking_id: str, reason: str = "") -> dict:
        """否决建议：写入 intent_rejected 事件，next_action 回落到 HOLD。

        - 未知 tracking_id 抛 KeyError；
        - reason 落入 payload，方便复盘“为什么不下单”；
        - 不清空 latest_intent，留作历史证据。
        """
        item = self.get_item(tracking_id)
        if not item:
            raise KeyError(tracking_id)
        self.add_event(
            tracking_id,
            event_type="intent_rejected",
            event_date=item.get("last_eval_date"),
            action="HOLD",
            message="操盘手否决 OrderIntent",
            payload={"reason": reason},
        )
        self._update_item(tracking_id, next_action="HOLD")
        return self.get_item(tracking_id) or item

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

    def _row_to_item(self, row, frame_cache: dict | None = None) -> dict:
        item = dict(row)
        item["params"] = _decode_json(item.pop("params_json", None), {})
        item["latest_intent"] = _decode_json(item.pop("latest_intent_json", None), None)
        item["remaining_pct"] = _safe_float(item.get("remaining_pct"), 100.0)
        item["entry_price"] = None if item.get("entry_price") is None else _safe_float(item.get("entry_price"))
        item["last_close"] = None if item.get("last_close") is None else _safe_float(item.get("last_close"))
        item["latest_return_pct"] = _safe_float(item.get("latest_return_pct"), 0.0)
        item["quantity"] = _safe_int(item.get("quantity"), 0)
        # 派生字段：跟踪交易日数（业务含义=策略实际持有/观察了多少根 K 线）
        # 起点优先取 entry_date（真正买入），其次 signal_date（仍在 watch_buy 时）
        # 终点优先取 last_eval_date（最近一次评估），其次今天
        # 计入起点当日；用 CSV 自带的交易日历，不必另查日历表
        item["tracked_trading_days"] = self._compute_tracked_days(item, frame_cache)
        return item

    def _compute_tracked_days(self, item: dict, frame_cache: dict | None = None) -> int:
        """统计跟踪期间穿越的交易日数。

        关键边界：
        - CSV 缺失或没数据时返回 0，不抛错；
        - start 取 entry_date ?: signal_date；为空则返回 0；
        - end 取 last_eval_date ?: 今天；
        - 调用方传 frame_cache 时复用同一 DataFrame，避免列表场景 N 次 IO。
        """
        code = (item.get("code") or "").strip()
        if not code:
            return 0
        start_str = item.get("entry_date") or item.get("signal_date") or ""
        if not start_str:
            return 0
        end_str = item.get("last_eval_date") or datetime.now().strftime("%Y-%m-%d")
        try:
            start_ts = pd.to_datetime(start_str)
            end_ts = pd.to_datetime(end_str)
        except Exception:
            return 0
        if end_ts < start_ts:
            return 0
        try:
            if frame_cache is not None and code in frame_cache:
                frame = frame_cache[code]
            else:
                frame = self._price_frame(code)
                if frame_cache is not None:
                    frame_cache[code] = frame
            if frame is None or frame.empty:
                return 0
            mask = (frame["date"] >= start_ts) & (frame["date"] <= end_ts)
            return int(mask.sum())
        except Exception:
            return 0

    # ---------- 信号日收盘价查询（用于单股添加表单默认买入价） ----------
    def get_signal_close(self, code: str, signal_date: str) -> dict:
        """返回指定 code 在 signal_date（或之前最近交易日）的收盘价。

        Returns:
            {"code", "name", "signal_date", "matched_date", "close"}
            close 可能为 None（CSV 不存在或日期早于首条记录）
        Raises:
            ValueError: 当 signal_date 解析失败
        """
        code = str(code or "").strip()
        if not code:
            raise ValueError("code 不能为空")
        try:
            target_ts = pd.to_datetime(signal_date)
        except Exception as exc:
            raise ValueError(f"signal_date 非法: {signal_date}") from exc
        try:
            from web.backend.services.kline_service import get_stock_name

            name = get_stock_name(code) or "未知"
        except Exception:
            name = "未知"
        frame = self._price_frame(code)
        if frame is None or frame.empty:
            return {"code": code, "name": name, "signal_date": signal_date,
                    "matched_date": None, "close": None}
        # 取 signal_date 当日；若当日非交易日，回退到之前最近交易日
        eligible = frame.index[frame["date"] <= target_ts]
        if len(eligible) == 0:
            return {"code": code, "name": name, "signal_date": signal_date,
                    "matched_date": None, "close": None}
        row = frame.iloc[int(eligible[-1])]
        matched = row["date"].strftime("%Y-%m-%d")
        return {
            "code": code,
            "name": name,
            "signal_date": signal_date,
            "matched_date": matched,
            "close": _safe_float(row.get("close"), 0.0) or None,
        }

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
        # 切到 holding 当日：若 eval_row.date 已经 > buy_row.date（即评估日已经过了入场日），
        # 应该立即按 entry_price/eval_close 计算 latest_return_pct，避免之后被 _evaluate_holding
        # 同日短路（last_eval_date == eval_date）卡住而长期显示 0%。
        eval_close = _safe_float(eval_row.get("close"), 0.0)
        rounded_entry = round(buy_price, 3)
        if rounded_entry > 0 and eval_close > 0 and eval_row["date"] > buy_row["date"]:
            initial_return_pct = round((eval_close / rounded_entry - 1) * 100, 2)
        else:
            initial_return_pct = 0.0
        self._update_item(
            item["tracking_id"],
            status="holding",
            entry_date=buy_date,
            entry_price=rounded_entry,
            quantity=quantity,
            remaining_pct=100.0,
            last_eval_date=eval_date,
            last_close=eval_close,
            latest_return_pct=initial_return_pct,
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

    def _evaluate_holding(self, item: dict, eval_row, force: bool = False) -> dict:
        """评估 holding/partial_sold 状态。

        force=False（默认）保留同日短路，避免一次批量评估内重复计算；
        force=True 强制重算，用于收盘同步与手动改买入价后立即刷新 latest_return_pct。
        """
        eval_date = eval_row["date"].strftime("%Y-%m-%d")
        if not force and item.get("last_eval_date") == eval_date:
            return item

        close_price = _safe_float(eval_row.get("close"), 0.0)
        entry_price = _safe_float(item.get("entry_price"), 0.0)
        return_pct = (close_price / entry_price - 1) * 100 if entry_price > 0 and close_price > 0 else 0.0
        params = dict(item.get("params") or {})
        trigger_pct = _safe_float(params.get("profit_trigger_pct"), 5.0)
        step_pct = max(0.0, _safe_float(params.get("profit_step_pct"), 10.0))
        sell_pct = max(0.0, min(100.0, _safe_float(params.get("profit_sell_pct"), 25.0)))
        keep_pct = max(0.0, min(100.0, _safe_float(params.get("profit_keep_pct"), 0.0)))
        remaining_pct = _safe_float(item.get("remaining_pct"), 100.0)

        if bool(params.get("profit_run_enabled", True)) and trigger_pct > 0:
            runner_triggered = bool(params.get("runner_triggered", False))
            if return_pct >= trigger_pct and not runner_triggered:
                runner_triggered = True
                params["runner_triggered"] = True
                params["next_profit_ladder_pct"] = round(trigger_pct + step_pct, 2)

            if runner_triggered and step_pct > 0 and sell_pct > 0:
                next_ladder_pct = _safe_float(params.get("next_profit_ladder_pct"), trigger_pct + step_pct)
                sell_total_pct = 0.0
                actions = []
                while (
                    remaining_pct - sell_total_pct > keep_pct
                    and return_pct >= next_ladder_pct
                ):
                    portion = min(sell_pct, max(0.0, remaining_pct - sell_total_pct - keep_pct))
                    if portion <= 0:
                        break
                    sell_total_pct += portion
                    actions.append(
                        {
                            "action": "sell_partial",
                            "profit_pct": round(next_ladder_pct, 2),
                            "sell_pct": round(portion, 2),
                        }
                    )
                    next_ladder_pct += step_pct

                if sell_total_pct > 0:
                    next_remaining = round(max(0.0, remaining_pct - sell_total_pct), 2)
                    params["next_profit_ladder_pct"] = round(next_ladder_pct, 2)
                    if next_remaining <= keep_pct and not params.get("hold_core_recorded"):
                        params["hold_core_recorded"] = True
                        actions.append(
                            {
                                "action": "hold_core",
                                "profit_pct": round(return_pct, 2),
                                "remaining_pct": next_remaining,
                                "keep_pct": keep_pct,
                            }
                        )
                    intent = OrderIntent.from_candidate(
                        self._candidate(item),
                        side="SELL",
                        planned_at=eval_row["date"],
                        price_type="close",
                        target_price=close_price,
                        quantity=_round_lot_quantity(int(_safe_int(item.get("quantity"), 0) * (sell_total_pct / 100)), 100),
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
                        params=params,
                        closed_at=eval_date if next_remaining <= 0 else None,
                    )
                    self.add_event(
                        item["tracking_id"],
                        "profit_take",
                        eval_date,
                        "SELL_PARTIAL",
                        "达到放飞阶梯，生成部分卖出建议",
                        {
                            "intent": intent,
                            "sell_pct": round(sell_total_pct, 2),
                            "remaining_pct": next_remaining,
                            "actions": actions,
                        },
                    )
                    return self.get_item(item["tracking_id"])

            if runner_triggered:
                next_action = "HOLD_CORE" if remaining_pct <= keep_pct else "HOLD_RUNNER"
                message = "已进入放飞跟踪，等待下一阶梯" if next_action == "HOLD_RUNNER" else "底仓已保留，继续持有"
                self._update_item(
                    item["tracking_id"],
                    last_eval_date=eval_date,
                    last_close=close_price,
                    latest_return_pct=round(return_pct, 2),
                    next_action=next_action,
                    latest_intent=None,
                    params=params,
                )
                self.add_event(
                    item["tracking_id"],
                    "profit_runner",
                    eval_date,
                    next_action,
                    message,
                    {
                        "return_pct": round(return_pct, 2),
                        "remaining_pct": remaining_pct,
                        "next_profit_ladder_pct": params.get("next_profit_ladder_pct"),
                    },
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
