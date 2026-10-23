"""在pytest收集前隔离默认SQLite，包括数据库模块自身的导入初始化。"""

import importlib
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path


def pytest_configure(config):
    temporary = tempfile.TemporaryDirectory(prefix="quant-pytest-sqlite-")
    target = Path(temporary.name) / "collection-cache.db"
    user_database = Path(__file__).resolve().parent / "data" / "web_strategy_cache.db"
    module_name = "web.backend.services.sqlite_service"
    first_import = module_name not in sys.modules
    original_connect = sqlite3.connect

    def isolated_bootstrap_connect(database, *args, **kwargs):
        # sqlite_service模块尾部会立即建表，必须在导入它之前接管首次连接。
        if str(database) != ":memory:" and Path(database).resolve() == user_database:
            database = str(target)
        return original_connect(database, *args, **kwargs)

    sqlite3.connect = isolated_bootstrap_connect
    try:
        service = importlib.import_module(module_name)
    finally:
        sqlite3.connect = original_connect
    original_local = service._local
    if first_import:
        connection = getattr(original_local, "conn", None)
        if connection is not None:
            connection.close()
        original_local = threading.local()
    config._quant_sqlite_isolation = (temporary, service.DB_PATH, original_local)
    service.DB_PATH = target
    service._local = threading.local()


def pytest_unconfigure(config):
    state = getattr(config, "_quant_sqlite_isolation", None)
    if state is None:
        return
    service = sys.modules["web.backend.services.sqlite_service"]
    temporary, original_path, original_local = state
    try:
        connection = getattr(service._local, "conn", None)
        if connection is not None:
            connection.close()
    finally:
        service.DB_PATH = original_path
        service._local = original_local
        temporary.cleanup()
