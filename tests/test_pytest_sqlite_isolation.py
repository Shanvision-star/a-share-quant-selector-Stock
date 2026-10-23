"""验证收集期默认数据库隔离，两类测试目录都不能打开用户data库。"""

from pathlib import Path
import subprocess
import sys
import tempfile


def test_default_sqlite_is_temporary_before_test_fixtures():
    from web.backend.services import sqlite_service

    assert sqlite_service.DB_PATH.name == "collection-cache.db"
    assert sqlite_service.DB_PATH.is_relative_to(Path(tempfile.gettempdir()))
    assert sqlite_service._local is not None


def test_collection_imports_cannot_open_user_sqlite():
    root = Path(__file__).resolve().parents[1]
    script = r'''
import pathlib
import sqlite3
import sys
import pytest

root = pathlib.Path.cwd()
original_connect = sqlite3.connect
opened = []
def guarded_connect(database, *args, **kwargs):
    if str(database) != ":memory:":
        target = pathlib.Path(database).resolve()
        if target.is_relative_to(root / "data"):
            raise AssertionError("collection attempted user SQLite access")
        opened.append(target)
    return original_connect(database, *args, **kwargs)
sqlite3.connect = guarded_connect
result = pytest.main(["--collect-only", "-q", "tests/test_backtest_job_service.py", "web/backend/tests/test_config_api_revision.py"])
assert result == 0, result
assert opened and all(path.name == "collection-cache.db" for path in opened), opened
assert all(not path.exists() for path in opened), "session SQLite must be cleaned after collection"
print("COLLECTION_SQLITE_ISOLATED")
'''
    result = subprocess.run([sys.executable, "-B", "-c", script], cwd=root, text=True, capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COLLECTION_SQLITE_ISOLATED" in result.stdout
