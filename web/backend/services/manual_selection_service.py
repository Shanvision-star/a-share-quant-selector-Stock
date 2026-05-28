"""人工选股池服务。"""
import json
import re
from datetime import datetime
from typing import Optional

from web.backend.services.sqlite_service import get_connection


# 6 位 A 股代码正则；P1 三入口（txt/paste/from-strategy）共用同一解析逻辑，
# 防止"上传 txt 用一套规则、粘贴用另一套"导致行为漂移
_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _now_text() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _decode_row(row) -> dict:
    item = dict(row)
    raw_payload = item.pop('source_payload_json', None)
    if raw_payload:
        try:
            item['source_payload'] = json.loads(raw_payload)
        except (json.JSONDecodeError, TypeError):
            item['source_payload'] = {}
    else:
        item['source_payload'] = {}
    return item


def list_selections(
    selection_date: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list[dict]:
    conn = get_connection()
    conditions = []
    params = []
    if selection_date:
        conditions.append('selection_date = ?')
        params.append(selection_date)
    if start_date:
        conditions.append('selection_date >= ?')
        params.append(start_date)
    if end_date:
        conditions.append('selection_date <= ?')
        params.append(end_date)
    where_clause = (' WHERE ' + ' AND '.join(conditions)) if conditions else ''
    rows = conn.execute(
        f"""SELECT * FROM manual_selections{where_clause}
            ORDER BY selection_date DESC, updated_at DESC, code ASC""",
        params,
    ).fetchall()
    return [_decode_row(row) for row in rows]


def list_selection_dates(limit: int = 60) -> list[str]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT selection_date FROM manual_selections ORDER BY selection_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [row['selection_date'] for row in rows]


def get_selection(selection_date: str, code: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM manual_selections WHERE selection_date = ? AND code = ?",
        (selection_date, code),
    ).fetchone()
    return _decode_row(row) if row else None


def upsert_selection(payload: dict) -> dict:
    conn = get_connection()
    now_text = _now_text()
    source_payload = payload.get('source_payload') or {}
    conn.execute(
        """INSERT INTO manual_selections
           (selection_date, code, name, strategy_name, source_trade_date,
            source_signal_date, source_payload_json, note, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(selection_date, code) DO UPDATE SET
             name = excluded.name,
             strategy_name = excluded.strategy_name,
             source_trade_date = excluded.source_trade_date,
             source_signal_date = excluded.source_signal_date,
             source_payload_json = excluded.source_payload_json,
             note = excluded.note,
             updated_at = excluded.updated_at""",
        (
            payload['selection_date'],
            payload['code'],
            payload.get('name', ''),
            payload.get('strategy_name', ''),
            payload.get('source_trade_date'),
            payload.get('source_signal_date'),
            json.dumps(source_payload, ensure_ascii=False),
            payload.get('note', ''),
            now_text,
            now_text,
        ),
    )
    conn.commit()
    return get_selection(payload['selection_date'], payload['code']) or {}


def delete_selection(selection_date: str, code: str) -> bool:
    conn = get_connection()
    cursor = conn.execute(
        "DELETE FROM manual_selections WHERE selection_date = ? AND code = ?",
        (selection_date, code),
    )
    conn.commit()
    return cursor.rowcount > 0


# ---------- P1: 三入口批量导入 ----------
# 设计原则：txt / paste / strategy_pick 三个入口收敛到同一 import_codes_batch，
# 避免每个入口重复 upsert 逻辑导致行为漂移；import_type 仅作为 source_payload
# 的标签，便于日后审计 "这条股票是手贴还是策略勾选进来的"


def parse_codes_from_text(text: str) -> list[str]:
    """从任意文本中提取 6 位 A 股代码，去重且保留首次出现顺序。

    保序的意义：用户从研报粘贴时，靠前的代码通常是研报重点推荐，
    跟踪批量导入后这个顺序仍有信息量，不应被 set() 随机化。
    """
    if not text:
        return []
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _CODE_PATTERN.finditer(text):
        code = match.group(1)
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered


def import_codes_batch(
    selection_date: str,
    codes: list[str],
    import_type: str,
    strategy_name: str = "",
    source_trade_date: Optional[str] = None,
    imported_by: str = "user",
) -> dict:
    """三入口共用的批量导入实现。

    参数:
        selection_date: 入池日期（用户在前端选择，通常是今天）
        codes: 原始代码列表，可能含非法值；本函数负责过滤
        import_type: 来源标签，写入 source_payload.import_type，便于追溯
        strategy_name: 策略来源（仅 strategy_pick 入口非空）
        source_trade_date: 信号交易日（默认 None，由调用方决定是否填）
        imported_by: 导入者标识，默认 "user"；预留给未来自动化/MCP 入口区分

    返回:
        {"inserted": int, "updated": int, "invalid": list[str]}

    边界:
        - 重复 (selection_date, code) 由唯一索引拦截，进入 ON CONFLICT 分支 →
          计入 updated，而非 inserted；
        - 非 6 位数字代码不抛异常，进入 invalid 列表，让前端整体提示。
    """
    inserted = 0
    updated = 0
    invalid: list[str] = []

    # 先按合法性分流，避免在循环中混合异常处理
    valid_codes: list[str] = []
    for raw in codes or []:
        code = str(raw or "").strip()
        if len(code) == 6 and code.isdigit():
            valid_codes.append(code)
        else:
            invalid.append(raw)

    if not valid_codes:
        return {"inserted": 0, "updated": 0, "invalid": invalid}

    conn = get_connection()
    # 先查已有 (selection_date, code) 集合，区分 inserted vs updated
    placeholders = ",".join(["?"] * len(valid_codes))
    existing_rows = conn.execute(
        f"SELECT code FROM manual_selections WHERE selection_date = ? AND code IN ({placeholders})",
        [selection_date, *valid_codes],
    ).fetchall()
    existing_codes = {row["code"] for row in existing_rows}

    for code in valid_codes:
        payload = {
            "selection_date": selection_date,
            "code": code,
            "name": "",
            "strategy_name": strategy_name,
            "source_trade_date": source_trade_date,
            "source_signal_date": source_trade_date,
            # import_type 落入 source_payload，未来增加新入口（如 mcp）只需扩 tag
            "source_payload": {"import_type": import_type, "imported_by": imported_by},
            "note": "",
        }
        upsert_selection(payload)
        if code in existing_codes:
            updated += 1
        else:
            inserted += 1

    return {"inserted": inserted, "updated": updated, "invalid": invalid}
