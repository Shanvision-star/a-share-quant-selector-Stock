"""桌面专用入口：随机回环端口、实例凭证发现及父进程退出清理。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def wait_for_parent_pipe_eof(stdin_fd: int) -> None:
    """只监测父管道关闭，不持有Windows FILE缓冲锁，避免阻塞后续原生扩展加载。"""
    if os.name != "nt":
        while os.read(stdin_fd, 4096):
            pass
        return

    import ctypes
    from ctypes import wintypes
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    peek = kernel.PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                     ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    peek.restype = wintypes.BOOL
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(stdin_fd))
    while True:
        available = wintypes.DWORD()
        if not peek(handle, None, 0, None, ctypes.byref(available), None):
            error = ctypes.get_last_error()
            if error in (6, 109, 232, 233):
                return
            raise OSError(error, "桌面父进程管道状态读取失败")
        # 桌面协议只用EOF表达退出；只消费已到达字节，绝不发起阻塞FILE读取。
        if available.value and not os.read(stdin_fd, min(available.value, 4096)):
            return
        time.sleep(0.2)


def watch_parent(server, stdin_fd: int | None = None) -> None:
    try:
        wait_for_parent_pipe_eof(sys.stdin.fileno() if stdin_fd is None else stdin_fd)
    except OSError:
        # 管道失效表示父进程不可再控制本服务，应进入已有优雅退出流程。
        pass
    finally:
        server.should_exit = True


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

    threading.Thread(target=watch_parent, args=(server,), daemon=True, name="desktop-parent-watch").start()
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
