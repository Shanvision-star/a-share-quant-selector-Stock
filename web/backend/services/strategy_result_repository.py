"""策略结果仓储层 - 封装 SQLite 读写操作"""
import json
import os
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

def insert_results_batch(results: list[dict], *, commit: bool = True):
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
    if commit:
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
    signal_or_trade_date = f"COALESCE(NULLIF({prefix}signal_date, ''), {prefix}trade_date)"

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
        conditions.append(f"{signal_or_trade_date} >= ?")
        params.append(start_date)
    if end_date:
        conditions.append(f"{signal_or_trade_date} <= ?")
        params.append(end_date)

    return conditions, params


def _authoritative_groups_cte() -> str:
    """按交易日与策略选最新正式发布版本，空分组也必须覆盖旧命中。"""
    conn = get_connection()
    has_snapshots = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_cache_snapshots'"
    ).fetchone()
    if not has_snapshots:
        # 旧版数据库及最小仓储消费者仍沿用逐条结果查询，不强制迁移读路径。
        return """authoritative_groups AS (
            SELECT NULL AS run_id, NULL AS trade_date, NULL AS strategy_filter,
                   1 AS publication_rank WHERE 0
        )"""
    return """authoritative_groups AS (
        SELECT snapshots.run_id, snapshots.trade_date, groups.value AS strategy_filter,
               ROW_NUMBER() OVER (
                   PARTITION BY snapshots.trade_date, groups.value
                   ORDER BY snapshots.snapshot_id DESC
               ) AS publication_rank
        FROM strategy_cache_snapshots snapshots,
             json_each(CASE WHEN json_valid(snapshots.available_groups_json)
                       THEN snapshots.available_groups_json ELSE '[]' END) groups
        WHERE json_extract(CASE WHEN json_valid(snapshots.summary_json)
                           THEN snapshots.summary_json ELSE '{}' END,
                           '$._authoritative') = 1
    )"""


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
    conditions.append('(publication.run_id IS NULL OR sr.run_id = publication.run_id)')
    where = " WHERE " + " AND ".join(conditions)

    sql = f"""
        WITH {_authoritative_groups_cte()}, ranked_results AS (
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
            LEFT JOIN authoritative_groups publication
                ON publication.trade_date = sr.trade_date
               AND publication.strategy_filter = sr.strategy_filter
               AND publication.publication_rank = 1
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

    published_groups = conn.execute(
        f"""WITH {_authoritative_groups_cte()}
            SELECT strategy_filter FROM authoritative_groups
            WHERE trade_date = ? AND publication_rank = 1""",
        (trade_date,),
    ).fetchall()
    group_totals = {r['strategy_filter']: 0 for r in published_groups}
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
    *,
    commit: bool = True,
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
    if commit:
        conn.commit()


def publish_snapshot(run_id: str, trade_date: str, strategy_filter: str,
                     batch: list[dict], snapshot: dict, cache_file) -> None:
    """在同一事务发布完整快照与结果；失败后旧正式版本继续可读。"""
    if snapshot.get('trade_date') != trade_date or snapshot.get('_run_id') != run_id:
        raise ValueError('快照日期或运行编号不一致')
    groups = snapshot.get('groups')
    if not isinstance(groups, dict) or not groups:
        raise ValueError('完整快照必须包含策略分组（允许分组零命中）')
    seen = set()
    for row in batch:
        if (row.get('run_id') != run_id or row.get('trade_date') != trade_date
                or row.get('strategy_filter') not in groups):
            raise ValueError('结果批次的运行、日期或策略分组不一致')
        key = (row['strategy_filter'], row['code'], row.get('signal_date') or '', row.get('category') or '')
        if key in seen:
            raise ValueError('完整结果批次包含重复信号')
        seen.add(key)
    summary = dict(snapshot)
    summary.pop('_invalidated', None)
    summary.update(_authoritative=True, _cache_file=os.path.normcase(os.path.abspath(os.fspath(cache_file))))
    conn = get_connection()
    savepoint = 'publish_' + uuid.uuid4().hex
    conn.execute(f'SAVEPOINT {savepoint}')
    try:
        # 多选策略可在同一 run 分阶段发布，替换整批防止旧命中残留。
        conn.execute('DELETE FROM strategy_results WHERE run_id = ?', (run_id,))
        insert_results_batch(batch, commit=False)
        save_snapshot(run_id, trade_date, strategy_filter, snapshot.get('total', 0),
                      sorted(groups), {sf: group.get('total', 0) for sf, group in groups.items()},
                      summary=summary, commit=False)
        conn.execute(f'RELEASE SAVEPOINT {savepoint}')
    except Exception:
        conn.execute(f'ROLLBACK TO SAVEPOINT {savepoint}')
        conn.execute(f'RELEASE SAVEPOINT {savepoint}')
        raise


def get_published_snapshot(cache_file) -> Optional[dict]:
    """读取指定缓存对应的最新权威完整快照，JSON 文件只作为兼容镜像。"""
    conn = get_connection()
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_cache_snapshots'").fetchone():
        return None
    canonical_path = os.path.normcase(os.path.abspath(os.fspath(cache_file)))
    row = conn.execute(
        """SELECT summary_json FROM strategy_cache_snapshots
           WHERE json_extract(CASE WHEN json_valid(summary_json) THEN summary_json ELSE '{}' END,
                              '$._authoritative') = 1
             AND json_extract(CASE WHEN json_valid(summary_json) THEN summary_json ELSE '{}' END,
                              '$._cache_file') = ?
             AND COALESCE(json_extract(CASE WHEN json_valid(summary_json) THEN summary_json ELSE '{}' END,
                                       '$._invalidated'), 0) != 1
           ORDER BY snapshot_id DESC LIMIT 1""",
        (canonical_path,),
    ).fetchone()
    return json.loads(row['summary_json']) if row else None


def invalidate_published_snapshots(cache_file) -> None:
    """参数变更使当前缓存失效，但保留历史发布关系供复盘与审计。"""
    conn = get_connection()
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='strategy_cache_snapshots'").fetchone():
        return
    canonical_path = os.path.normcase(os.path.abspath(os.fspath(cache_file)))
    conn.execute(
        """UPDATE strategy_cache_snapshots
           SET summary_json = json_set(summary_json, '$._invalidated', json('true'))
           WHERE json_extract(CASE WHEN json_valid(summary_json) THEN summary_json ELSE '{}' END,
                              '$._authoritative') = 1
             AND json_extract(CASE WHEN json_valid(summary_json) THEN summary_json ELSE '{}' END,
                              '$._cache_file') = ?""",
        (canonical_path,),
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
        f"SELECT * FROM strategy_cache_snapshots{where} ORDER BY generated_at DESC, snapshot_id DESC LIMIT 1",
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


def get_available_trade_dates(limit: int = 30, strategy_filter: str = None) -> list[str]:
    """获取有结果的日期列表，优先使用信号日期，缺失时回退到缓存交易日"""
    conn = get_connection()
    date_expr = "COALESCE(NULLIF(signal_date, ''), trade_date)"
    cte_sql, params = _build_latest_results_cte(strategy_filter=strategy_filter)
    rows = conn.execute(
        f"""{cte_sql} SELECT DISTINCT {date_expr} AS result_date
            FROM ranked_results
            WHERE row_num = 1 AND {date_expr} IS NOT NULL AND {date_expr} != ''
            ORDER BY result_date DESC
            LIMIT ?""",
        params + [limit],
    ).fetchall()
    return [r['result_date'] for r in rows]
