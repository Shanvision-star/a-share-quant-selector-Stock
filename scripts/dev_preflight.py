"""Web 开发服务器启动前检查，阻止端口占用和前后端版本错配。"""

from __future__ import annotations

import argparse
import socket
import subprocess
from pathlib import Path


def _git_output(project_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def collect_preflight_errors(project_root: Path, ports: tuple[int, ...]) -> list[str]:
    project_root = project_root.resolve()
    frontend_root = project_root / "web" / "frontend"
    required_paths = (
        project_root / ".venv" / "Scripts" / "python.exe",
        frontend_root / "package.json",
    )
    errors = [f"缺少启动依赖: {path}" for path in required_paths if not path.exists()]

    try:
        gitlink = _git_output(project_root, "ls-files", "-s", "--", "web/frontend")
        parts = gitlink.split()
        if len(parts) < 2 or parts[0] != "160000":
            errors.append("根仓库未记录 web/frontend gitlink。")
        elif frontend_root.exists():
            actual = _git_output(frontend_root, "rev-parse", "HEAD")
            expected = parts[1]
            if actual != expected:
                errors.append(
                    "前端子仓版本与根仓库不一致: "
                    f"期望 {expected[:8]}，实际 {actual[:8]}。"
                )
    except (OSError, subprocess.CalledProcessError) as exc:
        errors.append(f"无法校验前端子仓版本: {exc}")

    for port in ports:
        if not _port_available("127.0.0.1", port):
            errors.append(f"端口 {port} 已被占用，请先关闭旧服务窗口。")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Web 开发服务器启动条件。")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--ports", type=int, nargs="+", default=[8001, 5173])
    args = parser.parse_args()

    errors = collect_preflight_errors(args.project_root, tuple(args.ports))
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1
    print("[OK] 后端、前端目录、gitlink 和端口检查通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
