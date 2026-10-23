"""在独立副本中验收打包 Python、真实 MCP 与业务闭环，不写用户行情或数据库。"""

import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output" / "desktop-v2" / ("business-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
WORKSPACE = OUTPUT / "workspace"
PYTHON = ROOT / "desktop/build/python/python.exe"
RESULT = {"checks": [], "provider_calls": 0, "fixture": "copied historical CSV + explicitly seeded strategy record"}


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    RESULT["checks"].append(name)


def prepare():
    shutil.copytree(ROOT / "desktop/build/app", WORKSPACE)
    shutil.copytree(ROOT / "desktop/build/defaults/config", WORKSPACE / "config")
    data = WORKSPACE / "data"
    for code in ("000001", "688728", "688392"):
        original = ROOT / "data" / code[:2] / (code + ".csv")
        if original.exists():
            target = data / code[:2] / original.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
    (data / "stock_names.json").write_text(json.dumps({"000001": "平安银行", "688728": "格科微", "688392": "骄成超声"}, ensure_ascii=False), encoding="utf-8")
    fixture = """
import sys
sys.path.insert(0, sys.argv[1])
from web.backend.services.sqlite_service import init_database
from web.backend.services import strategy_result_repository as repo
init_database()
repo.create_run('acceptance-fixture', 'strategy', '2026-08-20', 'b1', total_count=1)
repo.insert_results_batch([dict(run_id='acceptance-fixture',trade_date='2026-08-20',strategy_filter='b1',strategy_name='B1Strategy',code='000001',name='平安银行',signal_date='2026-08-20',reason='验收夹具：验证来源引用，不构成投资建议')])
repo.finish_run('acceptance-fixture','done',matched_count=1,processed_count=1)
"""
    subprocess.run([str(PYTHON), "-c", fixture, str(WORKSPACE)], check=True, capture_output=True)


