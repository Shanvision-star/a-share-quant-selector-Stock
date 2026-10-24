"""用独立进程验证桌面退出后的 Windows 子进程回收及 spawn 入口隔离。"""

import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_job_object_failure_keeps_desktop_available_with_serial_scan(monkeypatch, capsys):
    from scripts import desktop_process_guard as guard

    def blocked_assignment():
        raise OSError(5, "outer job policy denied assignment")

    monkeypatch.setattr(guard, "attach_process_tree_lifetime", blocked_assignment)
    monkeypatch.setenv("QUANT_SCAN_DISABLE_PROCESS", "0")
    assert guard.configure_process_tree_lifetime() is False
    assert os.environ["QUANT_SCAN_DISABLE_PROCESS"] == "1"
    assert "策略扫描已降级为串行" in capsys.readouterr().err


@pytest.mark.parametrize("exceptional_exit", [False, True])
def test_backend_lifespan_cancels_scan_on_every_exit(monkeypatch, exceptional_exit):
    import asyncio
    from web.backend import main
    from web.backend.services import data_service, strategy_scan
    from web.backend.services.workspace_agent import workspace_agent

    canceled = []
    monkeypatch.setattr(main, "init_database", lambda: None)
    monkeypatch.setattr(workspace_agent.store, "init", lambda **kwargs: None)
    monkeypatch.setattr(data_service, "mark_stale_update_runs_interrupted", lambda: 0)
    monkeypatch.setattr(main.stock, "trigger_metric_snapshot_prewarm", lambda: None)
    monkeypatch.setattr(strategy_scan, "cancel_active_scans", lambda: canceled.append(True))

    async def exercise():
        async with main.lifespan(main.app):
            assert canceled == []
            if exceptional_exit:
                raise RuntimeError("fixture shutdown")

    if exceptional_exit:
        with pytest.raises(RuntimeError, match="fixture shutdown"):
            asyncio.run(exercise())
    else:
        asyncio.run(exercise())
    assert canceled == [True]


def test_spawn_import_does_not_start_desktop_backend(tmp_path):
    code = (
        "import runpy, sys; "
        f"sys.path.insert(0, {str(ROOT)!r}); "
        "runpy.run_module('scripts.run_desktop_backend', run_name='__mp_main__'); "
        "print('SPAWN_IMPORT_ONLY')"
    )
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SPAWN_IMPORT_ONLY"
    assert not (tmp_path / "data/desktop-runtime.json").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object 生命周期")
@pytest.mark.parametrize("force_exit", [False, True])
def test_windows_backend_exit_reaps_spawned_worker(tmp_path, force_exit):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    code = "\n".join([
        "import subprocess, sys",
        f"sys.path.insert(0, {str(ROOT)!r})",
        "from scripts.desktop_process_guard import attach_process_tree_lifetime",
        "assert attach_process_tree_lifetime() is True",
        "assert attach_process_tree_lifetime() is True",
        "child = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(90)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)",
        "print(child.pid, flush=True)",
        "sys.stdin.readline()",
    ])
    owner = subprocess.Popen([sys.executable, "-B", "-u", "-c", code], cwd=tmp_path,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    child_handle = None
    try:
        ready = queue.Queue()
        reader = threading.Thread(target=lambda: ready.put(owner.stdout.readline()), daemon=True)
        reader.start()
        line = ready.get(timeout=10).decode().strip()
        if not line:
            owner.wait(timeout=5)
            pytest.fail(owner.stderr.read().decode(errors="replace"))
        child_handle = kernel.OpenProcess(0x00100001, False, int(line))
        assert child_handle, ctypes.WinError(ctypes.get_last_error())
        assert kernel.WaitForSingleObject(child_handle, 0) == 258
        if force_exit:
            owner.kill()
        else:
            owner.stdin.close()
        owner.wait(timeout=10)
        assert kernel.WaitForSingleObject(child_handle, 5000) == 0, "后端退出后扫描 worker 仍然存活"
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        if child_handle:
            if kernel.WaitForSingleObject(child_handle, 0) == 258:
                kernel.TerminateProcess(child_handle, 1)
            kernel.CloseHandle(child_handle)
        for stream in (owner.stdin, owner.stdout, owner.stderr):
            if stream and not stream.closed:
                stream.close()
