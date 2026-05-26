"""P4 跟踪告警事件服务：持久化 + 钉钉分发桩。

参考 docs/Tracking/tracking_agent_plan.md §6 钉钉调度：
- priority < 30           必发（强制触达，无视 slot 容量）
- 30 <= priority < 60     按规模（每个 slot 受 per_slot_limit 限制，剩余继续 pending）
- priority >= 60          聚合（不立即推送，仅标记 aggregated 进入次日聚合视图）

落地策略：
- 表 tracking_alert_events 已由 sqlite_service.SCHEMA_VERSION=5 创建；
- persist_alerts 使用 INSERT OR IGNORE 借助 UNIQUE(dedup_key) 实现幂等；
- dispatch_pending_alerts 不修改 priority 边界，只按 ui_status='pending' 取候选；
- notifier 接口 send(slot, alerts) 返回 None；测试中以 _RecordingNotifier 替换；
- 生产实现可在 utils/dingtalk.py 中包装；本服务不做真实 HTTP。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Any, Callable, Iterable, Optional, Protocol

from web.backend.services.sqlite_service import get_connection

# 优先级分层阈值（按 P0 设计文档 §6）。
PRIORITY_MUST_SEND_BELOW = 30
PRIORITY_AGGREGATE_AT_OR_ABOVE = 60
DEFAULT_PER_SLOT_LIMIT = 8  # 钉钉单次推送规模上限，避免刷屏


class AlertNotifier(Protocol):
    """通知器协议：send(slot, alerts) -> None。"""

    def send(self, slot: str, alerts: Iterable[dict]) -> None: ...


class _NullNotifier:
    """默认无操作通知器：仅保证测试与首次部署不依赖外部 HTTP。"""

    def send(self, slot: str, alerts: Iterable[dict]) -> None:  # noqa: D401 - 桩实现
        return None


class TrackingAlertService:
    """跟踪告警事件持久化与分发服务。

    参数
    ----
    connection_factory: 提供 sqlite3.Connection 的工厂；测试可注入 :memory: 连接。
    notifier:           通知器，缺省 NullNotifier。
    """

    def __init__(
        self,
        connection_factory: Callable[[], sqlite3.Connection] = get_connection,
        notifier: Optional[AlertNotifier] = None,
    ) -> None:
        self._conn_factory = connection_factory
        self.notifier: AlertNotifier = notifier or _NullNotifier()
        self._lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------
    # schema 兜底（测试用内存库时确保表存在；生产库已由 init_database 建表）
    # ------------------------------------------------------------------
    def _ensure_schema(self) -> None:
        conn = self._conn_factory()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_alert_events (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_id TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                code TEXT NOT NULL,
                eval_date TEXT NOT NULL,
                priority INTEGER NOT NULL,
                category TEXT,
                action_label TEXT,
                name TEXT,
                message TEXT,
                evidence_json TEXT,
                dedup_key TEXT NOT NULL UNIQUE,
                dingtalk_slot TEXT,
                ui_status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                dispatched_at TEXT
            )
            """
        )
        conn.commit()

    # ------------------------------------------------------------------
    # 写入：幂等持久化
    # ------------------------------------------------------------------
    def persist_alerts(self, alerts: Iterable[dict]) -> dict:
        """将告警批量写入；同 dedup_key 视为重复，计入 skipped_dup。"""
        created = 0
        skipped = 0
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._conn_factory()
        with self._lock:
            for alert in alerts:
                dedup_key = alert.get("dedup_key")
                if not dedup_key:
                    # 缺少 dedup_key 视为脏数据；不抛异常，仅跳过避免影响其它规则
                    skipped += 1
                    continue
                evidence = alert.get("evidence")
                evidence_json = json.dumps(evidence, ensure_ascii=False) if evidence is not None else None
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO tracking_alert_events (
                        tracking_id, rule_id, code, eval_date, priority,
                        category, action_label, name, message, evidence_json,
                        dedup_key, ui_status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        alert.get("tracking_id", ""),
                        alert.get("rule_id", ""),
                        alert.get("code", ""),
                        alert.get("eval_date", ""),
                        int(alert.get("priority", 0)),
                        alert.get("category"),
                        alert.get("action_label"),
                        alert.get("name"),
                        alert.get("message"),
                        evidence_json,
                        dedup_key,
                        now,
                    ),
                )
                if cur.rowcount == 1:
                    created += 1
                else:
                    skipped += 1
            conn.commit()
        return {"created": created, "skipped_dup": skipped}

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    def list_alerts(
        self,
        tracking_id: Optional[str] = None,
        eval_date: Optional[str] = None,
        ui_status: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict]:
        conn = self._conn_factory()
        sql = ["SELECT * FROM tracking_alert_events WHERE 1=1"]
        args: list[Any] = []
        if tracking_id is not None:
            sql.append("AND tracking_id = ?")
            args.append(tracking_id)
        if eval_date is not None:
            sql.append("AND eval_date = ?")
            args.append(eval_date)
        if ui_status is not None:
            sql.append("AND ui_status = ?")
            args.append(ui_status)
        sql.append("ORDER BY priority ASC, alert_id ASC LIMIT ?")
        args.append(int(limit))
        rows = conn.execute(" ".join(sql), args).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 分发：按优先级分层处理 pending 事件
    # ------------------------------------------------------------------
    def dispatch_pending_alerts(
        self,
        slot: str,
        now: Optional[datetime] = None,
        per_slot_limit: int = DEFAULT_PER_SLOT_LIMIT,
    ) -> dict:
        """按 slot 推送 pending 告警；返回 {dispatched, deferred, aggregated}。"""
        now_iso = (now or datetime.now()).isoformat(timespec="seconds")
        conn = self._conn_factory()
        with self._lock:
            rows = conn.execute(
                """
                SELECT * FROM tracking_alert_events
                WHERE ui_status = 'pending'
                ORDER BY priority ASC, alert_id ASC
                """
            ).fetchall()
            pending = [self._row_to_dict(r) for r in rows]

            must_send: list[dict] = []
            scale: list[dict] = []
            aggregate: list[dict] = []
            for alert in pending:
                p = int(alert["priority"])
                if p < PRIORITY_MUST_SEND_BELOW:
                    must_send.append(alert)
                elif p >= PRIORITY_AGGREGATE_AT_OR_ABOVE:
                    aggregate.append(alert)
                else:
                    scale.append(alert)

            # 规模层受 limit 限制：先扣除必发层占用的额度，剩余留给后续 slot
            remaining = max(0, per_slot_limit - len(must_send))
            scale_send = scale[:remaining]
            scale_defer = scale[remaining:]

            to_send = must_send + scale_send
            if to_send:
                # 通知器异常不应阻断状态推进；按当前 P0 设计先 fail-fast，便于测试桩观察
                self.notifier.send(slot, to_send)
                self._mark_dispatched([a["alert_id"] for a in to_send], slot, now_iso)

            if aggregate:
                self._mark_aggregated([a["alert_id"] for a in aggregate], now_iso)

            conn.commit()
            return {
                "dispatched": len(to_send),
                "deferred": len(scale_defer),
                "aggregated": len(aggregate),
            }

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _mark_dispatched(self, alert_ids: list[int], slot: str, now_iso: str) -> None:
        if not alert_ids:
            return
        conn = self._conn_factory()
        placeholders = ",".join("?" for _ in alert_ids)
        conn.execute(
            f"""
            UPDATE tracking_alert_events
               SET ui_status = 'dispatched',
                   dingtalk_slot = ?,
                   dispatched_at = ?
             WHERE alert_id IN ({placeholders})
            """,
            [slot, now_iso, *alert_ids],
        )

    def _mark_aggregated(self, alert_ids: list[int], now_iso: str) -> None:
        if not alert_ids:
            return
        conn = self._conn_factory()
        placeholders = ",".join("?" for _ in alert_ids)
        conn.execute(
            f"""
            UPDATE tracking_alert_events
               SET ui_status = 'aggregated',
                   dispatched_at = ?
             WHERE alert_id IN ({placeholders})
            """,
            [now_iso, *alert_ids],
        )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        if d.get("evidence_json"):
            try:
                d["evidence"] = json.loads(d["evidence_json"])
            except (TypeError, ValueError):
                d["evidence"] = None
        else:
            d["evidence"] = None
        return d


# 模块级单例：与其它服务保持一致的引用方式
tracking_alert_service = TrackingAlertService(connection_factory=get_connection)
