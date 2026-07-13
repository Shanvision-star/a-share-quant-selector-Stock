"""系统状态中心聚合服务。

本模块只读取现有服务状态，不触发数据更新、策略重建、真实推送或交易动作。
它把数据 freshness、策略缓存 freshness、更新作业、Tracking 和集成配置归一化，
让前端能解释“为什么页面没有数据”。
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Callable

import yaml

from utils.status_sampling import select_status_sample
from utils.trading_calendar import previous_a_share_trading_day


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
WEB_STRATEGY_RESULTS_FILE = PROJECT_ROOT / "data" / "web_strategy_results.json"
WEB_STRATEGY_CACHE_DB_FILE = PROJECT_ROOT / "data" / "web_strategy_cache.db"
WEB_STRATEGY_SCHEMA_VERSION = 1
UPDATE_RUN_TYPES = {"update_and_rebuild", "update_only", "init_only"}
EXPECTED_STRATEGY_GROUPS = ("b1", "b2", "bowl", "brick", "zettaranc")
ACTIVE_TRACKING_STATUSES = ("watch_buy", "holding", "partial_sold")
TRACKING_ALERT_UI_STATUSES = (
    "pending",
    "dispatched",
    "aggregated",
    "acknowledged",
    "ignored",
)
CORE_STATUS_WEIGHT = {
    "ready": 0,
    "disabled": 0,
    "running": 1,
    "stale": 2,
    "missing": 3,
    "not_found": 3,
    "partial": 4,
    "error": 5,
}


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_bool(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _read_yaml_file(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _default_config_loader() -> dict:
    return {
        "config": _read_yaml_file(PROJECT_ROOT / "config" / "config.yaml"),
        "llm": _read_yaml_file(PROJECT_ROOT / "config" / "llm.yaml"),
    }


def _stock_csv_files() -> list[Path]:
    if not DATA_DIR.exists() or not DATA_DIR.is_dir():
        return []
    files_by_code: dict[str, Path] = {}
    for path in sorted(DATA_DIR.rglob("*.csv")):
        code = path.stem
        if not path.is_file() or not code.isdigit() or len(code) != 6:
            continue
        canonical_path = DATA_DIR / code[:2] / f"{code}.csv"
        current = files_by_code.get(code)
        if current is None or path == canonical_path:
            files_by_code[code] = path
    return [files_by_code[code] for code in sorted(files_by_code)]


def _latest_csv_date(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", newline="") as file:
            reader = csv.reader(file)
            header = next(reader, None)
            if not header:
                return None
            normalized_header = [str(column).lstrip("\ufeff").strip() for column in header]
            date_column = next(
                (column for column in ("date", "日期") if column in normalized_header),
                None,
            )
            if date_column is None:
                return None
            date_index = normalized_header.index(date_column)
            latest = None
            for row in reader:
                if date_index >= len(row):
                    continue
                value = str(row[date_index]).strip()[:10]
                if len(value) == 10 and value[4] == "-" and value[7] == "-":
                    latest = value if latest is None or value > latest else latest
            return latest
    except OSError:
        return None
    return None


def _empty_board_status() -> dict[str, dict[str, Any]]:
    return {
        board: {
            "total": 0,
            "latest_date": "-",
            "stale_ratio": 0.0,
        }
        for board in ("00", "30", "60", "68")
    }


def _default_data_status_loader() -> dict:
    csv_files = _stock_csv_files()
    board_files: dict[str, list[Path]] = {board: [] for board in ("00", "30", "60", "68")}
    for path in csv_files:
        prefix = path.stem[:2]
        if prefix in board_files:
            board_files[prefix].append(path)

    expected_date = _default_requested_trade_date()
    board_status = _empty_board_status()
    latest_dates: list[str] = []
    stale_count = 0
    checked_count = 0

    for board, files in board_files.items():
        board_latest = None
        board_stale = 0
        sample = select_status_sample(files, sample_size=10)
        for path in sample:
            stock_date = _latest_csv_date(path)
            if not stock_date:
                continue
            if stock_date < expected_date:
                board_stale += 1
                stale_count += 1
            if board_latest is None or stock_date > board_latest:
                board_latest = stock_date
            latest_dates.append(stock_date)
            checked_count += 1
        board_status[board] = {
            "total": len(files),
            "latest_date": board_latest or "-",
            "stale_ratio": round(board_stale / max(len(sample), 1) * 100, 1),
        }

    return {
        "total_stocks": len(csv_files),
        "latest_date": max(latest_dates) if latest_dates else "-",
        "stale_count": stale_count,
        "checked_count": checked_count,
        "is_fresh": stale_count / max(checked_count, 1) < 0.3 if checked_count else False,
        "boards": board_status,
    }


def _default_requested_trade_date() -> str:
    now = datetime.now()
    if now.time() >= dt_time(15, 0):
        target = now.date()
    else:
        target = now.date() - timedelta(days=1)
    return previous_a_share_trading_day(target).strftime("%Y-%m-%d")


def _read_strategy_snapshot() -> dict | None:
    if not WEB_STRATEGY_RESULTS_FILE.exists():
        return None

    try:
        with WEB_STRATEGY_RESULTS_FILE.open("r", encoding="utf-8") as file:
            snapshot = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(snapshot, dict):
        return None
    if snapshot.get("schema_version") != WEB_STRATEGY_SCHEMA_VERSION:
        return None
    if not isinstance(snapshot.get("groups"), dict):
        return None
    if not isinstance(snapshot.get("results"), list):
        return None
    return snapshot


def _read_only_db_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not WEB_STRATEGY_CACHE_DB_FILE.exists():
        return []

    uri = f"file:{WEB_STRATEGY_CACHE_DB_FILE.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _safe_json_loads(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _latest_strategy_run(requested_date: str) -> dict | None:
    items = _read_only_db_rows(
        """
        SELECT *
        FROM strategy_runs
        WHERE trade_date = ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (requested_date,),
    )
    return items[0] if items else None


