"""SQLite 数据库服务 - 初始化、连接管理、schema 建表"""
import sqlite3
import threading
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
DB_PATH = project_root / "data" / "web_strategy_cache.db"

_local = threading.local()

SCHEMA_VERSION = 1


def get_connection() -> sqlite3.Connection:
    """获取当前线程的 SQLite 连接（线程安全，每线程一个连接）"""
    conn = getattr(_local, 'conn', None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        _local.conn = conn
    return conn


def init_database():
    """初始化数据库 schema（幂等操作）"""
    conn = get_connection()
    cursor = conn.cursor()

    # 表 1: strategy_runs - 作业运行记录
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_runs (
            run_id TEXT PRIMARY KEY,
            run_type TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            strategy_filter TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            stage TEXT,
            message TEXT,
            processed_count INTEGER DEFAULT 0,
            total_count INTEGER DEFAULT 0,
            matched_count INTEGER DEFAULT 0,
            error_message TEXT,
            host TEXT
        )
    """)

    # 表 2: strategy_run_events - 作业事件流
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_run_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            strategy_filter TEXT,
            strategy_name TEXT,
            progress INTEGER,
            message TEXT,
            payload_json TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # 表 3: strategy_results - 正式结果
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            strategy_filter TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            code TEXT NOT NULL,
            name TEXT,
            category TEXT,
            signal_date TEXT,
            trigger_price REAL,
            close REAL,
            j_value REAL,
            similarity_score REAL,
            reason TEXT,
            signal_json TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # 表 4: strategy_cache_snapshots - 缓存摘要
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_cache_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            strategy_filter TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            total_results INTEGER DEFAULT 0,
            available_groups_json TEXT,
            group_totals_json TEXT,
            summary_json TEXT
        )
    """)

    # 表 5: app_meta - 应用元信息
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # 索引
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_trade_date ON strategy_runs(trade_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_started_at ON strategy_runs(started_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_run_id ON strategy_run_events(run_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_created_at ON strategy_run_events(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_trade_date ON strategy_results(trade_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_trade_strategy ON strategy_results(trade_date, strategy_filter)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_code ON strategy_results(code)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_run_id ON strategy_results(run_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_run_id ON strategy_cache_snapshots(run_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_trade_date ON strategy_cache_snapshots(trade_date)")

    # 唯一约束：同一次运行中同一股票同一策略同一信号日期同一分类只能有一条
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_results_unique
        ON strategy_results(run_id, strategy_filter, code, signal_date, category)
    """)

    # 记录 schema version
    cursor.execute(
        "INSERT OR REPLACE INTO app_meta(key, value) VALUES (?, ?)",
        ('schema_version', str(SCHEMA_VERSION))
    )

    conn.commit()


# 模块加载时自动初始化
init_database()
