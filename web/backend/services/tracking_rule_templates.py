"""P3 跟踪告警-规则模板服务。

模板表 `tracking_rule_templates` 用于在 P2 规则引擎之上做"按用户偏好启用/禁用规则
+ 覆盖参数"。模板与规则的关系是多对一：同一个 rule_id 可有多条模板（场景化预设），
启用时其 params 会按写入顺序合并，最后写覆盖先写。

为什么这样设计：
- DEFAULT_PARAMS 是引擎自带的兜底，不可改；
- 用户在前端可创建多个命名预设（如"激进版""稳健版"），按需启用；
- 仅启用的模板进入 enabled_rules 集合；未被任何启用模板涉及的规则保持默认启用，
  这样新增规则到 RULE_META 后无须用户重新配置就能立刻生效。
"""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Callable
from uuid import uuid4

from web.backend.services.sqlite_service import get_connection
from web.backend.services.tracking_rule_engine import RULE_META


ConnectionFactory = Callable[[], Any]


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _to_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


class TrackingRuleTemplateService:
    """规则模板 CRUD + 引擎输入装配。"""

    def __init__(self, connection_factory: ConnectionFactory):
        self.connection_factory = connection_factory
        self._ensure_schema()

    # ---------- 内部工具 ----------
    def _conn(self):
        return self.connection_factory()

    def _ensure_schema(self) -> None:
        conn = self._conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracking_rule_templates (
                template_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                rule_id TEXT NOT NULL,
                params_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rule_templates_rule_id ON tracking_rule_templates(rule_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rule_templates_enabled ON tracking_rule_templates(enabled)"
        )
        conn.commit()

    def _row_to_record(self, row) -> dict:
        if row is None:
            return None  # type: ignore[return-value]
        record = dict(row)
        try:
            record["params"] = json.loads(record.pop("params_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            record["params"] = {}
        record["enabled"] = bool(record.get("enabled"))
        return record

    @staticmethod
    def _validate_rule_id(rule_id: str) -> None:
        if rule_id not in RULE_META:
            raise ValueError(f"未知规则 rule_id={rule_id!r}，必须在 RULE_META 中注册")

    # ---------- CRUD ----------
    def create(self, payload: dict) -> dict:
        rule_id = str(payload.get("rule_id") or "").strip()
        self._validate_rule_id(rule_id)
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("模板名称不能为空")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError("params 必须是 dict")

        template_id = f"rtpl_{uuid4().hex[:12]}"
        now = _now_text()
        enabled = _to_bool(payload.get("enabled"), default=True)
        note = str(payload.get("note") or "")

        self._conn().execute(
            """
            INSERT INTO tracking_rule_templates
                (template_id, name, rule_id, params_json, enabled, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                name,
                rule_id,
                json.dumps(params, ensure_ascii=False),
                1 if enabled else 0,
                note,
                now,
                now,
            ),
        )
        self._conn().commit()
        return self.get(template_id)  # type: ignore[return-value]

    def get(self, template_id: str) -> dict | None:
        row = self._conn().execute(
            "SELECT * FROM tracking_rule_templates WHERE template_id = ?",
            (template_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list(
        self,
        rule_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[dict]:
        where: list[str] = []
        values: list[Any] = []
        if rule_id:
            where.append("rule_id = ?")
            values.append(rule_id)
        if enabled_only:
            where.append("enabled = 1")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self._conn().execute(
            f"SELECT * FROM tracking_rule_templates {where_sql} ORDER BY created_at ASC, template_id ASC",
            values,
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def update(self, template_id: str, changes: dict) -> dict | None:
        existing = self.get(template_id)
        if existing is None:
            return None

        new_name = changes.get("name", existing["name"])
        if not isinstance(new_name, str) or not new_name.strip():
            raise ValueError("模板名称不能为空")

        new_params = changes.get("params", existing["params"])
        if not isinstance(new_params, dict):
            raise ValueError("params 必须是 dict")

        new_rule_id = changes.get("rule_id", existing["rule_id"])
        self._validate_rule_id(new_rule_id)

        new_enabled = _to_bool(changes.get("enabled", existing["enabled"]))
        new_note = changes.get("note", existing.get("note") or "")

        self._conn().execute(
            """
            UPDATE tracking_rule_templates
            SET name = ?, rule_id = ?, params_json = ?, enabled = ?, note = ?, updated_at = ?
            WHERE template_id = ?
            """,
            (
                new_name.strip(),
                new_rule_id,
                json.dumps(new_params, ensure_ascii=False),
                1 if new_enabled else 0,
                new_note,
                _now_text(),
                template_id,
            ),
        )
        self._conn().commit()
        return self.get(template_id)

    def delete(self, template_id: str) -> bool:
        cursor = self._conn().execute(
            "DELETE FROM tracking_rule_templates WHERE template_id = ?",
            (template_id,),
        )
        self._conn().commit()
        return cursor.rowcount > 0

    # ---------- 引擎输入装配 ----------
    def build_engine_inputs(self) -> dict:
        """聚合启用中的模板，输出 evaluate_rules 直接使用的 params_overrides 与 enabled_rules。

        合并规则：同一 rule_id 多条启用模板按 created_at 升序合并 params；
        若同一字段被多条模板覆盖，后写覆盖前写。

        enabled_rules 语义：
        - 无模板 → 全部规则启用（保持向后兼容）；
        - 有模板 → 仅"被启用模板涵盖"的规则启用，其余排除（让用户明确选）。
        """
        rows = self._conn().execute(
            "SELECT rule_id, params_json, enabled FROM tracking_rule_templates ORDER BY created_at ASC, template_id ASC"
        ).fetchall()

        if not rows:
            return {
                "params_overrides": {},
                "enabled_rules": set(RULE_META.keys()),
            }

        overrides: dict[str, dict] = {}
        enabled_rules: set[str] = set()
        for row in rows:
            if not bool(row["enabled"]):
                continue
            rule_id = row["rule_id"]
            if rule_id not in RULE_META:
                continue
            try:
                params = json.loads(row["params_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                params = {}
            if not isinstance(params, dict):
                continue
            overrides.setdefault(rule_id, {}).update(params)
            enabled_rules.add(rule_id)

        return {"params_overrides": overrides, "enabled_rules": enabled_rules}


# 生产环境单例：复用 sqlite_service 的线程局部连接。
tracking_rule_template_service = TrackingRuleTemplateService(connection_factory=get_connection)