def _default_strategy_cache_loader() -> dict:
    requested_date = _default_requested_trade_date()
    snapshot = _read_strategy_snapshot()
    last_run = _latest_strategy_run(requested_date)
    base = {
        "requested_date": requested_date,
        "strategy_filter": "all",
        "cache_file": str(WEB_STRATEGY_RESULTS_FILE),
        "exists": snapshot is not None,
        "trade_date": None,
        "generated_at": None,
        "total": 0,
        "unique_total": 0,
        "available_groups": [],
        "missing_groups": [],
        "group_totals": {},
        "status": "missing",
        "message": "策略缓存文件不存在，请先手动重建。",
        "is_latest": False,
        "latest_run_status": last_run.get("status") if last_run else None,
        "last_run_id": last_run.get("run_id") if last_run else None,
        "source": "empty",
        "rebuild": {
            "is_running": bool(last_run and last_run.get("status") == "running"),
            "last_status": last_run.get("status") if last_run else None,
        },
    }

    if snapshot is None:
        return base

    results = snapshot.get("results", [])
    groups = snapshot.get("groups", {})
    available_groups = sorted(groups.keys())
    missing_groups = [group for group in EXPECTED_STRATEGY_GROUPS if group not in groups]
    trade_date = snapshot.get("trade_date")
    unique_total = len({str(item.get("code", "")) for item in results if item.get("code")})
    is_latest = bool(trade_date and trade_date == requested_date)
    status = "ready" if is_latest else "stale"
    message = (
        "当日策略缓存可直接复用。"
        if is_latest
        else f"策略缓存日期 {trade_date} 与目标日期 {requested_date} 不一致。"
    )
    if is_latest and missing_groups:
        status = "partial"
        message = f"策略缓存日期 {trade_date} 可用，但缺少策略分组: {', '.join(missing_groups)}。"
    if last_run and last_run.get("status") == "running":
        status = "running"
        message = last_run.get("message") or "策略缓存正在重建。"

    base.update(
        {
            "exists": True,
            "trade_date": trade_date,
            "generated_at": snapshot.get("generated_at"),
            "total": len(results),
            "unique_total": unique_total,
            "available_groups": available_groups,
            "missing_groups": missing_groups,
            "group_totals": {
                group_name: group.get("total", 0)
                for group_name, group in groups.items()
                if isinstance(group, dict)
            },
            "status": status,
            "message": message,
            "is_latest": is_latest,
            "source": "file",
            "rebuild": {
                "is_running": bool(last_run and last_run.get("status") == "running"),
                "last_status": last_run.get("status") if last_run else None,
                "target_date": requested_date,
                "last_run_id": last_run.get("run_id") if last_run else None,
            },
        }
    )
    return base


