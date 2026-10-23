"""Codex stdio MCP：将研究与整理接入同一审计后端，不向 stdout 写日志。"""

from typing import Literal
from pathlib import Path
import sys

# Windows 嵌入式 Python 的 _pth 隔离不会自动加入脚本目录；固定项目根以支持桌面内置解释器。
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

try:
    from quant_tools import request, run_endpoint
except ModuleNotFoundError:
    from scripts.quant_tools import request, run_endpoint

mcp = FastMCP("A-share Quant", instructions="先读取真实来源和日期再分析。研究运行会持久化，模型模式会调用配置的供应商。保存复盘仅在用户明确授权后 confirmed=true。没有交易执行权限。")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


@mcp.tool(annotations=READ)
def quant_status() -> dict:
    """检查现有数据、策略和跟踪运行状态，不触发更新。"""
    return request("GET", "system/status")


@mcp.tool(annotations=READ)
def quant_capabilities() -> dict:
    """查看本机 Agent 的任务与模型配置状态，不返回密钥。"""
    return request("GET", "agent/capabilities")


@mcp.tool(annotations=WRITE)
def quant_research(question: str, task: Literal["candidates", "tracking", "reviews"] = "candidates",
                   code: str | None = None, trade_date: str | None = None, limit: int = 20,
                   mode: Literal["local", "model"] = "local") -> dict:
    """建立可追踪研究任务。local 取证供 Codex 分析，model 调用已配置模型；返回 run_id 后用 quant_run 获取结果。"""
    return request("POST", "agent/runs", {"question": question, "task": task, "code": code, "trade_date": trade_date, "limit": limit, "mode": mode})


@mcp.tool(annotations=READ)
def quant_runs() -> dict:
    """列出近期运行，用于数据整理和任务追踪。"""
    return request("GET", "agent/runs")


@mcp.tool(annotations=READ)
def quant_run(run_id: str) -> dict:
    """取得输入、结果、原始证据快照、SHA256、模型用量和失败记录。"""
    return request("GET", run_endpoint(run_id))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def quant_cancel(run_id: str) -> dict:
    """取消未完成任务；已发出的模型请求可能仍消耗 token。"""
    return request("POST", run_endpoint(run_id, "/cancel"))


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False))
def quant_save_review(run_id: str, review_date: str, confirmed: bool = False) -> dict:
    """用户明确确认后追加报告到指定日期复盘，幂等且保留原文。"""
    return request("POST", run_endpoint(run_id, "/review"), {"review_date": review_date, "confirmed": confirmed})


@mcp.tool(annotations=WRITE)
def quant_submit_analysis(run_id: str, request_id: str, source_hashes: dict[str, str], report: dict,
                          model: str, prompt_version: str, author: str = "Codex", provider: str = "openai") -> dict:
    """把基于父运行来源的 Codex 结构化报告存为独立子运行，保留原取证。"""
    return request("POST", run_endpoint(run_id, "/analysis"), {"request_id": request_id, "source_hashes": source_hashes,
        "report": report, "model": model, "prompt_version": prompt_version, "author": author, "provider": provider})


@mcp.tool(annotations=WRITE)
def quant_action(request_id: str, action: Literal["update", "backtest", "tracking"], parameters: dict, confirmed: bool = False) -> dict:
    """显式确认后调用现有数据更新、回测或跟踪服务。queued/running 仅代表受理，用 quant_action_get 查询业务终态。"""
    return request("POST", "agent/actions", {"request_id": request_id, "action": action, "parameters": parameters, "confirmed": confirmed})


@mcp.tool(annotations=READ)
def quant_action_get(action_id: str) -> dict:
    """查询受控操作的真实业务 ID、状态和审计事件。"""
    return request("GET", run_endpoint(action_id).replace("agent/runs/", "agent/actions/"))


@mcp.tool(annotations=READ)
def quant_active_tasks() -> dict:
    """查询研究、数据更新和回测活动任务。"""
    return request("GET", "agent/active")


@mcp.tool(annotations=READ)
def quant_request_state(kind: Literal["analysis", "action"], request_id: str) -> dict:
    """查询幂等提交状态，区分processing与interrupted；中断不自动重放。"""
    from urllib.parse import quote
    return request("GET", f"agent/requests/{kind}/{quote(request_id, safe='')}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
