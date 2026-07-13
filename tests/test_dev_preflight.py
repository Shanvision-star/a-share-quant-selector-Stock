"""开发服务器启动前检查回归测试。"""

from pathlib import Path

from scripts import dev_preflight


def _prepare_runtime_paths(project_root: Path) -> None:
    python_exe = project_root / ".venv" / "Scripts" / "python.exe"
    python_exe.parent.mkdir(parents=True)
    python_exe.touch()
    package_json = project_root / "web" / "frontend" / "package.json"
    package_json.parent.mkdir(parents=True)
    package_json.write_text("{}", encoding="utf-8")


def test_preflight_accepts_matching_frontend_and_free_ports(tmp_path, monkeypatch):
    _prepare_runtime_paths(tmp_path)

    def fake_git_output(cwd: Path, *args: str) -> str:
        if args[0] == "ls-files":
            return "160000 abcdef1234567890 0\tweb/frontend"
        return "abcdef1234567890"

    monkeypatch.setattr(dev_preflight, "_git_output", fake_git_output)
    monkeypatch.setattr(dev_preflight, "_port_available", lambda host, port: True)

    assert dev_preflight.collect_preflight_errors(tmp_path, (8001, 5173)) == []


def test_preflight_reports_revision_mismatch_and_busy_port(tmp_path, monkeypatch):
    _prepare_runtime_paths(tmp_path)

    def fake_git_output(cwd: Path, *args: str) -> str:
        if args[0] == "ls-files":
            return "160000 abcdef1234567890 0\tweb/frontend"
        return "9999991234567890"

    monkeypatch.setattr(dev_preflight, "_git_output", fake_git_output)
    monkeypatch.setattr(dev_preflight, "_port_available", lambda host, port: port != 8001)

    errors = dev_preflight.collect_preflight_errors(tmp_path, (8001, 5173))

    assert any("前端子仓版本" in error for error in errors)
    assert any("端口 8001" in error for error in errors)
