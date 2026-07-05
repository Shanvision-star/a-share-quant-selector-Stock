"""C 档：zettaranc_adapter 单元测试。

覆盖：
- SKILL.md 加载与剥离 frontmatter/setup 节
- ts_code 后缀映射
- 缺 Tushare token 时 CLI 调用直接放弃（不抛错）
- 本地 CSV 路径能产出包含 KDJ/MACD/BBI 的快照文本
- prepare_context 在两条路径都失败时返回 source=none
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest


def _csv_fixture(tmp_path: Path, code: str = "000070", rows: int = 80) -> Path:
    """生成符合本仓库 CSV 列规范的假数据：date,open,high,low,close,volume,amount,turnover,market_cap。
    日期倒序（最新在前），与 utils/csv_manager 写出一致。
    """
    import numpy as np
    rng = np.random.default_rng(42)
    base = 10.0
    closes = base + np.cumsum(rng.normal(0, 0.2, rows))
    highs = closes + rng.uniform(0.05, 0.3, rows)
    lows = closes - rng.uniform(0.05, 0.3, rows)
    opens = closes + rng.normal(0, 0.1, rows)
    dates = pd.date_range("2025-01-01", periods=rows, freq="B").strftime("%Y-%m-%d")
    df = pd.DataFrame({
        "date": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": rng.integers(1_000_000, 5_000_000, rows),
        "amount": rng.integers(1e7, 5e7, rows),
        "turnover": rng.uniform(0.5, 5.0, rows),
        "market_cap": rng.uniform(1e9, 5e9, rows),
    })
    df = df.iloc[::-1].reset_index(drop=True)  # 最新在前
    sub = tmp_path / code[:2]
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"{code}.csv"
    df.to_csv(path, index=False)
    return path


def test_load_skill_md_strips_frontmatter_and_setup(monkeypatch):
    from web.backend.services import zettaranc_adapter as za

    fake_md = (
        "---\n"
        "name: zettaranc\n"
        "description: x\n"
        "---\n"
        "## 角色扮演规则\n"
        "我是 Z 哥。\n"
        "## 首次对话 · 数据模式检查\n"
        "请用户填 token。\n"
        "## 心智模型\n"
        "止损优先。\n"
    )
    monkeypatch.setattr(za, "_SKILL_MD_PATH", _fake_path(fake_md))
    za.reset_cache_for_tests()
    text = za.load_skill_md_role()
    assert "name: zettaranc" not in text
    assert "请用户填 token" not in text
    assert "角色扮演规则" in text
    assert "心智模型" in text


def test_load_skill_md_strips_v33_inline_setup(monkeypatch):
    """v3.3.x 的首次配置段不再有二级标题，也不能进入诊断 system prompt。"""
    from web.backend.services import zettaranc_adapter as za

    fake_md = (
        "---\n"
        "name: zettaranc\n"
        "---\n"
        "# zettaranc\n"
        "## 能力边界与 API 依赖声明\n"
        "这里允许保留能力边界。\n"
        "**此 Skill 首次激活时，先检查数据源配置。**\n"
        "在第一条用户消息后，执行配置检测。\n"
        "> 对了，还有个事儿——你还没选模式。\n"
        "TUSHARE_TOKEN=你的 token\n"
        "## 角色扮演规则（最重要）\n"
        "直接以 Z 哥身份回应。\n"
        "## 核心心智模型总览\n"
        "止损优先。\n"
    )
    monkeypatch.setattr(za, "_SKILL_MD_PATH", _fake_path(fake_md))
    za.reset_cache_for_tests()
    text = za.load_skill_md_role()
    assert "还没选模式" not in text
    assert "TUSHARE_TOKEN=你的 token" not in text
    assert "角色扮演规则" in text
    assert "核心心智模型" in text


def test_load_skill_md_missing_returns_fallback(monkeypatch, tmp_path):
    from web.backend.services import zettaranc_adapter as za

    monkeypatch.setattr(za, "_SKILL_MD_PATH", tmp_path / "no_such_file.md")
    za.reset_cache_for_tests()
    text = za.load_skill_md_role()
    assert "Z 哥" in text or "zettaranc" in text


def test_to_ts_code_prefixes():
    from web.backend.services.zettaranc_adapter import to_ts_code

    assert to_ts_code("600487") == "600487.SH"
    assert to_ts_code("000001") == "000001.SZ"
    assert to_ts_code("300750") == "300750.SZ"
    assert to_ts_code("000070.SZ") == "000070.SZ"


def test_run_cli_analyze_without_token_returns_none(monkeypatch):
    from web.backend.services import zettaranc_adapter as za

    monkeypatch.delenv("ZETTARANC_TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(za, "_ZETTARANC_ROOT", Path("/nonexistent_zettaranc_root"))
    assert za._run_cli_analyze("000001") is None


def test_build_local_context_with_synthetic_csv(monkeypatch, tmp_path):
    from web.backend.services import zettaranc_adapter as za

    _csv_fixture(tmp_path, code="000070", rows=80)
    monkeypatch.setattr(za, "_DATA_DIR", tmp_path)
    text = za._build_local_context("000070")
    assert text is not None
    assert "KDJ" in text and "MACD" in text and "BBI" in text
    assert "000070" in text


def test_prepare_context_falls_through_to_none(monkeypatch, tmp_path):
    from web.backend.services import zettaranc_adapter as za

    monkeypatch.setattr(za, "_DATA_DIR", tmp_path)  # 空目录
    monkeypatch.delenv("ZETTARANC_TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(za, "_ZETTARANC_ROOT", tmp_path / "no_zettaranc")
    ctx = za.prepare_context("999999")
    assert ctx["source"] == "none"
    assert ctx["error"] == "no_data"


def test_prepare_context_uses_local_csv_when_no_token(monkeypatch, tmp_path):
    from web.backend.services import zettaranc_adapter as za

    _csv_fixture(tmp_path, code="000070")
    monkeypatch.setattr(za, "_DATA_DIR", tmp_path)
    monkeypatch.delenv("ZETTARANC_TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr(za, "_ZETTARANC_ROOT", tmp_path / "no_zettaranc")
    ctx = za.prepare_context("000070")
    assert ctx["source"] == "local_csv"
    assert "KDJ" in ctx["text"]


# ---------- helpers ----------


def _fake_path(content: str) -> Path:
    """构造一个 Path-like 对象，让 .exists() 为真且 .read_text() 返回 content。"""
    import tempfile

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)
