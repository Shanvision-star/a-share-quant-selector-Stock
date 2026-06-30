"""
Zettaranc 统一路由
====================

把 zettaranc 三件套功能统一暴露给前端：
  * /api/zettaranc/backtest/latest    读取最近一次离线回测结果
  * /api/zettaranc/backtest/run       触发一次小池子回测（默认 20 只、--j-buy 0、
                                       --vol-ratio 1.3，避免阻塞 worker 太久）
  * /api/zettaranc/holdings           持仓 CRUD
  * /api/zettaranc/holdings/alerts    持仓纪律巡检
  * /api/zettaranc/attack-scan        今日攻击日候选

设计原则：
  * 路由层只做编排，重逻辑放 services 与 strategy
  * 全部走「统一 envelope」: {success, data, message}
  * 触发型接口（run/scan）暴露 limit，避免 worker 长时间阻塞
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from web.backend.services.zettaranc_attack_scanner import get_default_scanner
from web.backend.services.zettaranc_holdings_service import (
    Holding,
    get_default_service,
)

router = APIRouter(prefix="/api/zettaranc", tags=["zettaranc"])

ROOT = Path(__file__).resolve().parents[3]
BACKTEST_LATEST = ROOT / "output" / "zettaranc_backtest_latest.json"


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------


def _ok(data: Any, message: str = "") -> dict:
    return {"success": True, "data": data, "message": message}


class HoldingIn(BaseModel):
    code: str
    name: str
    entry_date: str
    entry_price: float
    qty: int
    stop_loss: float
    take_profit_pct: float = 15.0
    hold_days_limit: int = 20
    max_position_pct: float = 10.0
    total_capital: float = 1_000_000.0
    notes: str = ""


class HoldingPatch(BaseModel):
    name: str | None = None
    entry_date: str | None = None
    entry_price: float | None = None
    qty: int | None = None
    stop_loss: float | None = None
    take_profit_pct: float | None = None
    hold_days_limit: int | None = None
    max_position_pct: float | None = None
    total_capital: float | None = None
    notes: str | None = None


class BacktestRunIn(BaseModel):
    start: str = "2024-01-01"
    end: str | None = None
    limit: int = Field(default=20, ge=1, le=300)
    take_profit: float = 15.0
    hold_days: int = 20
    j_buy: float = 0.0
    vol_ratio: float = 1.3


# ----------------------------------------------------------------------
# 回测
# ----------------------------------------------------------------------


@router.get("/backtest/latest")
def backtest_latest():
    if not BACKTEST_LATEST.exists():
        raise HTTPException(404, "尚无 zettaranc 回测结果，请先运行回测")
    try:
        data = json.loads(BACKTEST_LATEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(500, f"读取回测结果失败: {e}") from e
    return _ok(data)


@router.post("/backtest/run")
def backtest_run(payload: BacktestRunIn):
    """同步触发一次回测：默认 20 只、阈值放宽，~30 秒内可返回。"""
    script = ROOT / "scripts" / "run_zettaranc_backtest.py"
    if not script.exists():
        raise HTTPException(500, "回测脚本不存在")
    args = [
        sys.executable, str(script),
        "--start", payload.start,
        "--limit", str(payload.limit),
        "--take-profit", str(payload.take_profit),
        "--hold-days", str(payload.hold_days),
        "--j-buy", str(payload.j_buy),
        "--vol-ratio", str(payload.vol_ratio),
    ]
    if payload.end:
        args += ["--end", payload.end]
    try:
        proc = subprocess.run(
            args, cwd=str(ROOT), capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired as e:
        raise HTTPException(504, "回测超时，请缩小 limit") from e
    if proc.returncode != 0:
        raise HTTPException(500, f"回测失败: {proc.stderr[-500:]}")
    # 跑完后读最新结果
    if not BACKTEST_LATEST.exists():
        raise HTTPException(500, "回测脚本未生成 latest 文件")
    data = json.loads(BACKTEST_LATEST.read_text(encoding="utf-8"))
    return _ok(data, message="回测完成")


# ----------------------------------------------------------------------
# 持仓
# ----------------------------------------------------------------------


@router.get("/holdings")
def list_holdings():
    return _ok(get_default_service().list_holdings())


@router.post("/holdings")
def add_holding(payload: HoldingIn):
    item = get_default_service().add_holding(Holding(**payload.model_dump()))
    return _ok(item, message="已保存")


@router.patch("/holdings/{code}")
def update_holding(code: str, payload: HoldingPatch):
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    item = get_default_service().update_holding(code, patch)
    if item is None:
        raise HTTPException(404, f"持仓不存在: {code}")
    return _ok(item, message="已更新")


@router.delete("/holdings/{code}")
def delete_holding(code: str):
    ok = get_default_service().delete_holding(code)
    if not ok:
        raise HTTPException(404, f"持仓不存在: {code}")
    return _ok({"code": code}, message="已删除")


@router.get("/holdings/alerts")
def holdings_alerts(today: str | None = None):
    alerts = get_default_service().check_stop_alerts(today=today)
    summary = {
        "total": len(alerts),
        "critical": sum(1 for a in alerts if a.get("severity") == "critical"),
        "warn": sum(1 for a in alerts if a.get("severity") == "warn"),
    }
    return _ok({"alerts": alerts, "summary": summary})


# ----------------------------------------------------------------------
# 攻击日扫描
# ----------------------------------------------------------------------


@router.get("/attack-scan")
def attack_scan(limit: int = 50):
    """对本地 csv 池子扫描，limit 控制最多扫多少只（避免长时间阻塞）。"""
    if limit < 0:
        limit = 0
    candidates = get_default_scanner().scan_today(limit=limit)
    return _ok({"count": len(candidates), "candidates": candidates})
