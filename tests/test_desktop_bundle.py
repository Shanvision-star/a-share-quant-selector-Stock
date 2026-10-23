"""桌面分发检查：代码白名单和用户配置边界不得因打包而失效。"""

import importlib.util
from pathlib import Path


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
