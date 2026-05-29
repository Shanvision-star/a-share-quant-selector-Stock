"""战法文档中心接口。

只对外暴露白名单内的 Markdown 文件（位于 docs/ 下），通过常量 slug 映射，
避免任何用户可控字符串拼路径，防止路径穿越。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Path as PathParam, Query

router = APIRouter(prefix="/api/strategy-docs", tags=["战法文档"])

# 仓库根目录（routers → backend → web → repo）
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DOCS_ROOT = _PROJECT_ROOT / "docs"

# slug 严格约束：仅小写字母数字和短横线，避免任何路径片段进入
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class DocEntry:
    """单个文档元数据。relative_path 仅用于服务器读盘，前端只看到 slug。"""

    slug: str
    title: str
    category: str
    relative_path: str  # 相对于 docs/ 的相对路径


# 文档白名单：按分类组织，所有文件必须实际存在于 docs/ 下；不实际存在的会在 list 时过滤掉
_DOC_REGISTRY: tuple[DocEntry, ...] = (
    # B1 战法
    DocEntry("b1-case", "B1 案例战法", "B1", "B1_CASE_STRATEGY.md"),
    DocEntry("b1-stage", "B1 阶段战法", "B1", "B1_STAGE_STRATEGY.md"),
    DocEntry("b1-pattern", "B1 形态匹配", "B1", "B1_PATTERN_MATCH.md"),
    # B2 战法
    DocEntry("b2-strategy", "B2 战法说明", "B2", "B2_STRATEGY.md"),
    DocEntry("b2-pattern", "B2 形态匹配", "B2", "B2_PATTERN_MATCH.md"),
    DocEntry("b2-cases", "B2 案例库", "B2", "B2_STRATEGY_CASE_LIBRARY.md"),
    DocEntry("b2-code-notes", "B2 代码注解", "B2", "b2_strategy_code_notes.annotated.md"),
    # 砖型图 / 碗底（本任务新建专题）
    DocEntry("brick-pattern", "砖型图战法", "砖型图", "BRICK_STRATEGY.md"),
    DocEntry("bowl-bottom", "碗底反弹战法", "碗底", "BOWL_REBOUND_STRATEGY.md"),
    # 回测 / 跟踪
    DocEntry("backtest-overview", "回测系统说明", "回测", "BACKTEST_OVERVIEW.md"),
    DocEntry("tracking-agent", "跟踪 Agent", "跟踪", "TRACKING_AGENT.md"),
    # 系统说明
    DocEntry("project-exec", "项目执行逻辑与 Web 说明", "系统", "PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md"),
    DocEntry("tech-docs", "技术文档", "系统", "technical_documentation.md"),
)

_SLUG_INDEX: dict[str, DocEntry] = {entry.slug: entry for entry in _DOC_REGISTRY}


def _resolve_doc_path(entry: DocEntry) -> Optional[Path]:
    """把白名单条目映射到实际磁盘路径；做 resolve 后再校验仍在 docs/ 之下。"""
    # 注意：relative_path 来源是模块常量，不接受用户输入；这里二次校验是纵深防御
    candidate = (_DOCS_ROOT / entry.relative_path).resolve()
    try:
        candidate.relative_to(_DOCS_ROOT.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _entry_to_meta(entry: DocEntry) -> Optional[dict]:
    """生成列表 API 返回的元数据；文件缺失返回 None 由调用方过滤。"""
    path = _resolve_doc_path(entry)
    if path is None:
        return None
    stat = path.stat()
    return {
        "slug": entry.slug,
        "title": entry.title,
        "category": entry.category,
        "updated_at": int(stat.st_mtime),
        "size": stat.st_size,
    }


@router.get("")
async def list_strategy_docs():
    """返回所有白名单文档（缺失文件自动跳过）和分类顺序。"""
    items: list[dict] = []
    for entry in _DOC_REGISTRY:
        meta = _entry_to_meta(entry)
        if meta is not None:
            items.append(meta)
    # 保持分类列表顺序与白名单出现顺序一致，避免前端排序漂移
    categories: list[str] = []
    for entry in _DOC_REGISTRY:
        if entry.category not in categories:
            categories.append(entry.category)
    return {"success": True, "data": {"categories": categories, "items": items}}


@router.get("/{slug}")
async def get_strategy_doc(slug: str = PathParam(..., min_length=1, max_length=64)):
    """按 slug 查白名单 → 返回原始 Markdown 文本。

    - slug 必须满足 ^[a-z0-9][a-z0-9-]{0,63}$ 且命中白名单
    - 不接受任何路径分隔符、"."、".."
    - 文件缺失返回 404，避免泄露磁盘细节
    """
    if not _SLUG_RE.match(slug):
        # slug 形式非法直接 404，不区分“非法格式”和“不存在”
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
        # 读盘异常返回 500 但不返回 raw exception message
        raise HTTPException(status_code=500, detail="文档读取失败") from exc
    return {
        "success": True,
        "data": {
            "slug": entry.slug,
            "title": entry.title,
            "category": entry.category,
            "content": content,
            "updated_at": int(path.stat().st_mtime),
        },
    }