def _default_runs_loader() -> dict:
    update_run_types = sorted(UPDATE_RUN_TYPES)
    placeholders = ",".join("?" for _ in update_run_types)
    items = _read_only_db_rows(
        f"""
        SELECT *
        FROM strategy_runs
        WHERE run_type IN ({placeholders})
        ORDER BY started_at DESC
        LIMIT 20
        """,
        tuple(update_run_types),
    )
    return {
        "items": items,
        "total": len(items),
        "page": 1,
        "per_page": 20,
    }


def _default_tracking_items_loader(status: str, limit: int = 1000) -> list[dict]:
    return _read_only_db_rows(
        """
        SELECT tracking_id
        FROM tracking_items
        WHERE status = ?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (status, max(1, int(limit))),
    )


def _default_tracking_status_count_loader(status: str) -> int:
    rows = _read_only_db_rows(
        "SELECT COUNT(*) AS cnt FROM tracking_items WHERE status = ?",
        (status,),
    )
    return int(rows[0]["cnt"]) if rows else 0


def _default_alerts_loader(ui_status: str, limit: int = 1000) -> list[dict]:
    return _read_only_db_rows(
        """
        SELECT alert_id, tracking_id, ui_status, priority
        FROM tracking_alert_events
        WHERE ui_status = ?
        ORDER BY priority ASC, alert_id ASC
        LIMIT ?
        """,
        (ui_status, max(1, int(limit))),
    )


def _default_alert_status_counts_loader() -> dict[str, int]:
    rows = _read_only_db_rows(
        """
        SELECT ui_status, COUNT(*) AS cnt
        FROM tracking_alert_events
        GROUP BY ui_status
        """
    )
    counts = {status: 0 for status in TRACKING_ALERT_UI_STATUSES}
    for row in rows:
        status = str(row.get("ui_status") or "").strip().lower()
        if not status:
            continue
        counts[status] = int(row.get("cnt") or 0)
    return counts


def _default_tracking_loop_run_loader(loop_type: str = "post_close") -> dict | None:
    rows = _read_only_db_rows(
        """
        SELECT *
        FROM tracking_loop_runs
        WHERE loop_type = ?
        ORDER BY started_at DESC, rowid DESC
        LIMIT 1
        """,
        (loop_type,),
    )
    if not rows:
        return None

    row = rows[0]
    return {
        "run_id": row.get("run_id"),
        "loop_type": row.get("loop_type"),
        "eval_date": row.get("eval_date"),
        "slot": row.get("slot"),
        "status": row.get("status"),
        "trigger": row.get("trigger"),
        "sync_first": bool(row.get("sync_first")),
        "per_slot_limit": int(row.get("per_slot_limit") or 0),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
        "sync": _safe_json_loads(row.get("sync_json")),
        "evaluation": _safe_json_loads(row.get("evaluation_json")),
        "dispatch": _safe_json_loads(row.get("dispatch_json")),
        "error": _safe_json_loads(row.get("error_json")),
    }


@dataclass(frozen=True)
class StatusBlock:
    status: str
    message: str
    checked_at: str
    next_action: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "checked_at": self.checked_at,
            "next_action": self.next_action,
            "details": self.details,
        }


class SystemStatusService:
    """聚合系统状态，提供给 `/api/system/status` 使用。"""

    def __init__(
        self,
        *,
        now_provider: Callable[[], str] = _now_iso,
        data_status_loader: Callable[[], dict] = _default_data_status_loader,
        strategy_cache_loader: Callable[[], dict] = _default_strategy_cache_loader,
        runs_loader: Callable[[], dict] = _default_runs_loader,
        tracking_items_loader: Callable[[str, int], list[dict]] = _default_tracking_items_loader,
        tracking_counts_loader: Callable[[str], int] | None = None,
        alerts_loader: Callable[[str, int], list[dict]] = _default_alerts_loader,
        alert_status_counts_loader: Callable[[], dict[str, int]] | None = None,
        tracking_loop_run_loader: Callable[[str], dict | None] = _default_tracking_loop_run_loader,
        config_loader: Callable[[], dict] = _default_config_loader,
    ) -> None:
        self.now_provider = now_provider
        self.data_status_loader = data_status_loader
        self.strategy_cache_loader = strategy_cache_loader
        self.runs_loader = runs_loader
        self.tracking_items_loader = tracking_items_loader
        self.tracking_counts_loader = (
            tracking_counts_loader
            if tracking_counts_loader is not None
            else (
                _default_tracking_status_count_loader
                if tracking_items_loader is _default_tracking_items_loader
                else None
            )
        )
        self.alerts_loader = alerts_loader
        self.alert_status_counts_loader = (
            alert_status_counts_loader
            if alert_status_counts_loader is not None
            else (
                _default_alert_status_counts_loader
                if alerts_loader is _default_alerts_loader
                else None
            )
        )
        self.tracking_loop_run_loader = tracking_loop_run_loader
        self.config_loader = config_loader

    def build_status(self) -> dict[str, Any]:
        checked_at = self.now_provider()
        backend = self._backend_block(checked_at)
        data = self._guarded_block("data", checked_at, self._data_block)
        strategy_cache = self._guarded_block("strategy_cache", checked_at, self._strategy_cache_block)
        update_pipeline = self._guarded_block("update_pipeline", checked_at, self._update_pipeline_block)
        tracking = self._guarded_block("tracking", checked_at, self._tracking_block, core_block=False)
        integrations = self._guarded_block("integrations", checked_at, self._integrations_block, core_block=False)
        blocks = {
            "backend": backend,
            "data": data,
            "strategy_cache": strategy_cache,
            "update_pipeline": update_pipeline,
            "tracking": tracking,
            "integrations": integrations,
        }
        overall = self._overall_status(blocks)
        return {
            "checked_at": checked_at,
            "overall_status": overall,
            **{key: value.to_dict() for key, value in blocks.items()},
            "frontend_hints": self._frontend_hints(blocks, overall),
        }

    def _backend_block(self, checked_at: str) -> StatusBlock:
        return StatusBlock(
            status="ready",
            message="后端 API 可用。",
            checked_at=checked_at,
            next_action="继续检查数据和策略缓存状态。",
            details={
                "api_version": "2.0.0",
                "service": "FastAPI",
            },
        )

    def _guarded_block(
        self,
        name: str,
        checked_at: str,
        builder: Callable[[str], StatusBlock],
        *,
        core_block: bool = True,
    ) -> StatusBlock:
        try:
            return builder(checked_at)
        except Exception as exc:
            action = "先查看后端日志，再重试状态检查。" if core_block else "该模块不阻断数据和策略主链路。"
            return StatusBlock(
                status="error",
                message=f"{name} 状态读取失败。",
                checked_at=checked_at,
                next_action=action,
                details={"error_type": type(exc).__name__},
            )

    def _data_block(self, checked_at: str) -> StatusBlock:
        raw = self.data_status_loader() or {}
        total = int(raw.get("total_stocks") or 0)
        latest_date = raw.get("latest_date") or "-"
        is_fresh = bool(raw.get("is_fresh"))
        if total <= 0:
            status = "missing"
            message = "本地行情 CSV 不存在或未被识别。"
            action = "进入数据更新页执行首次初始化。"
        elif not is_fresh:
            status = "stale"
            message = f"本地行情存在，但抽样显示最新日期 {latest_date} 未达到预期。"
            action = "进入数据更新页执行 update+rebuild。"
        else:
            status = "ready"
            message = f"本地行情数据可用，最新样本日期 {latest_date}。"
            action = "继续检查策略缓存是否与行情日期一致。"
        return StatusBlock(
            status=status,
            message=message,
            checked_at=checked_at,
            next_action=action,
            details={
                "total_stocks": total,
                "latest_date": latest_date,
                "stale_count": raw.get("stale_count", 0),
                "checked_count": raw.get("checked_count", 0),
                "is_fresh": is_fresh,
                "boards": raw.get("boards", {}),
            },
        )

    def _strategy_cache_block(self, checked_at: str) -> StatusBlock:
        raw = self.strategy_cache_loader() or {}
        raw_status = str(raw.get("status") or "missing")
        status = "missing" if raw_status == "not_found" else raw_status
        trade_date = raw.get("trade_date")
        requested_date = raw.get("requested_date")
        is_latest = bool(raw.get("is_latest"))
        if status == "ready" and requested_date and trade_date and requested_date != trade_date:
            status = "stale"
        if status == "ready" and not is_latest:
            status = "stale"

        if status == "ready":
            message = f"策略缓存可用，缓存日期 {trade_date}。"
            action = "可以查看策略结果。"
        elif status == "running":
            message = raw.get("message") or "策略缓存正在重建。"
            action = "等待重建完成，或进入数据更新页查看进度。"
        elif status == "partial":
            message = raw.get("message") or "策略缓存部分可用，但缺少策略分组。"
            action = "进入策略结果页或数据更新页重建全部策略缓存。"
        elif status == "stale":
            message = raw.get("message") or f"策略缓存日期 {trade_date} 与目标日期 {requested_date} 不一致。"
            action = "进入数据更新页执行 update+rebuild。"
        else:
            status = "missing"
            message = raw.get("message") or "策略缓存缺失。"
            action = "进入数据更新页生成策略缓存。"

        return StatusBlock(
            status=status,
            message=message,
            checked_at=checked_at,
            next_action=action,
            details={
                "requested_date": requested_date,
                "trade_date": trade_date,
                "generated_at": raw.get("generated_at"),
                "total": raw.get("total", 0),
                "unique_total": raw.get("unique_total", 0),
                "available_groups": raw.get("available_groups", []),
                "missing_groups": raw.get("missing_groups", []),
                "latest_run_status": raw.get("latest_run_status"),
                "last_run_id": raw.get("last_run_id"),
                "rebuild": raw.get("rebuild", {}),
            },
        )

    def _update_pipeline_block(self, checked_at: str) -> StatusBlock:
        runs = (self.runs_loader() or {}).get("items", [])
        update_runs = [run for run in runs if run.get("run_type") in UPDATE_RUN_TYPES]
        latest = update_runs[0] if update_runs else None
        if not latest:
            return StatusBlock(
                status="missing",
                message="尚未找到数据更新作业记录。",
                checked_at=checked_at,
                next_action="如果页面无数据，进入数据更新页执行一次 update+rebuild。",
                details={"latest_run": None},
            )

        raw_status = str(latest.get("status") or "missing")
        if raw_status == "done":
            status = "ready"
            action = "继续检查策略缓存是否 ready。"
        elif raw_status == "running":
            status = "running"
            action = "进入数据更新页查看实时进度。"
        elif raw_status == "partial":
            status = "partial"
            action = "不要直接信任当前结果；检查失败股票后重新执行 update+rebuild。"
        else:
            status = "error"
            action = "查看最近更新错误并重新执行 update+rebuild。"

        return StatusBlock(
            status=status,
            message=latest.get("message") or f"最近更新作业状态: {raw_status}",
            checked_at=checked_at,
            next_action=action,
            details={
                "latest_run": {
                    "run_id": latest.get("run_id"),
                    "run_type": latest.get("run_type"),
                    "trade_date": latest.get("trade_date"),
                    "status": latest.get("status"),
                    "matched_count": latest.get("matched_count"),
                    "processed_count": latest.get("processed_count"),
                    "total_count": latest.get("total_count"),
                    "started_at": latest.get("started_at"),
                    "completed_at": latest.get("completed_at"),
                }
            },
        )

    def _tracking_block(self, checked_at: str) -> StatusBlock:
        counts: dict[str, int] = {}
        total_active = 0
        for status in ACTIVE_TRACKING_STATUSES:
            count = (
                self.tracking_counts_loader(status)
                if self.tracking_counts_loader is not None
                else len(self.tracking_items_loader(status, 1000))
            )
            counts[status] = count
            total_active += count
        pending_alerts = self.alerts_loader("pending", 1000)
        if self.alert_status_counts_loader is not None:
            alert_status_counts = {
                **{status: 0 for status in TRACKING_ALERT_UI_STATUSES},
                **self.alert_status_counts_loader(),
            }
        else:
            # 测试或外部注入 loader 时无法安全假设有 SQL count 能力，只按显式状态逐项读取。
            alert_status_counts = {
                status: len(self.alerts_loader(status, 1000))
                for status in TRACKING_ALERT_UI_STATUSES
            }
        latest_loop_run = self.tracking_loop_run_loader("post_close")
        latest_loop_status, latest_loop_message = self._tracking_loop_message(latest_loop_run)
        return StatusBlock(
            status="ready",
            message=f"Tracking 活跃记录 {total_active} 条，待处理告警 {len(pending_alerts)} 条。",
            checked_at=checked_at,
            next_action="Tracking 状态不影响数据和策略主链路。",
            details={
                "active_count": total_active,
                "status_counts": counts,
                "pending_alert_count": len(pending_alerts),
                "alert_status_counts": alert_status_counts,
                "latest_loop_run": latest_loop_run,
                "latest_loop_status": latest_loop_status,
                "latest_loop_message": latest_loop_message,
            },
        )

    def _tracking_loop_message(self, latest_run: dict | None) -> tuple[str, str]:
        if not latest_run:
            return "missing", "尚未执行过收盘循环。"
        status = str(latest_run.get("status") or "missing")
        if status == "done":
            return status, "最近收盘循环完成。"
        if status == "partial":
            return status, "最近收盘循环部分完成，请查看 sync/evaluation error 摘要。"
        if status == "error":
            return status, "最近收盘循环失败，请查看 error.stage/message。"
        if status == "running":
            return status, "收盘循环正在运行。"
        return status, f"最近收盘循环状态: {status}"

    def _integrations_block(self, checked_at: str) -> StatusBlock:
        raw = self.config_loader() or {}
        app_config = raw.get("config") or raw
        llm_config = raw.get("llm") or {}
        dingtalk = app_config.get("dingtalk", {}) if isinstance(app_config, dict) else {}
        qmt = app_config.get("qmt", {}) if isinstance(app_config, dict) else {}
        llm_provider = str(llm_config.get("provider") or "").strip().lower()
        deepseek = llm_config.get("deepseek", {}) if isinstance(llm_config, dict) else {}
        codex_cli = llm_config.get("codex_cli", {}) if isinstance(llm_config, dict) else {}

        # 集成区只暴露布尔状态，避免 webhook、api_key、账户号和本机路径进入前端 payload。
        dingtalk_configured = _safe_bool(dingtalk.get("webhook_url"))
        deepseek_configured = _safe_bool(deepseek.get("api_key"))
        # codex_cli 可依赖服务器/本机已登录态；状态页只承认 provider/command 存在，不执行 CLI。
        codex_cli_configured = llm_provider == "codex_cli" or _safe_bool(codex_cli.get("command"))
        llm_configured = deepseek_configured or codex_cli_configured
        provider_label = ""
        if llm_configured and llm_provider in {"deepseek", "codex_cli"}:
            provider_label = llm_provider
        elif deepseek_configured:
            provider_label = "deepseek"
        qmt_enabled = bool(qmt.get("enabled", False))
        any_configured = dingtalk_configured or llm_configured or qmt_enabled
        return StatusBlock(
            status="ready" if any_configured else "disabled",
            message="外部集成配置已脱敏汇总。" if any_configured else "外部集成未配置或当前不启用。",
            checked_at=checked_at,
            next_action="集成配置不影响数据和策略主链路。",
            details={
                "dingtalk": {
                    "configured": dingtalk_configured,
                    "signed": _safe_bool(dingtalk.get("secret")),
                },
                "llm": {
                    "deepseek_configured": deepseek_configured,
                    "codex_cli_configured": codex_cli_configured,
                    "provider": provider_label,
                },
                "qmt": {
                    "enabled": qmt_enabled,
                    "mode": qmt.get("mode") or "disabled",
                    "reserved_only": bool(qmt.get("reserved_only", True)),
                },
            },
        )

    def _overall_status(self, blocks: dict[str, StatusBlock]) -> str:
        core_blocks = [blocks["data"], blocks["strategy_cache"]]
        update_status = blocks["update_pipeline"].status
        if update_status in {"running", "partial", "error"}:
            core_blocks.append(blocks["update_pipeline"])
        worst = max(core_blocks, key=lambda block: CORE_STATUS_WEIGHT.get(block.status, 5))
        return "missing" if worst.status == "not_found" else worst.status

    def _frontend_hints(self, blocks: dict[str, StatusBlock], overall: str) -> list[str]:
        hints: list[str] = []
        data = blocks["data"]
        strategy = blocks["strategy_cache"]
        update = blocks["update_pipeline"]
        if data.status in {"missing", "stale", "error"}:
            hints.append(data.next_action)
        if strategy.status in {"missing", "stale", "partial", "running", "error"}:
            hints.append(strategy.next_action)
        if update.status == "running":
            hints.append("有数据更新任务正在运行，当前页面可能显示旧缓存。")
        if update.status == "partial":
            hints.append("最近更新是 partial/局部完成，不建议把当前结果当作完整结果。")
        if update.status == "error":
            hints.append("最近更新失败，请先查看更新页错误信息。")
        if overall == "ready" and not hints:
            hints.append("数据和策略缓存均可用，可以查看策略结果。")
        return list(dict.fromkeys(hints))


system_status_service = SystemStatusService()
