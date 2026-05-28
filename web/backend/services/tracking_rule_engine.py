"""跟踪告警规则引擎（P2 阶段）。

按 docs/Tracking/tracking_agent_plan.md §5 / §5.3 实现 5 条规则的纯计算：
    rule_break_short_trend  priority 10  TREND_BREAK
    rule_break_bull_bear    priority 20  STOP_LOSS
    rule_short_overshoot    priority 50  SELL_PARTIAL
    rule_stall_exit         priority 60  WAIT_BUY
    rule_long_dead_cross    priority 70  TREND_BREAK

设计约束：
- **纯函数**：不读 DB、不写文件、不发钉钉；P3 入库 / P4 调度 / P5 批量在外层包装。
- **frame 升序**：与 ``TrackingService._price_frame`` 输出一致（最新一根在 ``iloc[-1]``）。
- **失败安全**：数据不足或缺列时静默跳过该规则，避免 P5 批量评估被脏数据打断。
- **dedup_key 形如 ``{tracking_id}|{rule_id}|{eval_date}``**：为 P4 唯一索引留接口。

所有规则均默认开启；用户在 P3 模板管理页可以覆写 ``params_overrides`` 或禁用。
"""

from __future__ import annotations

from typing import Callable, Optional

import pandas as pd


# 设计文档 §5.3 表格直接落盘的常量；P3 模板表会以此为默认值
RULE_META: dict[str, dict] = {
    "rule_break_short_trend": {
        "name": "跌破短趋势线",
        "category": "short_term",
        "priority": 10,
        "action_label": "TREND_BREAK",
    },
    "rule_break_bull_bear": {
        "name": "跌破多空线",
        "category": "short_term",
        "priority": 20,
        "action_label": "STOP_LOSS",
    },
    "rule_short_overshoot": {
        "name": "短期放飞",
        "category": "short_term",
        "priority": 50,
        "action_label": "SELL_PARTIAL",
    },
    "rule_stall_exit": {
        "name": "N日不涨退出",
        "category": "short_term",
        "priority": 60,
        "action_label": "WAIT_BUY",
    },
    "rule_long_dead_cross": {
        "name": "长周期均线死叉",
        "category": "long_term",
        "priority": 70,
        "action_label": "TREND_BREAK",
    },
}

# 设计文档 §5.1 / §5.2 / §5.3 给出的默认参数；P3 由 tracking_rule_templates.params_schema 覆写
DEFAULT_PARAMS: dict[str, dict] = {
    "rule_break_short_trend": {
        "short_ma_window": 5,
        "confirm_close_count": 1,
        "tolerance_pct": 0.5,
    },
    "rule_break_bull_bear": {
        "confirm_close_count": 2,
        "tolerance_pct": 0.3,
    },
    "rule_short_overshoot": {
        "short_ma_window": 5,
        "overshoot_pct": 8.0,
    },
    "rule_stall_exit": {
        "stall_days": 5,
        "stall_pct": 2.0,
    },
    "rule_long_dead_cross": {
        "fast_window": 60,
        "slow_window": 120,
    },
}


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _prepare_frame(frame: pd.DataFrame) -> Optional[pd.DataFrame]:
    """统一为升序 + 数值化 close；返回 None 表示数据不可用。"""
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    df = frame.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df if not df.empty else None


def _resolve_eval_index(df: pd.DataFrame, eval_date: Optional[str]) -> Optional[int]:
    """按 eval_date 定位评估日索引；None 取最后一根。"""
    if eval_date is None or "date" not in df.columns:
        return len(df) - 1
    ts = pd.to_datetime(eval_date)
    matches = df.index[df["date"] <= ts]
    if len(matches) == 0:
        return None
    return int(matches[-1])


def _eval_date_str(df: pd.DataFrame, eval_index: int, fallback: Optional[str]) -> str:
    """从 frame 取评估日的 YYYY-MM-DD，写入 dedup_key。"""
    if "date" in df.columns:
        return pd.to_datetime(df["date"].iloc[eval_index]).strftime("%Y-%m-%d")
    return fallback or ""


def _merged_params(rule_id: str, overrides: Optional[dict]) -> dict:
    """合并默认参数与外层 overrides，rule 级别覆盖优先。"""
    params = dict(DEFAULT_PARAMS.get(rule_id, {}))
    if not overrides:
        return params
    rule_overrides = overrides.get(rule_id) if isinstance(overrides, dict) else None
    if isinstance(rule_overrides, dict):
        params.update(rule_overrides)
    return params


