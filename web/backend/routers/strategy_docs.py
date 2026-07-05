"""战法文档中心接口。

两个文档根：
- ``_DOCS_ROOT = docs/``：本仓库原生战法/系统说明（source="local"）
- ``_ZETTARANC_ROOT = third_party/zettaranc/``：vendor 进来的 zettaranc-skill v3.3.2
  知识库和用户文档（SKILL.md + docs/*.md + knowledge/*.md），通过 source="zettaranc" 区分。

安全约束：
- slug 必须命中白名单且匹配 ^[a-z0-9][a-z0-9-]{0,63}$
- 解析路径后必须 resolve 并回校仍在所属 root 下
- 任何路径分隔符 / "." / ".." 一律 404
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Path as PathParam

router = APIRouter(prefix="/api/strategy-docs", tags=["战法文档"])

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DOCS_ROOT = _PROJECT_ROOT / "docs"
_ZETTARANC_ROOT = _PROJECT_ROOT / "third_party" / "zettaranc"

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class DocEntry:
    """单个文档元数据。relative_path 仅服务器读盘用，前端只看到 slug。"""

    slug: str
    title: str
    category: str
    relative_path: str
    source: str = "local"  # "local" 或 "zettaranc"


_DOC_REGISTRY: tuple[DocEntry, ...] = (
    # -------- 本项目原生战法 --------
    DocEntry("b1-case", "B1 案例战法", "B1 战法", "B1_CASE_STRATEGY.md"),
    DocEntry("b1-stage", "B1 阶段战法", "B1 战法", "B1_STAGE_STRATEGY.md"),
    DocEntry("b1-pattern", "B1 形态匹配", "B1 战法", "B1_PATTERN_MATCH.md"),
    DocEntry("b1-way", "B1 知行用法", "B1 战法", "B1_stage_way.md"),
    DocEntry("b2-strategy", "B2 战法说明", "B2 战法", "B2_STRATEGY.md"),
    DocEntry("b2-pattern", "B2 形态匹配", "B2 战法", "B2_PATTERN_MATCH.md"),
    DocEntry("b2-cases", "B2 案例库", "B2 战法", "B2_STRATEGY_CASE_LIBRARY.md"),
    DocEntry("b2-cases-updated", "B2 案例库（更新版）", "B2 战法", "B2_STRATEGY_CASE_LIBRARY_UPDATED.md"),
    DocEntry("b2-code-notes", "B2 代码注解", "B2 战法", "b2_strategy_code_notes.annotated.md"),
    DocEntry("b2-changelog", "B2 变更日志", "B2 战法", "B2_STRATEGY_CHANGELOG.md"),
    DocEntry("brick-pattern", "砖型图战法", "形态战法", "BRICK_STRATEGY.md"),
    DocEntry("bowl-bottom", "碗底反弹战法", "形态战法", "BOWL_REBOUND_STRATEGY.md"),
    DocEntry("backtest-overview", "回测系统说明", "回测与跟踪", "BACKTEST_OVERVIEW.md"),
    DocEntry("tracking-agent", "跟踪 Agent", "回测与跟踪", "TRACKING_AGENT.md"),
    DocEntry("project-exec", "项目执行逻辑与 Web 说明", "系统说明", "PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md"),
    DocEntry("tech-docs", "技术文档", "系统说明", "technical_documentation.md"),
    # -------- zettaranc-skill 知识库 --------
    DocEntry("zr-skill", "zettaranc 角色协议 SKILL.md", "zettaranc · 核心", "SKILL.md", source="zettaranc"),
    DocEntry("zr-readme", "zettaranc README", "zettaranc · 核心", "README.md", source="zettaranc"),
    DocEntry("zr-user-guide", "zettaranc 使用手册 USER_GUIDE", "zettaranc · 核心", "docs/USER_GUIDE.md", source="zettaranc"),
    DocEntry("zr-changelog", "zettaranc CHANGELOG", "zettaranc · 核心", "docs/CHANGELOG.md", source="zettaranc"),
    DocEntry("zr-changelog-v3", "zettaranc v3.0 变更说明", "zettaranc · 核心", "docs/CHANGELOG-v3.0.md", source="zettaranc"),
    DocEntry("zr-config-guide", "zettaranc 配置指南 CONFIG_GUIDE", "zettaranc · 核心", "docs/CONFIG_GUIDE.md", source="zettaranc"),
    DocEntry("zr-todo", "zettaranc TODO 路线图", "zettaranc · 核心", "docs/TODO.md", source="zettaranc"),
    DocEntry("zr-workflow", "回答工作流 workflow", "zettaranc · 工作流", "knowledge/workflow.md", source="zettaranc"),
    DocEntry("zr-harness", "Harness 约束与纠错", "zettaranc · 工作流", "knowledge/harness.md", source="zettaranc"),
    DocEntry("zr-improvement", "自我改进系统 improvement-system", "zettaranc · 工作流", "knowledge/improvement-system.md", source="zettaranc"),
    DocEntry("zr-improvement-summary", "自我改进系统总结", "zettaranc · 工作流", "docs/IMPROVEMENT_SYSTEM_SUMMARY.md", source="zettaranc"),
    DocEntry("zr-intent-router", "意图路由设计 intent-router", "zettaranc · 工作流", "docs/intent-router-design.md", source="zettaranc"),
    DocEntry("zr-trading-core", "交易内核 trading-core", "zettaranc · 心法", "knowledge/trading-core.md", source="zettaranc"),
    DocEntry("zr-three-best", "三好原则 three-best-principles", "zettaranc · 心法", "knowledge/three-best-principles.md", source="zettaranc"),
    DocEntry("zr-trading-psy", "交易心理 trading-psychology", "zettaranc · 心法", "knowledge/trading-psychology.md", source="zettaranc"),
    DocEntry("zr-sell-discipline", "卖出纪律 sell-discipline", "zettaranc · 心法", "knowledge/sell-discipline.md", source="zettaranc"),
    DocEntry("zr-exit-strategies", "退出战术 exit-strategies", "zettaranc · 心法", "knowledge/exit-strategies.md", source="zettaranc"),
    DocEntry("zr-position-mgmt", "仓位管理 position-management", "zettaranc · 心法", "knowledge/position-management.md", source="zettaranc"),
    DocEntry("zr-portfolio-mgmt", "组合管理 portfolio-management", "zettaranc · 心法", "knowledge/portfolio-management.md", source="zettaranc"),
    DocEntry("zr-heuristics", "决策启发式 heuristics", "zettaranc · 心法", "knowledge/heuristics.md", source="zettaranc"),
    DocEntry("zr-indicators", "技术指标手册 indicators", "zettaranc · 技术", "knowledge/indicators.md", source="zettaranc"),
    DocEntry("zr-key-candles", "关键 K 线 key-candles", "zettaranc · 技术", "knowledge/key-candles.md", source="zettaranc"),
    DocEntry("zr-trend-lines", "趋势线/知行线 trend-lines", "zettaranc · 技术", "knowledge/trend-lines.md", source="zettaranc"),
    DocEntry("zr-breathing", "呼吸节奏 breathing-theory", "zettaranc · 技术", "knowledge/breathing-theory.md", source="zettaranc"),
    DocEntry("zr-four-rhythms", "四节奏 four-rhythms", "zettaranc · 技术", "knowledge/four-rhythms.md", source="zettaranc"),
    DocEntry("zr-six-tracks", "六轨 six-tracks-2026", "zettaranc · 技术", "knowledge/six-tracks-2026.md", source="zettaranc"),
    DocEntry("zr-advanced", "进阶形态 advanced-patterns", "zettaranc · 技术", "knowledge/advanced-patterns.md", source="zettaranc"),
    DocEntry("zr-iron-butterfly", "铁蝴蝶 iron-butterfly", "zettaranc · 技术", "knowledge/iron-butterfly.md", source="zettaranc"),
    DocEntry("zr-life-decision", "人生决策 life-decision", "zettaranc · 决策", "knowledge/life-decision.md", source="zettaranc"),
    DocEntry("zr-life-research", "人生决策研究 life-decision-research", "zettaranc · 决策", "knowledge/life-decision-research.md", source="zettaranc"),
    DocEntry("zr-career", "职业发展 career-development", "zettaranc · 决策", "knowledge/career-development.md", source="zettaranc"),
    DocEntry("zr-business", "商业判断 business-judgment", "zettaranc · 决策", "knowledge/business-judgment.md", source="zettaranc"),
    DocEntry("zr-business-research", "商业判断研究 business-judgment-research", "zettaranc · 决策", "knowledge/business-judgment-research.md", source="zettaranc"),
    DocEntry("zr-framework", "框架提取 framework-extraction", "zettaranc · 决策", "knowledge/framework-extraction.md", source="zettaranc"),
    DocEntry("zr-glossary", "股市术语表 stock-glossary", "zettaranc · 参考", "knowledge/stock-glossary.md", source="zettaranc"),
    DocEntry("zr-data-dict", "数据字典 data_dictionary", "zettaranc · 参考", "knowledge/data_dictionary.md", source="zettaranc"),
    DocEntry("zr-signal-dict", "信号字典 signal_dictionary", "zettaranc · 参考", "knowledge/signal_dictionary.md", source="zettaranc"),
    DocEntry("zr-market-macro", "市场宏观 market-macro", "zettaranc · 参考", "knowledge/market-macro.md", source="zettaranc"),
)

_SLUG_INDEX: dict[str, DocEntry] = {entry.slug: entry for entry in _DOC_REGISTRY}

# 每个 source 对应固定根，_resolve_doc_path 要把目标 resolve 后回校仍在该根下
_SOURCE_ROOTS: dict[str, Path] = {
    "local": _DOCS_ROOT,
    "zettaranc": _ZETTARANC_ROOT,
}


def _resolve_doc_path(entry: DocEntry) -> Optional[Path]:
    """白名单条目 → 实际磁盘路径；resolve 后回校仍在所属 root 下，避免符号链接逃逸。"""
    root = _SOURCE_ROOTS.get(entry.source)
    if root is None:
        return None
    candidate = (root / entry.relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _entry_to_meta(entry: DocEntry) -> Optional[dict]:
    """生成列表 API 的元数据；文件缺失返回 None 由调用方过滤。"""
    path = _resolve_doc_path(entry)
    if path is None:
        return None
    stat = path.stat()
    return {
        "slug": entry.slug,
        "title": entry.title,
        "category": entry.category,
        "source": entry.source,
        "updated_at": int(stat.st_mtime),
        "size": stat.st_size,
    }


@router.get("")
async def list_strategy_docs():
    """返回所有白名单文档（缺失自动跳过）和分类顺序。"""
    items: list[dict] = []
    for entry in _DOC_REGISTRY:
        meta = _entry_to_meta(entry)
        if meta is not None:
            items.append(meta)
    categories: list[str] = []
    for entry in _DOC_REGISTRY:
        if entry.category not in categories:
            # 仅当至少存在一个 item 已纳入时显示该分类，避免空分类抖动
            if any(it["category"] == entry.category for it in items):
                categories.append(entry.category)
    return {"success": True, "data": {"categories": categories, "items": items}}


@router.get("/{slug}")
async def get_strategy_doc(slug: str = PathParam(..., min_length=1, max_length=64)):
    """按 slug 查白名单 → 返回原始 Markdown 文本。

    - slug 必须匹配 ^[a-z0-9][a-z0-9-]{0,63}$ 且命中白名单
    - 不接受任何路径分隔符、"."、".."
    - 文件缺失返回 404，避免泄露磁盘细节
    """
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=404, detail="文档不存在")
    entry = _SLUG_INDEX.get(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    path = _resolve_doc_path(entry)
    if path is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="文档读取失败") from exc
    return {
        "success": True,
        "data": {
            "slug": entry.slug,
            "title": entry.title,
            "category": entry.category,
            "source": entry.source,
            "content": content,
            "updated_at": int(path.stat().st_mtime),
        },
    }
