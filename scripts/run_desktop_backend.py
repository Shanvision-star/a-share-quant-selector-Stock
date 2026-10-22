"""桌面专用入口：随机回环端口、实例凭证发现及父进程退出清理。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import uvicorn
    from web.backend.main import app

    token = os.environ.get("QUANT_DESKTOP_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("桌面启动缺少实例认证令牌")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    runtime_path = ROOT / "data" / "desktop-runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime = {"base_url": f"http://127.0.0.1:{port}", "pid": os.getpid(), "token": token}
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
    # 发现文件只供当前用户本地 Codex 使用，禁止写入日志或纳入 Git。
    if os.name != "nt":
        runtime_path.chmod(0o600)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=5))

    def parent_watch():
        sys.stdin.buffer.read()
        server.should_exit = True

    threading.Thread(target=parent_watch, daemon=True, name="desktop-parent-watch").start()
    print(json.dumps({"port": port, "pid": os.getpid()}), flush=True)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        if runtime_path.exists():
            try:
                if json.loads(runtime_path.read_text(encoding="utf-8")).get("pid") == os.getpid():
                    runtime_path.unlink()
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    main()
