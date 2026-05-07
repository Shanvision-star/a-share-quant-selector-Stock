"""验证回测异步任务服务的提交、完成和失败记录。"""

import time

from web.backend.services.backtest_job_service import BacktestJobManager


def test_backtest_job_manager_returns_task_status_and_result():
    """任务提交后应立即返回 task_id，后台完成后可查询结果。"""
    def slow_runner(params):
        time.sleep(0.02)
        return {"summary": {"trade_count": 1}, "params": params}

    manager = BacktestJobManager(
        runner=slow_runner,
        max_workers=1,
    )

    submitted = manager.submit({"start_date": "2026-04-24", "end_date": "2026-04-24"})

    assert submitted["task_id"]
    assert submitted["status"] in {"queued", "running"}

    task = manager.wait(submitted["task_id"], timeout=2)

    assert task["status"] == "done"
    assert task["result"]["summary"]["trade_count"] == 1
    assert task["finished_at"]

    fetched = manager.get(submitted["task_id"])
    assert fetched["status"] == "done"
    assert fetched["result"]["params"]["start_date"] == "2026-04-24"


def test_backtest_job_manager_records_failure_message():
    """后台异常不能吞掉，应记录 failed 状态和错误消息供前端展示。"""
    def fail_runner(params):
        time.sleep(0.01)
        raise RuntimeError("boom")

    manager = BacktestJobManager(runner=fail_runner, max_workers=1)

    submitted = manager.submit({"start_date": "2026-04-24", "end_date": "2026-04-24"})
    task = manager.wait(submitted["task_id"], timeout=2)

    assert task["status"] == "failed"
    assert "boom" in task["error"]
    assert task["finished_at"]
