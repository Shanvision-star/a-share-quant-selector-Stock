"""收盘同步服务：只更新活跃跟踪中的股票行情，再推进评估状态。

职责边界：
- 不触碰全市场更新逻辑（update.py / daily_update）；
- 专门服务跟踪运营场景：每次只刷 N 只股票（通常 5-50 只），秒级响应；
- 同一入口可由前端"收盘同步"按钮手动触发，也可未来接入 APScheduler 定时任务。

依赖：
- utils.akshare_fetcher.AkshareDataFetcher.fetch_stock_update （增量拉行情）
- utils.csv_manager.CSVManager.update_stock （写入 CSV）
- tracking_service.evaluate_items （推进状态机：watch_buy → holding 等）
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

ACTIVE_STATUS = ("watch_buy", "holding", "partial_sold")


def _fetch_and_update_single(code: str, days: int = 30) -> str:
    """增量更新单只股票近期行情 CSV。

    返回值：
    - "ok"   成功写入
    - "skip" 拉取结果为空（可能今日无交易或数据源暂时不可用）
    - 其他字符串  异常信息，上层记入 errors 列表继续处理

    延迟导入避免全局 akshare 登录开销；仅在实际调用时初始化。
    """
    try:
        # 延迟导入，避免在测试/导入时触发 baostock 登录等副作用
        from utils.akshare_fetcher import AkshareDataFetcher  # type: ignore
        from utils.csv_manager import CSVManager  # type: ignore

        df = AkshareDataFetcher().fetch_stock_update(code, days=days)
        if df is None or df.empty:
            return "skip"
        CSVManager().update_stock(code, df)
        return "ok"
    except Exception as exc:
        return str(exc)


class TrackingSyncService:
    """编排收盘同步流程：行情刷新 → 状态评估。"""

    def sync_and_evaluate(
        self,
        eval_date: Optional[str] = None,
        only_codes: Optional[list[str]] = None,
        days: int = 30,
    ) -> dict:
        """
        执行收盘同步，返回结构化摘要。

        流程：
        1. 从活跃跟踪列表收集全部 code（status ∈ watch_buy/holding/partial_sold）
        2. 逐一调用 fetch_stock_update → update_stock 写 CSV（只更新近 days 天）
        3. 调 tracking_service.evaluate_items 推进状态机
        4. 返回 {total_codes, updated, skipped, errors, evaluation}

        Args:
            eval_date:   指定评估基准日（None 则取 frame 最后一行，即最新收盘日）
            only_codes:  仅同步指定 codes；None 则同步全部活跃跟踪
            days:        增量拉取天数窗口，默认 30 天（覆盖月内所有交易日）
        """
        from web.backend.services.tracking_service import tracking_service  # 延迟导入避免循环

        # ── Step 1: 收集活跃跟踪 codes ────────────────────────────────
        all_active: list[dict] = []
        for status in ACTIVE_STATUS:
            all_active.extend(tracking_service.list_items(status=status, limit=1000))

        # 按 set 去重；若 only_codes 有传则缩小范围
        codes: list[str] = list({item["code"] for item in all_active})
        if only_codes:
            only_set = set(only_codes)
            codes = [c for c in codes if c in only_set]

        # ── Step 2: 逐一刷新行情 CSV ──────────────────────────────────
        updated: list[str] = []
        skipped: list[str] = []
        errors: list[dict] = []

        for code in codes:
            result = _fetch_and_update_single(code, days=days)
            if result == "ok":
                updated.append(code)
            elif result == "skip":
                skipped.append(code)
            else:
                errors.append({"code": code, "error": result})
                logger.warning("sync-close 行情更新失败 [%s]: %s", code, result)

        # ── Step 3: 批量推进评估状态 ──────────────────────────────────
        # 即使部分 code 更新失败，也继续评估；evaluate_items 内部已处理空 frame
        # force=True 打破 holding 同日短路，保证刚刚刷的 CSV 能即时重算 latest_return_pct。
        eval_result = tracking_service.evaluate_items(eval_date, force=True)

        # 统计状态变更数（watch_buy → holding 等）：从 items 差分得出
        status_changes = [
            {"tracking_id": item.get("tracking_id"), "code": item.get("code"), "status": item.get("status")}
            for item in eval_result.get("items", [])
            if item.get("status") != "watch_buy"
        ]

        return {
            "total_codes": len(codes),
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "evaluation": {
                "total": eval_result.get("total", 0),
                "status_changes": status_changes,
            },
        }


tracking_sync_service = TrackingSyncService()
