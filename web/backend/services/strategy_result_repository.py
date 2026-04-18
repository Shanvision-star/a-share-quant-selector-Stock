"""策略结果仓储层 - 封装 SQLite 读写操作"""
import json
import uuid
from datetime import datetime
from typing import Optional

from web.backend.services.sqlite_service import get_connection


def generate_run_id() -> str:
    """生成唯一作业 ID"""
    return datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]


# ─── 作业运行记录 ───

def create_run(
    run_id: str,
    run_type: str,
    trade_date: str,
    strategy_filter: str,
    total_count: int = 0,
) -> dict:
    """创建作业运行记录"""
    conn = get_connection()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        """INSERT INTO strategy_runs
           (run_id, run_type, trade_date, strategy_filter, status, started_at, total_count)
           VALUES (?, ?, ?, ?, 'running', ?, ?)""",
        (run_id, run_type, trade_date, strategy_filter, now, total_count),
    )
    conn.commit()
    return {
        'run_id': run_id,
        'run_type': run_type,
        'trade_date': trade_date,
        'strategy_filter': strategy_filter,
        'status': 'running',
        'started_at': now,
        'total_count': total_count,
    }


def update_run(run_id: str, **kwargs):
    """更新作业运行记录"""
    conn = get_connection()
    fields = []
    values = []
    for key, val in kwargs.items():
        fields.append(f"{key} = ?")
        values.append(val)
    if not fields:
        return
    values.append(run_id)
    conn.execute(
        f"UPDATE strategy_runs SET {', '.join(fields)} WHERE run_id = ?",
        values,
    )
    conn.commit()


