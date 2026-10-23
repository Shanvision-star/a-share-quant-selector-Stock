"""Codex 共用的 HTTP 客户端与 JSON 命令行；自动发现当前桌面实例。"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import sys
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]


def run_endpoint(run_id: str, suffix: str = "") -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("run_id 必须是后端返回的 32 位标识")
    return f"agent/runs/{run_id}{suffix}"


def request(method: str, endpoint: str, payload: dict | None = None) -> dict:
    runtime = {}
    base = os.getenv("QUANT_API_URL")
    if not base:
        runtime_path = Path(os.getenv("QUANT_RUNTIME_FILE", str(ROOT / "data" / "desktop-runtime.json")))
        if runtime_path.exists():
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        base = runtime.get("base_url", "http://127.0.0.1:8001")
    parsed = urlparse(base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1") or parsed.username or parsed.password:
        raise ValueError("工具仅允许连接本地回环 HTTP 服务")
    token = os.getenv("QUANT_API_TOKEN") or runtime.get("token", "")
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        response = client.request(method, "/api/" + endpoint, json=payload, headers={"X-Quant-Token": token})
        if response.is_error:
            detail = response.json().get("detail", "请求失败")
            raise ValueError(f"HTTP {response.status_code}: {detail}")
        return response.json()


def main():
    parser = argparse.ArgumentParser(description="量化工作台 JSON 工具")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "capabilities", "runs", "active"):
        commands.add_parser(name)
    run = commands.add_parser("run")
    run.add_argument("question")
    run.add_argument("--task", choices=["candidates", "tracking", "reviews", "market"], default="candidates")
    run.add_argument("--mode", choices=["local", "model", "codex"], default="local")
    run.add_argument("--code")
    run.add_argument("--date")
    run.add_argument("--limit", type=int, default=20)
    for name in ("get", "cancel"):
        commands.add_parser(name).add_argument("run_id")
    save = commands.add_parser("save-review")
    save.add_argument("run_id")
    save.add_argument("date")
    save.add_argument("--confirm", action="store_true")
    analysis = commands.add_parser("submit-analysis")
    analysis.add_argument("run_id")
    analysis.add_argument("payload", help="结构化分析 JSON 文件")
    action = commands.add_parser("action")
    action.add_argument("payload", help="白名单操作 JSON 文件，必须显式 confirmed")
    commands.add_parser("action-get").add_argument("action_id")
    state = commands.add_parser("request-state")
    state.add_argument("kind", choices=["analysis", "action"])
    state.add_argument("request_id")
    args = parser.parse_args()
    try:
        if args.command in ("status", "capabilities", "runs", "active"):
            result = request("GET", {"status": "system/status", "capabilities": "agent/capabilities", "runs": "agent/runs", "active": "agent/active"}[args.command])
        elif args.command == "request-state":
            from urllib.parse import quote
            result = request("GET", f"agent/requests/{args.kind}/{quote(args.request_id, safe='')}")
        elif args.command in ("submit-analysis", "action"):
            payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
            endpoint = run_endpoint(args.run_id, "/analysis") if args.command == "submit-analysis" else "agent/actions"
            result = request("POST", endpoint, payload)
        elif args.command == "action-get":
            result = request("GET", run_endpoint(args.action_id).replace("agent/runs/", "agent/actions/"))
        elif args.command == "run":
            result = request("POST", "agent/runs", {"question": args.question, "task": args.task, "mode": args.mode, "code": args.code, "trade_date": args.date, "limit": args.limit})
        elif args.command == "save-review":
            result = request("POST", run_endpoint(args.run_id, "/review"), {"review_date": args.date, "confirmed": args.confirm})
        elif args.command == "cancel":
            result = request("POST", run_endpoint(args.run_id, "/cancel"))
        else:
            result = request("GET", run_endpoint(args.run_id))
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, httpx.HTTPError) as exc:
        # 不输出请求 headers 或发现文件，避免凭证进入模型上下文。
        print(json.dumps({"error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
