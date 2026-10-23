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


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    action: Literal["update", "backtest", "tracking"]
    confirmed: bool = False
    parameters: dict = Field(default_factory=dict)


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
                result = request_state(kind, request_id, result, persist=False)
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


def request_state(kind, request_id, result=None, persist=True):
    init_requests()
    if result is None:
        row = get_connection().execute("SELECT payload FROM workspace_agent_requests WHERE kind=? AND request_id=?", (kind, request_id)).fetchone()
        if not row:
            raise KeyError(request_id)
        result = json.loads(row[0])
    if not result or result.get("request_state"):
        if not result:
            result = {"request_state": "interrupted", "error": "旧版占位缺少拥有者，禁止自动重放"}
        elif result["request_state"] == "processing" and not process_alive(result.get("owner_pid")):
            result.update(request_state="interrupted", error="提交进程已退出；不会自动重放", recovered_at=now())
        result.update(kind=kind, request_id=request_id)
        if persist:
            complete_request(kind, request_id, result)
    return result


def complete_request(kind, request_id, result):
    conn = get_connection()
    conn.execute("UPDATE workspace_agent_requests SET payload=? WHERE kind=? AND request_id=?", (json.dumps(result, ensure_ascii=False), kind, request_id))
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
            return self._submit(request)

    def _submit(self, request):
        init_requests()
        conn = get_connection()
        conn.execute("CREATE TABLE IF NOT EXISTS workspace_action_audit (event_id TEXT PRIMARY KEY, created_at TEXT, request_id TEXT, event TEXT, payload TEXT)")
        conn.execute("INSERT INTO workspace_action_audit VALUES (?,?,?,?,?)", (uuid4().hex, now(), request.request_id, "requested" if request.confirmed else "confirmation_rejected", json.dumps(request.model_dump(mode="json"), ensure_ascii=False)))
        conn.commit()
        if not request.confirmed:
            raise ValueError("需要明确 confirmed 才可执行业务写操作")
        params = self.validate(request)
        if len([x for x in self.recent() if x["created_at"][:16] == now()[:16]]) >= 12:
            existing = next((x for x in self.recent() if x["request_id"] == request.request_id), None)
            if not existing:
                raise ValueError("操作频率过高，请稍后重试")
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
        allowed = {"target_date", "auto_rebuild", "pipeline", "allow_intraday_fast", "init_if_empty", "strategies"}
        if set(params) - allowed:
            raise ValueError("未知更新参数")
        if params.get("target_date"):
            date.fromisoformat(params["target_date"])
        for key in allowed - {"target_date", "strategies"}:
            if key in params and not isinstance(params[key], bool):
                raise ValueError("更新开关必须是布尔值")
        if params.get("strategies") is not None and (not isinstance(params["strategies"], list) or any(s not in {"b1","b2","bowl","brick","zettaranc"} for s in params["strategies"])):
            raise ValueError("未知策略")
        return params

    def update(self, item, params):
        async def consume():
            from .data_service import run_data_update
            terminal = False
            async for message in run_data_update(**params):
                data = message["data"]
                item["business_id"] = data.get("run_id") or item["business_id"]
                item["result"] = data
                status = data.get("status")
                if message["event"] == "error" or status in ("error", "partial", "busy"):
                    item.update(status="failed", error=data.get("message", status))
                    terminal = True
                elif message["event"] == "job_complete" and status == "done":
                    item["status"] = "completed"
                    terminal = True
                item["events"].append({"at": now(), "type": message["event"], "status": status})
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
        items = [json.loads(row[0]) for row in rows if json.loads(row[0]).get("action_id")]
        for item in items:
            if item["kind"] == "update" and item["status"] in ("running", "queued") and not process_alive(item.get("owner_pid")):
                from .strategy_result_repository import get_run
                business = get_run(item["business_id"]) if item.get("business_id") else None
                status = {"done": "completed", "error": "failed", "interrupted": "interrupted"}.get((business or {}).get("status"), "interrupted")
                item.update(status=status, result=business, error=None if status == "completed" else (business or {}).get("message") or "拥有更新任务的后端进程已退出，请核对业务历史")
                item["events"].append({"at": now(), "type": "owner_interrupted"})
                self.save(item)
        return items

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
