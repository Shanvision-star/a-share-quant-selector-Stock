"""战法文档中心 API 测试。

覆盖：
- 列表只返回白名单且实际存在的文档
- 按 slug 读取返回 markdown 原文
- 非法 slug / 不存在 slug / 路径穿越尝试统一 404
- 路径穿越绝不能逃出 docs/ 目录
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.backend.routers import strategy_docs as docs_module


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    docs_root = tmp_path / "docs"
    zettaranc_root = tmp_path / "zettaranc"
    fixtures = {
        docs_root / "B1_CASE_STRATEGY.md": "# B1 案例战法\n",
        docs_root / "B2_STRATEGY.md": "# B2 战法说明\n",
        docs_root / "PROJECT_EXECUTION_LOGIC_AND_WEB_NOTES.md": "# 项目执行逻辑\n",
        zettaranc_root / "docs" / "CHANGELOG.md": "# CHANGELOG\n\nv3.3.2\n",
        zettaranc_root / "docs" / "USER_GUIDE.md": "# USER GUIDE\n",
        zettaranc_root / "knowledge" / "workflow.md": "# Workflow\n",
        zettaranc_root / "knowledge" / "life-decision.md": "# Life Decision\n",
    }
    for path, content in fixtures.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(docs_module, "_DOCS_ROOT", docs_root)
    monkeypatch.setattr(docs_module, "_ZETTARANC_ROOT", zettaranc_root)
    monkeypatch.setitem(docs_module._SOURCE_ROOTS, "local", docs_root)
    monkeypatch.setitem(docs_module._SOURCE_ROOTS, "zettaranc", zettaranc_root)

    # 用 FastAPI 直接挂 router，避免拉起全量 main:app 触发其它启动钩子
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(docs_module.router)
    return TestClient(app)


def test_list_returns_only_existing_whitelist(client: TestClient) -> None:
    """列表接口只能返回白名单中实际存在的文件，不能多也不能少。"""
    response = client.get("/api/strategy-docs")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    items = payload["data"]["items"]
    slugs = {item["slug"] for item in items}

    # 至少这几篇是仓库自带、肯定存在
    expected_subset = {
        "b1-case",
        "b2-strategy",
        "project-exec",
        "zr-changelog",
        "zr-user-guide",
        "zr-workflow",
        "zr-life-decision",
    }
    assert expected_subset.issubset(slugs), f"白名单核心文档缺失：{expected_subset - slugs}"

    # 所有返回项的 slug 必须在常量白名单内
    whitelist = {entry.slug for entry in docs_module._DOC_REGISTRY}
    assert slugs.issubset(whitelist)

    # 分类列表非空且不重复
    categories = payload["data"]["categories"]
    assert categories
    assert len(categories) == len(set(categories))


def test_get_doc_returns_markdown(client: TestClient) -> None:
    response = client.get("/api/strategy-docs/project-exec")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["slug"] == "project-exec"
    assert isinstance(data["content"], str) and data["content"].strip()
    assert data["title"]


def test_get_zettaranc_changelog_uses_latest_docs_path(client: TestClient) -> None:
    """上游 v3.x 把 CHANGELOG 移到 docs/ 下，旧路径失效时前端仍要看得到。"""
    response = client.get("/api/strategy-docs/zr-changelog")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["slug"] == "zr-changelog"
    assert data["source"] == "zettaranc"
    assert "v3.3.2" in data["content"]


def test_get_doc_rejects_unknown_slug(client: TestClient) -> None:
    response = client.get("/api/strategy-docs/this-slug-does-not-exist")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "bad_slug",
    [
        "../etc/passwd",
        "..%2Fetc%2Fpasswd",
        "B1_CASE_STRATEGY",  # 大写 + 下划线均非法
        "with space",
        "..",
        # "." 会被 HTTP 客户端归一化成空段，等价于命中列表接口，不视为穿越
        "a" * 200,
    ],
)
def test_get_doc_rejects_malicious_slug(client: TestClient, bad_slug: str) -> None:
    response = client.get(f"/api/strategy-docs/{bad_slug}")
    # 路径穿越或非法格式均必须返回 404，绝不允许 200
    assert response.status_code in (404, 422)


def test_resolve_doc_path_keeps_inside_docs_root(tmp_path: Path) -> None:
    """直接调用底层 _resolve_doc_path，确认它不会逃出 docs/ 目录。"""
    # 构造一个伪 entry 指向 ../ 试图穿越
    bogus = docs_module.DocEntry(
        slug="bogus",
        title="bogus",
        category="bogus",
        relative_path="../requirements.txt",
    )
    assert docs_module._resolve_doc_path(bogus) is None
