"""人工选股池服务。"""
import json
from datetime import datetime
from typing import Optional

from web.backend.services.sqlite_service import get_connection


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
