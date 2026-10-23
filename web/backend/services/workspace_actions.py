"""白名单业务操作与外部分析提交的持久化幂等边界。"""

import asyncio
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .sqlite_service import get_connection
from .workspace_agent import AgentReport, now, process_alive


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    source_hashes: dict[str, str]
    report: AgentReport
    author: str = Field(default="Codex", min_length=1, max_length=100)
    provider: str = Field(default="openai", min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)


class UpdateActionParameters(BaseModel):
    """复用数据更新服务的参数默认值，供校验与能力发现共享。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    target_date: str | None = None
    auto_rebuild: bool = True
    pipeline: bool = False
    allow_intraday_fast: bool = False
    init_if_empty: bool = True
    strategies: list[Literal["b1", "b2", "bowl", "brick", "zettaranc"]] | None = None


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    action: Literal["update", "backtest", "tracking", "tracking_refresh"]
    confirmed: bool = False
    parameters: dict = Field(default_factory=dict)


class TrackingRefreshParameters(BaseModel):
    """只接受正式跟踪、报告与复盘标识，不接受仓位或交易字段。"""
    model_config = ConfigDict(extra='forbid')
    tracking_id: str = Field(pattern=r'^trk_[a-f0-9]+$')
    run_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    review_date: date


def init_requests():
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS workspace_agent_requests (kind TEXT, request_id TEXT, fingerprint TEXT, payload TEXT, PRIMARY KEY(kind,request_id))")
    conn.commit()


def claim_request(kind, request_id, payload):
    init_requests()
    conn = get_connection()
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT fingerprint,payload FROM workspace_agent_requests WHERE kind=? AND request_id=?", (kind, request_id)).fetchone()
        if row:
            if row[0] != fingerprint:
                raise ValueError("request_id 已绑定不同请求")
            result = json.loads(row[1])
            if not result or result.get("request_state"):
                result = recovered_request_state(kind, request_id, result)
                conn.execute("UPDATE workspace_agent_requests SET payload=? WHERE kind=? AND request_id=?", (json.dumps(result, ensure_ascii=False), kind, request_id))
                conn.commit()
                raise ValueError(f"request_id={request_id} 状态={result['request_state']}；查询 /api/agent/requests/{kind}/{request_id}，不会重放")
            conn.rollback()
            return result
        conn.execute("INSERT INTO workspace_agent_requests VALUES (?,?,?,?)", (kind, request_id, fingerprint, json.dumps({"request_state": "processing", "owner_pid": os.getpid(), "created_at": now(), "request": payload}, ensure_ascii=False)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def recovered_request_state(kind, request_id, result):
    """纯状态转换；调用方负责事务，不能在占位锁内隐式提交。"""
    if result and not result.get("request_state"):
        return result
    result = dict(result)
    if not result:
        result = {"request_state": "interrupted", "error": "旧版占位缺少拥有者，禁止自动重放"}
    elif result["request_state"] == "processing" and not process_alive(result.get("owner_pid")):
        result.update(request_state="interrupted", error="提交进程已退出；不会自动重放", recovered_at=now())
    return {**result, "kind": kind, "request_id": request_id}


def request_state(kind, request_id):
    init_requests()
    conn = get_connection()
    while True:
        row = conn.execute("SELECT payload FROM workspace_agent_requests WHERE kind=? AND request_id=?", (kind, request_id)).fetchone()
        if not row:
            raise KeyError(request_id)
        original = json.loads(row[0])
        result = recovered_request_state(kind, request_id, original)
        # 活跃占位仅补充响应标识，不写库；恢复使用原payload比较交换，避免覆盖并发完成映射。
        changed = not original or result.get("request_state") != original.get("request_state")
        if not changed:
            return result
        updated = conn.execute("UPDATE workspace_agent_requests SET payload=? WHERE kind=? AND request_id=? AND payload=?", (json.dumps(result, ensure_ascii=False), kind, request_id, row[0]))
        conn.commit()
        if updated.rowcount:
            return result
        # 另一个线程已完成或恢复，重新读取权威结果，不重写旧占位。


def complete_request(kind, request_id, result):
    conn = get_connection()
    conn.execute("UPDATE workspace_agent_requests SET payload=? WHERE kind=? AND request_id=?", (json.dumps(result, ensure_ascii=False), kind, request_id))
    conn.commit()


def audit_attempt(kind, request_id, event, *, parent_id=None, author=None, stage=None, error_type=None):
    """只保存有界标识和失败分类，不保存原参数、模型正文或异常原文中的凭证。"""
    conn = get_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS workspace_action_audit (event_id TEXT PRIMARY KEY, created_at TEXT, request_id TEXT, event TEXT, payload TEXT)")
    payload = {"kind": kind, "parent_id": (parent_id or "")[:128], "author": (author or "")[:100], "stage": stage, "error_type": error_type}
    conn.execute("INSERT INTO workspace_action_audit VALUES (?,?,?,?,?)", (uuid4().hex, now(), request_id[:128], event, json.dumps(payload, ensure_ascii=False)))
    conn.commit()


class ControlledActions:
    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="controlled-update")
        self.lock = threading.Lock()

    def save(self, item):
        complete_request("action", item["request_id"], item)
        return item

    def submit(self, request):
        with self.lock:
            audit_attempt("action", request.request_id, "requested", stage="confirmation")
            try:
                return self._submit(request)
            except Exception as exc:
                audit_attempt("action", request.request_id, "rejected", stage=getattr(self, "stage", "validation"), error_type=type(exc).__name__)
                raise ValueError("操作被拒绝，请核对confirmed、参数、频率和request_id；失败审计已保存") from exc

    def _submit(self, request):
        self.stage = "confirmation"
        if not request.confirmed:
            raise ValueError("需要明确 confirmed 才可执行业务写操作")
        self.stage = "validation"
        params = self.validate(request)
        self.stage = "rate_limit"
        if len([x for x in self.recent() if x["created_at"][:16] == now()[:16]]) >= 12:
            existing = next((x for x in self.recent() if x["request_id"] == request.request_id), None)
            if not existing:
                raise ValueError("操作频率过高，请稍后重试")
        self.stage = "idempotency"
        prior = claim_request("action", request.request_id, request.model_dump(mode="json"))
        if prior:
            return self.get(prior["action_id"])
        item = {"action_id": uuid4().hex, "request_id": request.request_id, "kind": request.action, "status": "running", "business_id": None,
                "owner_pid": os.getpid(), "created_at": now(), "parameters": params,
                "events": [{"at": now(), "type": "confirmed", "confirmed": True}, {"at": now(), "type": "requested"}]}
        self.save(item)
        try:
            # 同种活动写任务只允许一个；幂等请求在此之前返回原任务。
            if any(x["action_id"] != item["action_id"] and x["kind"] == item["kind"] and x["status"] in ("running", "queued", "cancel_requested") for x in (self.get(row["action_id"]) for row in self.recent())):
                raise ValueError("同类操作正在执行，请等待完成")
            if request.action == "backtest":
                from .backtest_job_service import backtest_job_manager
                result = backtest_job_manager.submit(params)
                item.update(business_id=result["task_id"], status=result["status"], result=result)
            elif request.action == "tracking_refresh":
                from .daily_observation import refresh_observation
                result = refresh_observation(**params)
                item.update(business_id=result['tracking_id'], status='completed', result=result)
            elif request.action == "tracking":
                from .tracking_service import tracking_service
                result = tracking_service.create_item(params)
                item.update(business_id=result["tracking_id"], status="completed", result=result)
            else:
                self.pool.submit(self.update, item, params)
                return item
            item["events"].append({"at": now(), "type": "business_result", "status": item["status"]})
        except Exception as exc:
            item.update(status="failed", error=str(exc)[:300])
            item["events"].append({"at": now(), "type": "failed", "error": item["error"]})
        return self.save(item)

    def validate(self, request):
        params = request.parameters
        if request.action == 'tracking_refresh':
            return TrackingRefreshParameters.model_validate(params).model_dump(mode='json')
        if request.action == "backtest":
            from web.backend.routers.backtest import BacktestRequest
            if set(params) - BacktestRequest.model_fields.keys():
                raise ValueError("未知回测参数")
            result = BacktestRequest.model_validate(params).model_dump()
            if result["start_date"] > result["end_date"]:
                raise ValueError("回测开始日期不能晚于结束日期")
            for value in (result["start_date"], result["end_date"]):
                date.fromisoformat(value)
            return result
        if request.action == "tracking":
            from web.backend.routers.tracking import TrackingCreateRequest
            if set(params) - TrackingCreateRequest.model_fields.keys():
                raise ValueError("未知跟踪参数")
            result = TrackingCreateRequest.model_validate(params).model_dump()
            date.fromisoformat(result["signal_date"])
            return result
        result = UpdateActionParameters.model_validate(params).model_dump(exclude_unset=True)
        if result.get("target_date"):
            date.fromisoformat(result["target_date"])
        return result

    def update(self, item, params):
        async def consume():
            from .data_service import run_data_update
            terminal = False
            async for message in run_data_update(**params):
                data = message["data"]
                item["business_id"] = data.get("run_id") or item["business_id"]
                item["result"] = data
                status = data.get("status")
                if message["event"] == "error" or status in ("error", "partial", "busy") or data.get("update_status") in ("partial", "error"):
                    item.update(status="failed", error=data.get("message", status), update_failure=dict(data), update_status=data.get("update_status") or status)
                    terminal = True
                elif message["event"] == "job_complete" and status == "done":
                    if not item.get("update_failure"):
                        item["status"] = "completed"
                    terminal = True
                item["events"].append({"at": now(), "type": message["event"], "status": status, "update_status": data.get("update_status"), "failed": data.get("failed"), "message": str(data.get("message", ""))[:300]})
                self.save(item)
            if not terminal:
                raise ValueError("更新流结束但未返回业务终态")
        try:
            asyncio.run(consume())
        except Exception as exc:
            item.update(status="failed", error=str(exc)[:300])
            item["events"].append({"at": now(), "type": "failed"})
        self.save(item)

    def recent(self):
        init_requests()
        rows = get_connection().execute("SELECT payload FROM workspace_agent_requests WHERE kind='action'").fetchall()
        items = []
        for row in rows:
            item = json.loads(row[0])
            if not item.get("action_id"):
                continue
            if item["kind"] == "backtest" and item["status"] in ("running", "queued", "cancel_requested") and not process_alive(item.get("owner_pid")):
                item = self.recover_backtest(item, row[0])
            items.append(item)
        for item in items:
            if item["kind"] == "update" and item["status"] in ("running", "queued") and not process_alive(item.get("owner_pid")):
                from .strategy_result_repository import get_run, get_run_events
                business = get_run(item["business_id"]) if item.get("business_id") else None
                status = {"done": "completed", "error": "failed", "interrupted": "interrupted"}.get((business or {}).get("status"), "interrupted")
                history = get_run_events(item["business_id"]) if business else []
                partial = item.get("update_failure") or (business or {}).get("update_status") in ("partial", "error") or any(event["event_type"] in ("warning", "update_warning") for event in history)
                if partial:
                    status = "failed"
                    item["update_status"] = "partial"
                item.update(status=status, result=business, error=None if status == "completed" else (business or {}).get("message") or "拥有更新任务的后端进程已退出，请核对业务历史")
                item["events"].append({"at": now(), "type": "owner_interrupted"})
                self.save(item)
        return items

    def recover_backtest(self, item, original_payload):
        """仅恢复死拥有者关联的业务记录，原请求映射保留且不重新提交。"""
        from .backtest_job_service import backtest_job_manager
        business = backtest_job_manager.repository.interrupt_if_active(item["business_id"]) if item.get("business_id") else None
        item.update(status=business["status"] if business else "failed", result=business,
                    error=(business.get("error") or None) if business else "拥有回测任务的后端进程已退出；不会自动重放")
        item["events"].append({"at": now(), "type": "owner_interrupted", "status": item["status"]})
        conn = get_connection()
        # 多实例同时恢复时只允许一个记录事件，避免覆盖另一个读取者已保存的终态。
        changed = conn.execute("UPDATE workspace_agent_requests SET payload=? WHERE kind='action' AND request_id=? AND payload=?",
            (json.dumps(item, ensure_ascii=False), item["request_id"], original_payload))
        conn.commit()
        if changed.rowcount:
            audit_attempt("action", item["request_id"], "owner_interrupted", stage="backtest_recovery")
            return item
        current = conn.execute("SELECT payload FROM workspace_agent_requests WHERE kind='action' AND request_id=?", (item["request_id"],)).fetchone()
        return json.loads(current[0]) if current else item

    def get(self, action_id):
        item = next((x for x in self.recent() if x["action_id"] == action_id), None)
        if not item:
            raise KeyError(action_id)
        if item["kind"] == "backtest" and item["business_id"]:
            from .backtest_job_service import backtest_job_manager
            result = backtest_job_manager.get(item["business_id"])
            if result:
                if item["status"] != result["status"]:
                    item["events"].append({"at": now(), "type": "business_status", "status": result["status"]})
                item.update(status=result["status"], result=result)
                self.save(item)
        return item


controlled_actions = ControlledActions()
