"""桌面分发检查：代码白名单和用户配置边界不得因打包而失效。"""

import importlib.util
import csv
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

import pytest


def build_module():
    path = Path(__file__).resolve().parents[1] / "scripts/build_desktop_runtime.py"
    spec = importlib.util.spec_from_file_location("desktop_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_allowlist_excludes_private_runtime_data(tmp_path):
    module = build_module()
    for name in ("web/backend/main.py", "utils/technical.py", "web/frontend/dist/index.html", "config/llm.yaml",
                 "data/web_strategy_cache.db", "data/review_library/private.md", "third_party/zettaranc/.env",
                 "third_party/zettaranc/data/private.py", "third_party/zettaranc/modules/cli.py"):
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("fixture", encoding="utf-8")
    files = {p.relative_to(tmp_path).as_posix() for p in module.source_files(tmp_path) if p.exists()}
    assert "web/backend/main.py" in files
    assert "third_party/zettaranc/modules/cli.py" in files
    assert not any(name.startswith(("data/", "config/")) or "/data/" in name or name.endswith(".env") for name in files)


def test_build_cleanup_rejects_workspace_and_external_directories(tmp_path, monkeypatch):
    module = build_module()
    monkeypatch.setattr(module, "BUILD", tmp_path / "build")
    protected = tmp_path / "user-data"
    protected.mkdir()
    import pytest
    with pytest.raises(ValueError):
        module.reset_build_dir(protected)
    with pytest.raises(ValueError):
        module.reset_build_dir(tmp_path / "build")
    assert protected.exists()


def test_bundle_includes_backtest_entry_and_history_subprocess_dependency():
    module = build_module()
    files = {p.relative_to(module.ROOT).as_posix() for p in module.source_files(module.ROOT) if p.exists()}
    assert {"scripts/run_zettaranc_backtest.py", "scripts/extend_history_baostock.py",
            "scripts/backfill_history.py", "scripts/desktop_process_guard.py"} <= files
    assert {"strategy/zettaranc_combo.py", "utils/csv_manager.py", "utils/akshare_fetcher.py"} <= files
    assert "web/backend/services/strategy_scan.py" in files


def test_embedded_python_runs_bundled_zettaranc_and_history_dry_run(tmp_path):
    executable = os.environ.get("QUANT_EMBEDDED_PYTHON")
    if not executable:
        pytest.skip("显式设置 QUANT_EMBEDDED_PYTHON 才执行内置解释器离线验收")
    module = build_module()
    app = tmp_path / "app"
    for source in module.source_files(module.ROOT):
        relative = source.relative_to(module.ROOT)
        if source.is_file() and source.suffix == ".py" and relative.parts[0] != "third_party":
            target = app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (app / "config").mkdir()
    (app / "config/strategy_params.yaml").write_text("{}", encoding="utf-8")
    sample = app / "data/00/000001.csv"
    sample.parent.mkdir(parents=True)
    with sample.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "open", "close", "high", "low", "volume", "amount", "total_mv"])
        for index in reversed(range(180)):
            close = 10 + math.sin(index / 8) / 10 + index / 1000
            writer.writerow([(date(2025, 1, 1) + timedelta(days=index)).isoformat(), close - .1, close,
                             close + .2, close - .2, 100000, 100000000, 10000000000])
    code = "\n".join([
        "import json, sys",
        f"sys.path.insert(0, {str(app)!r})",
        "assert sys.flags.isolated == 1, 'must use embedded _pth isolation'",
        "from web.backend.routers import zettaranc as route",
        "response = route.backtest_run(route.BacktestRunIn(start='2025-05-01', end='2025-06-29', limit=1, j_buy=200, vol_ratio=.1))",
        "latest = route.backtest_latest()",
        "assert response['success'] and latest['data'] == response['data']",
        "assert response['data']['config']['codes_run'] == 1",
        "assert response['data']['skipped_codes'] == 0",
        "assert response['data']['total_trades'] > 0",
        "print(json.dumps({'success': True, 'isolated': sys.flags.isolated}))",
    ])
    result = subprocess.run([executable, "-c", code], cwd=tmp_path,
                            capture_output=True, text=True, errors="replace", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"success": True, "isolated": 1}
    assert (app / "output/zettaranc_backtest_latest.json").is_file()
    # dry-run 真正经 extend 的 subprocess 调用 backfill；在创建 fetcher 前返回，不请求行情。
    result = subprocess.run([executable, str(app / "scripts/extend_history_baostock.py"), "--dry-run"],
                            cwd=tmp_path, capture_output=True, text=True, errors="replace", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[DRY-RUN]" in result.stdout and "000001" in result.stdout