def _make_alert(
    rule_id: str,
    item: dict,
    eval_date_str: str,
    evidence: dict,
    message: str,
) -> dict:
    """统一构造告警字典；P4 入库时再补 dingtalk_status 等字段。"""
    meta = RULE_META[rule_id]
    tracking_id = item.get("tracking_id") or ""
    return {
        "rule_id": rule_id,
        "name": meta["name"],
        "category": meta["category"],
        "priority": meta["priority"],
        "action_label": meta["action_label"],
        "tracking_id": tracking_id,
        "code": item.get("code") or "",
        "eval_date": eval_date_str,
        "dedup_key": f"{tracking_id}|{rule_id}|{eval_date_str}",
        "message": message,
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# 单规则实现
# ---------------------------------------------------------------------------


def _rule_break_short_trend(item: dict, df: pd.DataFrame, eval_index: int, eval_date_str: str, overrides) -> Optional[dict]:
    """§5.1：close < MA(short_ma_window) * (1 - tolerance_pct/100)，连续 N 根命中。"""
    params = _merged_params("rule_break_short_trend", overrides)
    window = int(params["short_ma_window"])
    confirm = int(params["confirm_close_count"])
    tol = float(params["tolerance_pct"]) / 100.0
    if eval_index + 1 < window or eval_index + 1 < confirm:
        return None

    close_series = df["close"].iloc[: eval_index + 1]
    ma = close_series.rolling(window=window, min_periods=window).mean()
    # 取最近 confirm 根，全部 close < ma*(1-tol)
    recent_close = close_series.iloc[-confirm:].to_numpy()
    recent_ma = ma.iloc[-confirm:].to_numpy()
    if pd.isna(recent_ma).any():
        return None
    threshold = recent_ma * (1 - tol)
    if not (recent_close < threshold).all():
        return None
    return _make_alert(
        "rule_break_short_trend",
        item,
        eval_date_str,
        evidence={
            "close": float(recent_close[-1]),
            "short_ma": float(recent_ma[-1]),
            "threshold": float(threshold[-1]),
            "confirm_count": confirm,
        },
        message=f"收盘价 {recent_close[-1]:.2f} 跌破 MA{window} 趋势线 {recent_ma[-1]:.2f}，建议减仓",
    )


def _rule_break_bull_bear(item: dict, df: pd.DataFrame, eval_index: int, eval_date_str: str, overrides) -> Optional[dict]:
    """§5.2：close < 多空线*(1 - tolerance_pct/100)，连续 N 根命中。"""
    params = _merged_params("rule_break_bull_bear", overrides)
    confirm = int(params["confirm_close_count"])
    tol = float(params["tolerance_pct"]) / 100.0
    if eval_index + 1 < confirm:
        return None

    # 复用 utils.technical.calculate_zhixing_trend，它会输出 short_term_trend / bull_bear_line
    try:
        from utils.technical import calculate_zhixing_trend
    except ImportError:
        return None

    sub_df = df.iloc[: eval_index + 1]
    try:
        trend = calculate_zhixing_trend(sub_df)
    except Exception:  # 数据不足或异常时不评估，避免影响其它规则
        return None
    if trend is None or "bull_bear_line" not in trend.columns:
        return None

    recent_close = sub_df["close"].iloc[-confirm:].to_numpy()
    recent_bb = trend["bull_bear_line"].iloc[-confirm:].to_numpy()
    if pd.isna(recent_bb).any():
        return None
    threshold = recent_bb * (1 - tol)
    if not (recent_close < threshold).all():
        return None
    return _make_alert(
        "rule_break_bull_bear",
        item,
        eval_date_str,
        evidence={
            "close": float(recent_close[-1]),
            "bull_bear_line": float(recent_bb[-1]),
            "threshold": float(threshold[-1]),
            "confirm_count": confirm,
        },
        message=f"连续 {confirm} 根收盘 {recent_close[-1]:.2f} 跌破多空线 {recent_bb[-1]:.2f}，建议止损",
    )


def _rule_short_overshoot(item: dict, df: pd.DataFrame, eval_index: int, eval_date_str: str, overrides) -> Optional[dict]:
    """§5.3：close > MA(short_ma_window) * (1 + overshoot_pct/100) 触发放飞。"""
    params = _merged_params("rule_short_overshoot", overrides)
    window = int(params["short_ma_window"])
    overshoot = float(params["overshoot_pct"]) / 100.0
    if eval_index + 1 < window:
        return None

    close_series = df["close"].iloc[: eval_index + 1]
    ma_val = close_series.iloc[-window:].mean()
    last_close = float(close_series.iloc[-1])
    threshold = ma_val * (1 + overshoot)
    if last_close <= threshold:
        return None
    return _make_alert(
        "rule_short_overshoot",
        item,
        eval_date_str,
        evidence={
            "close": last_close,
            "short_ma": float(ma_val),
            "overshoot_pct": (last_close / float(ma_val) - 1) * 100,
        },
        message=f"收盘 {last_close:.2f} 偏离 MA{window} {(last_close / ma_val - 1) * 100:.1f}%，建议减仓部分",
    )


def _rule_stall_exit(item: dict, df: pd.DataFrame, eval_index: int, eval_date_str: str, overrides) -> Optional[dict]:
    """§5.3：跟踪 N 个交易日累计涨幅 < stall_pct 时退出观察。

    仅在 ``status='watch_buy'`` 或 ``holding`` 时评估；初始 close 取 signal_date 所在交易日。
    """
    params = _merged_params("rule_stall_exit", overrides)
    days = int(params["stall_days"])
    stall_pct = float(params["stall_pct"]) / 100.0

    signal_date = item.get("signal_date")
    if not signal_date or "date" not in df.columns:
        return None
    signal_ts = pd.to_datetime(signal_date)
    signal_matches = df.index[df["date"] >= signal_ts]
    if len(signal_matches) == 0:
        return None
    start_idx = int(signal_matches[0])
    if eval_index - start_idx < days:
        return None

    start_close = float(df["close"].iloc[start_idx])
    last_close = float(df["close"].iloc[eval_index])
    if start_close <= 0:
        return None
    cumulative_pct = (last_close - start_close) / start_close
    if cumulative_pct >= stall_pct:
        return None
    return _make_alert(
        "rule_stall_exit",
        item,
        eval_date_str,
        evidence={
            "signal_close": start_close,
            "last_close": last_close,
            "cumulative_pct": cumulative_pct * 100,
            "elapsed_days": eval_index - start_idx,
        },
        message=f"跟踪 {eval_index - start_idx} 个交易日累计 {cumulative_pct * 100:.1f}%，建议退出等待新信号",
    )


def _rule_long_dead_cross(item: dict, df: pd.DataFrame, eval_index: int, eval_date_str: str, overrides) -> Optional[dict]:
    """§5.3：MA(fast_window) 由上向下穿越 MA(slow_window)。"""
    params = _merged_params("rule_long_dead_cross", overrides)
    fast = int(params["fast_window"])
    slow = int(params["slow_window"])
    if eval_index + 1 < slow + 1:
        return None

    close_series = df["close"].iloc[: eval_index + 1]
    ma_fast = close_series.rolling(window=fast, min_periods=fast).mean()
    ma_slow = close_series.rolling(window=slow, min_periods=slow).mean()
    today_fast = ma_fast.iloc[-1]
    today_slow = ma_slow.iloc[-1]
    prev_fast = ma_fast.iloc[-2]
    prev_slow = ma_slow.iloc[-2]
    if pd.isna(today_fast) or pd.isna(today_slow) or pd.isna(prev_fast) or pd.isna(prev_slow):
        return None
    # 死叉：昨日 fast >= slow，今日 fast < slow
    if not (prev_fast >= prev_slow and today_fast < today_slow):
        return None
    return _make_alert(
        "rule_long_dead_cross",
        item,
        eval_date_str,
        evidence={
            "ma_fast": float(today_fast),
            "ma_slow": float(today_slow),
            "fast_window": fast,
            "slow_window": slow,
        },
        message=f"MA{fast} {today_fast:.2f} 下穿 MA{slow} {today_slow:.2f}，长周期趋势转弱",
    )


# 规则注册：保持声明顺序与 §5.3 表格一致，便于审计
_RULE_FUNCS: list[tuple[str, Callable]] = [
    ("rule_break_short_trend", _rule_break_short_trend),
    ("rule_break_bull_bear", _rule_break_bull_bear),
    ("rule_short_overshoot", _rule_short_overshoot),
    ("rule_stall_exit", _rule_stall_exit),
    ("rule_long_dead_cross", _rule_long_dead_cross),
]


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------


def evaluate_rules(
    item: dict,
    frame: pd.DataFrame,
    eval_date: Optional[str] = None,
    params_overrides: Optional[dict] = None,
    enabled_rules: Optional[set[str]] = None,
) -> list[dict]:
    """对单个跟踪项执行全部启用的规则，返回按 priority 升序的告警列表。

    参数：
        item: 跟踪项字典，至少包含 ``tracking_id`` / ``code`` / ``signal_date`` / ``status``。
        frame: 升序 OHLC 数据；规则内部自行处理列名容错。
        eval_date: 评估截止日（含），None 表示最后一根。
        params_overrides: ``{rule_id: {param: value}}``，P3 模板表传入。
        enabled_rules: 仅评估这些规则；None 表示全部启用。
    """
    df = _prepare_frame(frame)
    if df is None:
        return []
    eval_index = _resolve_eval_index(df, eval_date)
    if eval_index is None or eval_index < 0:
        return []
    eval_date_str = _eval_date_str(df, eval_index, eval_date)

    alerts: list[dict] = []
    for rule_id, func in _RULE_FUNCS:
        if enabled_rules is not None and rule_id not in enabled_rules:
            continue
        try:
            alert = func(item, df, eval_index, eval_date_str, params_overrides)
        except Exception:
            # 单条规则异常不应阻断其它规则，记入下游日志由 P4 调度层处理
            continue
        if alert is not None:
            alerts.append(alert)

    alerts.sort(key=lambda a: a["priority"])
    return alerts
