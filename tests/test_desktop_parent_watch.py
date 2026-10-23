"""真实子进程管道验证桌面父进程存活与EOF退出，不启动业务后端。"""

from pathlib import Path
import queue
import threading
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize("send_bytes", [False, True])
def test_open_parent_pipe_keeps_child_alive_and_eof_exits(send_bytes):
    root = Path(__file__).resolve().parents[1]
    script = r'''
import sys
import threading
import time
from types import SimpleNamespace
from scripts.run_desktop_backend import watch_parent
server = SimpleNamespace(should_exit=False)
thread = threading.Thread(target=watch_parent, args=(server,), daemon=True)
thread.start()
print("PARENT_PIPE_OPEN", flush=True)
while not server.should_exit:
    time.sleep(.01)
print("PARENT_PIPE_EOF", flush=True)
'''
    process = subprocess.Popen([sys.executable, "-B", "-u", "-c", script], cwd=root,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        ready = queue.Queue()
        reader = threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True)
        reader.start()
        assert ready.get(timeout=8).decode().strip() == "PARENT_PIPE_OPEN"
        reader.join(timeout=1)
        if send_bytes:
            process.stdin.write(b"ignored-parent-message")
            process.stdin.flush()
        # 保持真实匿名管道打开，覆盖Windows PeekNamedPipe分支及有字节消费。
        time.sleep(.5)
        assert process.poll() is None
        process.stdin.close()
        process.wait(timeout=8)
        stdout = process.stdout.read().decode()
        stderr = process.stderr.read().decode()
        assert process.returncode == 0, stderr
        assert "PARENT_PIPE_EOF" in stdout
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