def finish_run(run_id: str, status: str, message: str = '', matched_count: int = 0, processed_count: int = 0):
    """完成作业"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    update_run(
        run_id,
        status=status,
        completed_at=now,
        message=message,
        matched_count=matched_count,
        processed_count=processed_count,
    )


def get_run(run_id: str) -> Optional[dict]:
    """获取单个作业"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM strategy_runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_runs(
    run_type: str = None,
    status: str = None,
    strategy_filter: str = None,
    date: str = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """查询作业列表"""
    conn = get_connection()
    conditions = []
    params = []
    if run_type:
        conditions.append("run_type = ?")
        params.append(run_type)
    if status:
        conditions.append("status = ?")
        params.append(status)
    if strategy_filter:
        conditions.append("strategy_filter = ?")
        params.append(strategy_filter)
    if date:
        conditions.append("trade_date = ?")
        params.append(date)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    count_row = conn.execute(f"SELECT COUNT(*) as cnt FROM strategy_runs{where}", params).fetchone()
    total = count_row['cnt'] if count_row else 0

    offset = (page - 1) * per_page
    rows = conn.execute(
        f"SELECT * FROM strategy_runs{where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
        params + [per_page, offset],
    ).fetchall()

    return {
        'items': [dict(r) for r in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
    }


# ─── 作业事件 ───

def insert_event(
    run_id: str,
    event_type: str,
    strategy_filter: str = None,
    strategy_name: str = None,
    progress: int = None,
    message: str = None,
    payload: dict = None,
):
    """插入作业事件"""
    conn = get_connection()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')
    conn.execute(
        """INSERT INTO strategy_run_events
           (run_id, event_type, strategy_filter, strategy_name, progress, message, payload_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, event_type, strategy_filter, strategy_name,
            progress, message,
            json.dumps(payload, ensure_ascii=False) if payload else None,
            now,
        ),
    )
    conn.commit()


def get_run_events(run_id: str, limit: int = 500) -> list:
    """获取作业事件"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM strategy_run_events WHERE run_id = ? ORDER BY event_id ASC LIMIT ?",
        (run_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── 策略结果 ───

def insert_results_batch(results: list[dict]):
    """批量插入策略结果"""
    if not results:
        return
    conn = get_connection()
    conn.executemany(
        """INSERT OR REPLACE INTO strategy_results
           (run_id, trade_date, strategy_filter, strategy_name, code, name,
            category, signal_date, trigger_price, close, j_value,
            similarity_score, reason, signal_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                r['run_id'], r['trade_date'], r['strategy_filter'], r['strategy_name'],
                r['code'], r.get('name', ''), r.get('category', ''),
                r.get('signal_date', ''), r.get('trigger_price'), r.get('close'),
                r.get('j_value'), r.get('similarity_score'),
                r.get('reason', ''),
                json.dumps(r.get('signal', {}), ensure_ascii=False) if r.get('signal') else None,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            )
            for r in results
        ],
    )
    conn.commit()


# Allowed sort columns (whitelist to prevent SQL injection)
_SORT_COLUMNS = {
    'trade_date', 'signal_date', 'code', 'name', 'strategy_name',
    'trigger_price', 'close', 'j_value', 'similarity_score', 'created_at',
    'run_started_at', 'run_completed_at',
}


def _build_result_filters(
    table_alias: str,
    trade_date: str = None,
    strategy_filter: str = None,
    code: str = None,
    keyword: str = None,
    min_j_value: float = None,
    max_j_value: float = None,
    min_similarity: float = None,
    max_similarity: float = None,
    start_date: str = None,
    end_date: str = None,
):
    conditions = []
    params = []
    prefix = f"{table_alias}."

    if trade_date:
        conditions.append(f"{prefix}trade_date = ?")
        params.append(trade_date)
    if strategy_filter and strategy_filter != 'all':
        conditions.append(f"{prefix}strategy_filter = ?")
        params.append(strategy_filter)
    if code:
        conditions.append(f"{prefix}code = ?")
        params.append(code)
    if keyword:
        conditions.append(f"({prefix}code LIKE ? OR {prefix}name LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if min_j_value is not None:
        conditions.append(f"{prefix}j_value >= ?")
        params.append(min_j_value)
    if max_j_value is not None:
        conditions.append(f"{prefix}j_value <= ?")
        params.append(max_j_value)
    if min_similarity is not None:
        conditions.append(f"{prefix}similarity_score >= ?")
        params.append(min_similarity)
    if max_similarity is not None:
        conditions.append(f"{prefix}similarity_score <= ?")
        params.append(max_similarity)
    if start_date:
        conditions.append(f"{prefix}trade_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append(f"{prefix}trade_date <= ?")
        params.append(end_date)

    return conditions, params


def _build_latest_results_cte(
    trade_date: str = None,
    strategy_filter: str = None,
    code: str = None,
    keyword: str = None,
    min_j_value: float = None,
    max_j_value: float = None,
    min_similarity: float = None,
    max_similarity: float = None,
    start_date: str = None,
    end_date: str = None,
):
    conditions, params = _build_result_filters(
        'sr',
        trade_date=trade_date,
        strategy_filter=strategy_filter,
        code=code,
        keyword=keyword,
        min_j_value=min_j_value,
        max_j_value=max_j_value,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
        start_date=start_date,
        end_date=end_date,
    )
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        WITH ranked_results AS (
            SELECT
                sr.*,
                runs.started_at AS run_started_at,
                runs.completed_at AS run_completed_at,
                runs.status AS run_status,
                runs.run_type AS run_type,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        sr.trade_date,
                        sr.strategy_filter,
                        sr.strategy_name,
                        sr.code,
                        COALESCE(sr.category, ''),
                        COALESCE(sr.signal_date, '')
                    ORDER BY
                        COALESCE(runs.completed_at, runs.started_at, sr.created_at) DESC,
                        runs.started_at DESC,
                        sr.created_at DESC,
                        sr.result_id DESC
                ) AS row_num
            FROM strategy_results sr
            LEFT JOIN strategy_runs runs ON runs.run_id = sr.run_id
            {where}
        )
    """
    return sql, params


def _decode_result_rows(rows) -> list:
    items = []
    for row in rows:
        item = dict(row)
        if item.get('signal_json'):
            try:
                item['signal'] = json.loads(item['signal_json'])
            except (json.JSONDecodeError, TypeError):
                item['signal'] = {}
        item.pop('signal_json', None)
        item.pop('row_num', None)
        items.append(item)
    return items


def query_results(
    trade_date: str = None,
    strategy_filter: str = None,
    code: str = None,
    keyword: str = None,
    min_j_value: float = None,
    max_j_value: float = None,
    min_similarity: float = None,
    max_similarity: float = None,
    start_date: str = None,
    end_date: str = None,
    page: int = 1,
    per_page: int = 50,
    sort_by: str = 'trade_date',
    sort_order: str = 'desc',
) -> dict:
    """查询策略结果（支持历史）"""
    conn = get_connection()
    cte_sql, params = _build_latest_results_cte(
        trade_date=trade_date,
        strategy_filter=strategy_filter,
        code=code,
        keyword=keyword,
        min_j_value=min_j_value,
        max_j_value=max_j_value,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
        start_date=start_date,
        end_date=end_date,
    )

    count_row = conn.execute(
        f"{cte_sql} SELECT COUNT(*) as cnt FROM ranked_results WHERE row_num = 1",
        params,
    ).fetchone()
    total = count_row['cnt'] if count_row else 0
    unique_count_row = conn.execute(
        f"{cte_sql} SELECT COUNT(DISTINCT code) as cnt FROM ranked_results WHERE row_num = 1",
        params,
    ).fetchone()
    unique_code_total = unique_count_row['cnt'] if unique_count_row else 0

    col = sort_by if sort_by in _SORT_COLUMNS else 'trade_date'
    direction = 'ASC' if sort_order.lower() == 'asc' else 'DESC'
    order_parts = [f'{col} {direction}']
    if col != 'trade_date':
        order_parts.append('trade_date DESC')
    if col != 'run_started_at':
        order_parts.append('run_started_at DESC')
    if col != 'code':
        order_parts.append('code ASC')
    order_clause = 'ORDER BY ' + ', '.join(order_parts)

    offset = (page - 1) * per_page
    rows = conn.execute(
        f"""{cte_sql}
            SELECT * FROM ranked_results
            WHERE row_num = 1
            {order_clause}
            LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    ).fetchall()

    return {
        'items': _decode_result_rows(rows),
        'total': total,
        'unique_code_total': unique_code_total,
        'page': page,
        'per_page': per_page,
    }


def query_unique_codes(
    trade_date: str = None,
    strategy_filter: str = None,
    code: str = None,
    keyword: str = None,
    min_j_value: float = None,
    max_j_value: float = None,
    min_similarity: float = None,
    max_similarity: float = None,
    start_date: str = None,
    end_date: str = None,
) -> list[str]:
    """查询去重后的股票代码列表（按 code 升序）"""
    conn = get_connection()
    cte_sql, params = _build_latest_results_cte(
        trade_date=trade_date,
        strategy_filter=strategy_filter,
        code=code,
        keyword=keyword,
        min_j_value=min_j_value,
        max_j_value=max_j_value,
        min_similarity=min_similarity,
        max_similarity=max_similarity,
        start_date=start_date,
        end_date=end_date,
    )
    rows = conn.execute(
        f"{cte_sql} SELECT DISTINCT code FROM ranked_results WHERE row_num = 1 ORDER BY code ASC",
        params,
    ).fetchall()
    return [str(r['code']) for r in rows if r['code']]


def get_results_for_date(trade_date: str, strategy_filter: str = 'all') -> list:
    """获取指定日期的全部结果（不分页，用于首页摘要）"""
    conn = get_connection()
    cte_sql, params = _build_latest_results_cte(trade_date=trade_date, strategy_filter=strategy_filter)
    rows = conn.execute(
        f"""{cte_sql}
            SELECT * FROM ranked_results
            WHERE row_num = 1
            ORDER BY strategy_filter ASC, run_started_at DESC, code ASC, signal_date DESC""",
        params,
    ).fetchall()
    return _decode_result_rows(rows)


def get_result_summary_for_date(trade_date: str) -> dict:
    """获取指定日期的结果统计摘要"""
    conn = get_connection()
    cte_sql, params = _build_latest_results_cte(trade_date=trade_date)
    rows = conn.execute(
        f"""{cte_sql}
           SELECT strategy_filter, COUNT(*) as cnt
           FROM ranked_results
           WHERE row_num = 1
           GROUP BY strategy_filter""",
        params,
    ).fetchall()

    group_totals = {}
    total = 0
    for r in rows:
        group_totals[r['strategy_filter']] = r['cnt']
        total += r['cnt']

    return {
        'trade_date': trade_date,
        'total': total,
        'group_totals': group_totals,
        'available_groups': sorted(group_totals.keys()),
    }


def delete_results_for_run(run_id: str):
    """删除某次运行的所有结果"""
    conn = get_connection()
    conn.execute("DELETE FROM strategy_results WHERE run_id = ?", (run_id,))
    conn.commit()


# ─── 缓存快照 ───

def save_snapshot(
    run_id: str,
    trade_date: str,
    strategy_filter: str,
    total_results: int,
    available_groups: list,
    group_totals: dict,
    summary: dict = None,
):
    """保存缓存快照"""
    conn = get_connection()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute(
        """INSERT INTO strategy_cache_snapshots
           (run_id, trade_date, strategy_filter, generated_at, total_results,
            available_groups_json, group_totals_json, summary_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id, trade_date, strategy_filter, now, total_results,
            json.dumps(available_groups, ensure_ascii=False),
            json.dumps(group_totals, ensure_ascii=False),
            json.dumps(summary, ensure_ascii=False) if summary else None,
        ),
    )
    conn.commit()


def get_latest_snapshot(trade_date: str = None, strategy_filter: str = None) -> Optional[dict]:
    """获取最新快照"""
    conn = get_connection()
    conditions = []
    params = []
    if trade_date:
        conditions.append("trade_date = ?")
        params.append(trade_date)
    if strategy_filter and strategy_filter != 'all':
        conditions.append("strategy_filter = ?")
        params.append(strategy_filter)

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    row = conn.execute(
        f"SELECT * FROM strategy_cache_snapshots{where} ORDER BY generated_at DESC LIMIT 1",
        params,
    ).fetchone()

    if not row:
        return None

    item = dict(row)
    for json_field in ('available_groups_json', 'group_totals_json', 'summary_json'):
        raw = item.pop(json_field, None)
        key = json_field.replace('_json', '')
        if raw:
            try:
                item[key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                item[key] = None
        else:
            item[key] = None

    return item


def get_available_trade_dates(limit: int = 30) -> list[str]:
    """获取有结果的交易日期列表"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM strategy_results ORDER BY trade_date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [r['trade_date'] for r in rows]
