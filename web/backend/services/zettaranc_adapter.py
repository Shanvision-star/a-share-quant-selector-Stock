"""zettaranc-skill 适配层：把上游 SKILL.md 与 CLI 接入到 LLM 诊断链路。

设计约束（C 档任务，2026-05-29）：
- vendor 方式 = git submodule (third_party/zettaranc/)。上游主仓库依赖 Tushare
  与独立 SQLite（third_party/zettaranc/data/stock_data.db），数据完全隔离，
  绝不写入本仓库的 data/ CSV，也不复用 a-share-quant-selector 的更新流水线。
- 双轨数据：
    A) 主路径：当 ZETTARANC_TUSHARE_TOKEN（或 third_party/zettaranc/.env 中
       TUSHARE_TOKEN）配置完整时，subprocess 调用上游
       `python -m modules.cli analyze {ts_code}`，捕获 stdout 作为真·zettaranc
       上下文（含战法识别 + 60 指标）。
    B) 降级：未配置 Tushare 或 CLI 失败时，读本仓库 data/{prefix}/{code}.csv，
       用 utils.technical 计算 KDJ/MACD/BBI/MA/RSI 快照，构造同形态文本块。
- SKILL.md（618 行）已剥离 YAML frontmatter 和「首次对话 · 数据模式检查」配置块，
  只保留角色协议 + 心智模型，缓存为模块级单例供 LLM service 拼 system prompt。

对外接口：
- ``load_skill_md_role()`` -> str：返回精简后的 SKILL.md 文本（不含 setup 节）。
- ``prepare_context(code)`` -> dict：返回 ``{"source": "cli|local_csv|none",
   "text": ..., "error": ...}``，调用方负责拼接到 user prompt。
- ``to_ts_code(code)`` -> str：把 6 位 A 股代码补 .SH/.SZ 后缀，匹配上游 CLI 入参。
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 仓库根：本文件位于 web/backend/services/，向上 3 级即仓库根
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ZETTARANC_ROOT = _REPO_ROOT / "third_party" / "zettaranc"
_SKILL_MD_PATH = _ZETTARANC_ROOT / "SKILL.md"
_DATA_DIR = _REPO_ROOT / "data"

# CLI 调用超时（秒）。上游 analyze 含 Tushare 拉取 + 60 指标计算，给宽松上限。
_CLI_TIMEOUT_SECONDS = 35

# 缓存：避免每次诊断都读盘
_skill_md_cache: Optional[str] = None


def _strip_skill_md(raw: str) -> str:
    """去掉 YAML frontmatter 与 setup 段，仅留角色协议与心智模型。

    保留：## 角色扮演规则、回答工作流、心智模型、心法等正文。
    去掉：开头 --- name/description --- frontmatter；以及
          ## 首次对话 · 数据模式检查 整段（与我们的部署无关）。
    """
    text = raw
    # 1) 去 YAML frontmatter：开头一对 --- ... ---
    fm = re.match(r"^---\s*\n.*?\n---\s*\n", text, flags=re.DOTALL)
    if fm:
        text = text[fm.end():]
    # 2) 去 "## 首次对话 · 数据模式检查" 一节（直到下一个 ## 标题）
    setup = re.search(
        r"\n##\s*首次对话\s*·\s*数据模式检查.*?(?=\n##\s)",
        text,
        flags=re.DOTALL,
    )
    if setup:
        text = text[: setup.start()] + text[setup.end():]
    # 3) v3.3.x 把首次配置说明改成无二级标题的粗体段。
    #    这里继续剥离，避免跟踪诊断的 system prompt 引导用户配置上游 Token。
    inline_setup = re.search(
        r"\n\*\*此 Skill\s*首次激活时，先检查数据源配置。\*\*.*?(?=\n##\s*角色扮演规则)",
        text,
        flags=re.DOTALL,
    )
    if inline_setup:
        text = text[: inline_setup.start()] + text[inline_setup.end():]
    return text.strip()


def load_skill_md_role() -> str:
    """加载并缓存 SKILL.md 角色协议正文。文件缺失时返回兜底短提示。"""
    global _skill_md_cache
    if _skill_md_cache is not None:
        return _skill_md_cache

    if not _SKILL_MD_PATH.exists():
        logger.warning(
            "[zettaranc] SKILL.md 未找到（%s）；将使用最简角色提示。",
            _SKILL_MD_PATH,
        )
        _skill_md_cache = (
            "你是 zettaranc（Z 哥），A 股短线纪律派。"
            "止损优先、仓位控制、不凭感觉。用「我」第一人称回答。"
        )
        return _skill_md_cache

    try:
        raw = _SKILL_MD_PATH.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Windows 极端情况：UTF-8 BOM 或 GBK 写入。回退 errors=ignore 不阻断。
        raw = _SKILL_MD_PATH.read_text(encoding="utf-8", errors="ignore")
    _skill_md_cache = _strip_skill_md(raw)
    return _skill_md_cache


def to_ts_code(code: str) -> str:
    """6 位 A 股代码 → Tushare ts_code（NNNNNN.SH 或 NNNNNN.SZ）。

    规则与 zettaranc/modules 一致：
        6xxxxx → .SH ；其余 → .SZ。已含后缀的原样返回。
    """
    code = str(code).strip().upper()
    if "." in code:
        return code
    if not code or not code[0].isdigit():
        return code  # 非标准代码不强加后缀，让上游报错
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def _has_tushare_token() -> bool:
    """检查是否具备调上游 CLI 的最低环境：Tushare token 必须存在。

    优先级：进程环境变量 ZETTARANC_TUSHARE_TOKEN / TUSHARE_TOKEN
        > third_party/zettaranc/.env 文件存在且含 TUSHARE_TOKEN=非空值。
    """
    if os.environ.get("ZETTARANC_TUSHARE_TOKEN") or os.environ.get("TUSHARE_TOKEN"):
        return True
    env_file = _ZETTARANC_ROOT / ".env"
    if not env_file.exists():
        return False
    try:
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("TUSHARE_TOKEN="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return True
    except OSError:
        return False
    return False


def _run_cli_analyze(code: str, days: int = 60) -> Optional[str]:
    """subprocess 调上游 cli analyze；任何异常都返回 None 让上层降级。

    - 切到 third_party/zettaranc/ 作 cwd，确保它的 .env / 相对路径找得到。
    - 用同一个解释器（sys.executable），避免 venv 切换问题。
    - 捕获 stdout；stderr 仅记日志不抛出。
    """
    if not _has_tushare_token():
        return None
    ts_code = to_ts_code(code)
    cmd = [sys.executable, "-m", "modules.cli", "analyze", ts_code, "--days", str(days)]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_ZETTARANC_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_CLI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("[zettaranc] CLI 调用异常 code=%s err=%s", code, exc)
        return None
    if proc.returncode != 0:
        logger.warning(
            "[zettaranc] CLI 非零退出 code=%s rc=%s stderr=%s",
            code,
            proc.returncode,
            (proc.stderr or "").strip()[:200],
        )
        return None
    output = (proc.stdout or "").strip()
    return output or None


def _build_local_context(code: str, days: int = 60) -> Optional[str]:
    """降级路径：读本仓库 CSV 算 KDJ/MACD/BBI/MA/RSI，输出 zettaranc CLI 同形态文本块。

    返回 None 表示连本地 CSV 都没有，调用方应放弃数据注入并提示 LLM 没数据。
    """
    # 解析 CSV 路径：data/{prefix2}/{code}.csv；先尝试 6 位再尝试去后缀
    bare = str(code).split(".")[0].strip()
    if not bare:
        return None
    prefix = bare[:2]
    csv_path = _DATA_DIR / prefix / f"{bare}.csv"
    if not csv_path.exists():
        return None

    # 局部导入避免模块加载时拖入 pandas/numpy（测试 fixture 已确保可用）
    try:
        import pandas as pd  # noqa: WPS433  局部导入降低冷启动开销
        from utils.technical import KDJ, MA, EMA, calculate_zhixing_state  # 复用现有指标
    except Exception as exc:  # pragma: no cover - 防御性
        logger.warning("[zettaranc] 本地指标依赖导入失败: %s", exc)
        return None

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        logger.warning("[zettaranc] 读 CSV 失败 %s: %s", csv_path, exc)
        return None

    if df.empty or "close" not in df.columns:
        return None

    # CSV 按日期倒序存储（最新在前）；技术指标计算要求时间正序
    df = df.iloc[::-1].reset_index(drop=True)
    if len(df) < 30:
        return None  # 数据太少不算
    df_tail = df.tail(max(days, 60)).copy()

    close = df_tail["close"].astype(float)
    high = df_tail["high"].astype(float) if "high" in df_tail else close
    low = df_tail["low"].astype(float) if "low" in df_tail else close

    try:
        kdj_input = pd.DataFrame({
            "date": df_tail["date"].astype(str) if "date" in df_tail else range(len(df_tail)),
            "close": close.values,
            "high": high.values,
            "low": low.values,
        })
        kdj_df = KDJ(kdj_input)
        last_k = float(kdj_df["K"].iloc[-1])
        last_d = float(kdj_df["D"].iloc[-1])
        last_j = float(kdj_df["J"].iloc[-1])
    except Exception:
        last_k = last_d = last_j = float("nan")

    # MACD：DIF = EMA12 - EMA26；DEA = EMA9(DIF)；HIST = (DIF-DEA)*2
    try:
        ema12 = EMA(close, 12)
        ema26 = EMA(close, 26)
        dif = ema12 - ema26
        dea = EMA(dif, 9)
        hist = (dif - dea) * 2
        last_dif = float(dif.iloc[-1])
        last_dea = float(dea.iloc[-1])
        last_hist = float(hist.iloc[-1])
    except Exception:
        last_dif = last_dea = last_hist = float("nan")

    # BBI = (MA3+MA6+MA12+MA24)/4
    try:
        bbi = (MA(close, 3) + MA(close, 6) + MA(close, 12) + MA(close, 24)) / 4
        last_bbi = float(bbi.iloc[-1])
    except Exception:
        last_bbi = float("nan")

    try:
        ma5 = float(MA(close, 5).iloc[-1])
        ma10 = float(MA(close, 10).iloc[-1])
        ma20 = float(MA(close, 20).iloc[-1])
    except Exception:
        ma5 = ma10 = ma20 = float("nan")

    last_close = float(close.iloc[-1])
    last_date = str(df_tail.iloc[-1].get("date", "")) if "date" in df_tail else ""

    # 简单趋势判定（呼应 SKILL.md 多/空头排列说法）
    if ma5 > ma10 > ma20:
        trend = "多头排列"
    elif ma5 < ma10 < ma20:
        trend = "空头排列"
    else:
        trend = "纠缠"

    # ---- 知行双线 + 位置（呼应 zettaranc trend-lines/knowledge） ----
    # 知行短期趋势线 = MA14 与 MA28 的均值；知行多空线 = MA57 与 MA114 的均值。
    # 必须用未截断的 df（含全部历史，CSV 大多 250+ 根）；只 tail 60 时 MA114 必失效，
    # 这是早前 LLM 一直回答“多空线未定义/数据不足”的根因。末值进入上下文即可。
    zhixing_short = float("nan")
    zhixing_bull = float("nan")
    zhixing_pos = "数据不足"
    dist_bull_pct = float("nan")
    dist_short_pct = float("nan")
    spread_pct = float("nan")
    try:
        if "date" in df.columns and len(df) >= 114:
            zx_input = pd.DataFrame({
                "date": df["date"].astype(str).values,
                "close": df["close"].astype(float).values,
            })
            zx_state = calculate_zhixing_state(zx_input)
            zhixing_short = float(zx_state["short_term_trend"].iloc[-1])
            zhixing_bull = float(zx_state["bull_bear_line"].iloc[-1])
            dist_bull_pct = float(zx_state["distance_to_bullbear_pct"].iloc[-1])
            dist_short_pct = float(zx_state["distance_to_short_term_pct"].iloc[-1])
            spread_pct = float(zx_state["line_spread_pct"].iloc[-1])
            # 位置标签按 trend-lines.md 心法层级判定（自上而下）
            if bool(zx_state["fall_in_bowl"].iloc[-1]):
                zhixing_pos = "碗底（短期趋势线>多空线，价格落于两线之间）"
            elif bool(zx_state["near_short_trend"].iloc[-1]):
                zhixing_pos = "贴近短期趋势线"
            elif bool(zx_state["near_duokong"].iloc[-1]):
                zhixing_pos = "贴近多空线"
            elif bool(zx_state["trend_above"].iloc[-1]) and last_close > zhixing_short:
                zhixing_pos = "多头（价格在短期趋势线之上）"
            elif (not bool(zx_state["trend_above"].iloc[-1])) and last_close < zhixing_short:
                zhixing_pos = "空头（价格在短期趋势线之下）"
            else:
                zhixing_pos = "震荡/纠缠"
    except Exception as exc:  # pragma: no cover - 防御性
        logger.warning("[zettaranc] 知行线计算失败: %s", exc)

    # ---- RSI(14)：标准 Wilder 平滑 ----
    rsi14 = float("nan")
    try:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / 14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi_series = 100 - 100 / (1 + rs)
        rsi14 = float(rsi_series.iloc[-1])
    except Exception:
        pass

    # ---- 近 5 日涨跌/量比 ----
    recent_changes: list[str] = []
    try:
        last5 = df_tail.tail(5)
        chg5 = last5["close"].astype(float).pct_change().fillna(0) * 100
        recent_changes = [f"{v:+.2f}%" for v in chg5.tolist()]
    except Exception:
        recent_changes = []
    vol_ratio = float("nan")
    try:
        if "volume" in df_tail.columns and len(df_tail) >= 6:
            vol = df_tail["volume"].astype(float)
            vol_ratio = float(vol.iloc[-1]) / float(vol.iloc[-6:-1].mean())
    except Exception:
        pass

    # ---- 砖型方向（呼应 docs/BRICK_STRATEGY 与 SKILL 砖型说法） ----
    if last_close > ma20 * 1.005:
        brick = "看多砖（收盘高于 MA20 0.5% 以上）"
    elif last_close < ma20 * 0.995:
        brick = "看空砖（收盘低于 MA20 0.5% 以上）"
    else:
        brick = "震荡砖（收盘贴近 MA20）"

    zhixing_block = (
        f"知行: 短期趋势线={zhixing_short:.2f}  多空线={zhixing_bull:.2f}  "
        f"线差={spread_pct:+.2f}%  距多空线={dist_bull_pct:+.2f}%  距短期={dist_short_pct:+.2f}%\n"
        f"位置: {zhixing_pos}\n"
    )
    recent_block = (
        f"近5日: {' / '.join(recent_changes) if recent_changes else 'n/a'}  "
        f"量比(对前5日均)={vol_ratio:.2f}\n" if recent_changes else ""
    )

    return (
        f"【本地数据快照 · 来源 a-share-quant CSV · 非 Tushare 实时】\n"
        f"代码: {bare}  日期: {last_date}  收盘: {last_close:.2f}\n"
        f"KDJ:  K={last_k:.2f}  D={last_d:.2f}  J={last_j:.2f}\n"
        f"MACD: DIF={last_dif:.4f}  DEA={last_dea:.4f}  柱={last_hist:.4f}\n"
        f"BBI:  {last_bbi:.2f}\n"
        f"均线: MA5={ma5:.2f}  MA10={ma10:.2f}  MA20={ma20:.2f}  ({trend})\n"
        f"RSI14: {rsi14:.2f}\n"
        + zhixing_block
        + recent_block
        + f"砖型: {brick}\n"
    )


def prepare_context(code: str, days: int = 60) -> dict[str, Any]:
    """统一上下文生产入口：CLI 优先，CSV 降级，最终 none。

    返回结构：
        {"source": "cli" | "local_csv" | "none",
         "text": str,   # source=none 时为提示文本
         "error": str | None}
    """
    if not code:
        return {"source": "none", "text": "缺少股票代码", "error": "missing code"}

    cli_text = _run_cli_analyze(code, days=days)
    if cli_text:
        return {"source": "cli", "text": cli_text, "error": None}

    local_text = _build_local_context(code, days=days)
    if local_text:
        return {"source": "local_csv", "text": local_text, "error": None}

    return {
        "source": "none",
        "text": f"未取到 {code} 的行情快照（无 Tushare token 且本地 CSV 不存在）。",
        "error": "no_data",
    }


def reset_cache_for_tests() -> None:
    """测试钩子：清掉 SKILL.md 缓存，便于在不同 patch 下复读。"""
    global _skill_md_cache
    _skill_md_cache = None