async def exercise(runtime, env):
    async with httpx.AsyncClient(base_url=runtime["base_url"], headers={"X-Quant-Token": runtime["token"]}, timeout=30, trust_env=False) as http:
        async def api(method, route, **kwargs):
            response = await http.request(method, "/api/" + route, **kwargs)
            response.raise_for_status()
            return response.json()

        check("packaged backend healthy", (await api("GET", "health"))["status"] == "ok")
        mcp_env = {**env, "QUANT_RUNTIME_FILE": str(WORKSPACE / "data/desktop-runtime.json")}
        params = StdioServerParameters(command=str(PYTHON), args=[str(WORKSPACE / "scripts/quant_mcp.py")], env=mcp_env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                check("MCP exposes all twelve tools", len(listed.tools) == 12)

                async def tool(name, **arguments):
                    response = await session.call_tool(name, arguments)
                    if response.isError:
                        raise AssertionError(f"MCP {name}: {response.content}")
                    return response.structuredContent or json.loads(response.content[0].text)

                capabilities = await tool("quant_capabilities")
                check("MCP discovers operation schemas and no trading", set(capabilities["action_schemas"]) == {"update", "backtest", "tracking"} and not capabilities["trading"])
                parent = await tool("quant_research", question="检查平安银行的本地候选记录与日期", code="000001", trade_date="2026-08-20")
                for _ in range(100):
                    parent = await tool("quant_run", run_id=parent["run_id"])
                    if parent["status"] not in ("running", "queued"):
                        break
                    await asyncio.sleep(.1)
                check("stock-scoped research completed with real database evidence", parent["status"] == "completed" and parent["sources"][0]["data"]["items"][0]["code"] == "000001")
                hashes = {source["source_id"]: source["sha256"] for source in parent["sources"]}
                for source in parent["sources"]:
                    check("source SHA256 independently verified", hashlib.sha256(json.dumps(source["data"], ensure_ascii=False, default=str).encode()).hexdigest() == source["sha256"])
                analysis = dict(run_id=parent["run_id"], request_id="acceptance-analysis", source_hashes=hashes,
                    report=dict(summary="平安银行存在一条用于验收的候选记录，信号日期为 2026-08-20。", findings=[dict(text="证据中的 reason 明确标记为验收夹具，因此只能验证追溯链路，不能作为买卖结论。", source_ids=["S1"])], next_steps=["结合独立行情与风险规则复核"], limitations=["历史 CSV 和种子记录，不代表实时市场或模型收益验证"]), model="codex-acceptance-fixture", prompt_version="acceptance-1", author="Codex acceptance")
                child = await tool("quant_submit_analysis", **analysis)
                check("Codex analysis stored as a separate linked run", child["parent_run_id"] == parent["run_id"] and child["run_id"] != parent["run_id"] and child["input"]["mode"] == "external")
                check("analysis retry is idempotent", (await tool("quant_submit_analysis", **analysis))["run_id"] == child["run_id"])
                review = await api("POST", "reviews/2026-08-20")
                body = review["data"]
                await api("PUT", "reviews/2026-08-20", json={key: ("必须保留的既有复盘正文" if key == "body" else body[key]) for key in ("body", "title", "status", "title_source", "tags", "stocks", "version")})
                await tool("quant_save_review", run_id=child["run_id"], review_date="2026-08-20", confirmed=True)
                check("review append retry is idempotent", (await tool("quant_save_review", run_id=child["run_id"], review_date="2026-08-20", confirmed=True))["already_saved"])
                reviews = await api("GET", "reviews?stock=000001")
                check("same-stock review search finds saved analysis", any(item["review_date"] == "2026-08-20" for item in reviews["data"]["items"]))
                saved = (await api("GET", "reviews/2026-08-20"))["data"]
                check("existing review body preserved with single analysis", "必须保留的既有复盘正文" in saved["body"] and saved["body"].count("<!-- agent-run:") == 1)
                tracking_args = dict(request_id="acceptance-tracking", action="tracking", confirmed=True, parameters={"code": "000001", "name": "平安银行", "signal_date": "2026-08-20", "source": "agent", "note": "独立验收数据"})
                tracked = await tool("quant_action", **tracking_args)
                check("controlled tracking actually persisted", tracked["status"] == "completed" and bool(tracked["business_id"]))
                check("tracking retry returns same business object", (await tool("quant_action", **tracking_args))["business_id"] == tracked["business_id"])
                tracking_research = await tool("quant_research", question="检查同股跟踪记录", task="tracking", code="000001")
                for _ in range(100):
                    tracking_research = await tool("quant_run", run_id=tracking_research["run_id"])
                    if tracking_research["status"] == "completed":
                        break
                    await asyncio.sleep(.1)
                check("tracking is available to subsequent research", tracking_research["sources"][0]["data"]["items"][0]["tracking_id"] == tracked["business_id"])
                backtest = await tool("quant_action", request_id="acceptance-backtest", action="backtest", confirmed=True, parameters={"source":"codes", "input_codes":["000001"], "start_date":"2026-08-20", "end_date":"2026-08-28", "codes_fallback_to_start_date":True, "max_candidates":10, "max_runtime_seconds":30})
                for _ in range(200):
                    backtest = await tool("quant_action_get", action_id=backtest["action_id"])
                    if backtest["status"] not in ("running", "queued", "cancel_requested"):
                        break
                    await asyncio.sleep(.3)
                check("real backtest reaches done business state", backtest["status"] == "done")
                check("backtest produced an actual simulated trade", backtest["result"]["summary"]["trade_count"] > 0)
                (OUTPUT / "backtest-result.json").write_text(json.dumps(backtest, ensure_ascii=False, indent=2), encoding="utf-8")
                RESULT["backtest"] = {"action_id": backtest["action_id"], "business_id": backtest["business_id"], "status": backtest["status"]}
                update = await tool("quant_action", request_id="acceptance-update", action="update", confirmed=True, parameters={"target_date":"2026-08-20", "auto_rebuild":False, "pipeline":False, "init_if_empty":False})
                for _ in range(200):
                    update = await tool("quant_action_get", action_id=update["action_id"])
                    if update["status"] not in ("running", "queued"):
                        break
                    await asyncio.sleep(.3)
                check("real update verifies already-covered historical data", update["status"] == "completed" and bool(update["business_id"]))
                RESULT["update"] = {"business_id":update["business_id"], "status":update["status"], "scope":"historical no-download date verification"}
                check("all controlled tasks have finished", (await tool("quant_active_tasks"))["total"] == 0)
                RESULT["runs"] = {"parent":parent["run_id"], "analysis":child["run_id"], "tracking":tracked["business_id"]}
                (OUTPUT / "analysis-evidence.json").write_text(json.dumps(child, ensure_ascii=False, indent=2), encoding="utf-8")
        check("original stock-list API preserved", (await http.get("/api/stock/list")).is_success)
        check("original K-line API preserved", (await http.get("/api/kline/000001")).is_success)
        started = time.monotonic()
        settings = await api("GET", "config", timeout=90)
        RESULT["settings_first_read_seconds"] = round(time.monotonic() - started, 3)
        check("original settings API preserved", len(settings["configs"]) == 5)
        selected = settings["configs"][0]
        update_payload = {"strategy_name":selected["strategy_name"], "params":{}, "expected_revision":settings["revision"]}
        for key, value in selected["params"].items():
            if isinstance(value, bool):
                update_payload["params"] = {key:not value}
                break
        if not update_payload["params"]:
            for key, value in selected["params"].items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    update_payload["params"] = {key:value + .01 if isinstance(value,float) else value + 1}
                    break
        changed = await api("POST", "config", json=update_payload)
        reloaded = await api("GET", "config", timeout=90)
        check("settings save and reload use revision locking", changed["success"] and reloaded["revision"] != settings["revision"])


def main():
    prepare()
    env = {**os.environ, "QUANT_DESKTOP_TOKEN": secrets.token_hex(32), "MPLBACKEND":"Agg", "PYTHONIOENCODING":"utf-8", "PYTHONNOUSERSITE":"1", "PATH":os.environ["SystemRoot"] + "\\System32;" + os.environ["SystemRoot"]}
    for name in ("PYTHONPATH", "PYTHONHOME", "QUANT_API_URL", "QUANT_API_TOKEN", "VIRTUAL_ENV"):
        env.pop(name, None)
    process = None
    with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
        try:
            diagnostic = "import faulthandler,runpy; faulthandler.enable(); faulthandler.dump_traceback_later(30,repeat=True); runpy.run_path('scripts/run_desktop_backend.py',run_name='__main__')"
            process = subprocess.Popen([str(PYTHON), "-u", "-c", diagnostic], cwd=WORKSPACE, env=env, stdin=subprocess.PIPE, stdout=log, stderr=log)
            discovery = WORKSPACE / "data/desktop-runtime.json"
            for _ in range(1200):
                if discovery.exists():
                    runtime = json.loads(discovery.read_text(encoding="utf-8"))
                    try:
                        if httpx.get(runtime["base_url"] + "/api/health", headers={"X-Quant-Token":runtime["token"]}, trust_env=False).is_success:
                            break
                    except httpx.HTTPError:
                        pass
                if process.poll() is not None:
                    raise RuntimeError("打包后端提前退出，查看隔离目录 backend.log")
                time.sleep(.1)
            else:
                raise TimeoutError("等待打包后端超时")
            asyncio.run(exercise(runtime, env))
            RESULT["passed"] = True
            RESULT["base_url"] = runtime["base_url"]
        except BaseException as exc:
            RESULT["passed"] = False
            RESULT["error"] = repr(exc)
            raise
        finally:
            (OUTPUT / "result.json").write_text(json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"output":str(OUTPUT), **RESULT}, ensure_ascii=False, indent=2), flush=True)
            if RESULT.get("passed") and "--serve" in sys.argv:
                input("验收后端保持启动，按 Enter 关闭：")
            if process and process.poll() is None:
                process.stdin.close()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    main()
