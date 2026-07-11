"""验证复盘 FastAPI 接口的 HTTP 契约与文件安全映射。"""

from io import BytesIO

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from web.backend.routers import review
from web.backend.services import review_title_service as title_module
from web.backend.services.review_repository import ReviewRepository
from web.backend.services.review_service import ReviewService


def _png_bytes() -> bytes:
    image = Image.new("RGB", (2, 2), "red")
    raw = BytesIO()
    image.save(raw, format="PNG")
    return raw.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    """用临时仓储和离线标题服务装配路由，禁止访问用户数据。"""
    repository = ReviewRepository(tmp_path / "review_library")
    service = ReviewService(repository)
    title_service = title_module.ReviewTitleService()
    monkeypatch.setattr(title_module, "load_llm_config", lambda: {"provider": "mock"})

    app = FastAPI()
    app.include_router(review.router)
    app.dependency_overrides[review.get_review_service] = lambda: service
    app.dependency_overrides[review.get_review_repository] = lambda: repository
    app.dependency_overrides[review.get_review_title_service] = lambda: title_service
    return TestClient(app)


def test_create_read_list_update_and_conflict(client: TestClient) -> None:
    """创建幂等、读取、筛选、保存和旧版本冲突均使用统一 envelope。"""
    first = client.post("/api/reviews/2026-07-11")
    second = client.post("/api/reviews/2026-07-11")

    assert first.status_code == 200
    assert first.json()["data"]["created"] is True
    assert second.json()["data"]["created"] is False

    created = first.json()["data"]
    payload = {
        "title": "今日复盘",
        "status": "follow_up",
        "title_source": "manual",
        "tags": ["B1"],
        "stocks": [{"code": "688802", "name": "沐曦股份"}],
        "body": "半导体观察",
        "version": created["version"],
    }
    saved = client.put("/api/reviews/2026-07-11", json=payload)
    stale = client.put("/api/reviews/2026-07-11", json=payload)
    loaded = client.get("/api/reviews/2026-07-11")
    listed = client.get("/api/reviews", params={"query": "沐曦", "status": "follow_up"})

    assert saved.status_code == 200
    assert saved.json()["success"] is True
    assert stale.status_code == 409
    assert loaded.json()["data"]["title"] == "今日复盘"
    assert listed.json()["data"]["total"] == 1
    assert listed.json()["data"]["items"][0]["review_date"] == "2026-07-11"


def test_add_stock_deduplicates_and_title_generation_stays_offline(client: TestClient) -> None:
    """同一股票只追加一次，未配置 provider 时返回本地标题候选。"""
    client.post("/api/reviews/2026-07-11")

    first = client.post(
        "/api/reviews/2026-07-11/stocks",
        json={"code": "688802", "name": "沐曦股份"},
    )
    second = client.post(
        "/api/reviews/2026-07-11/stocks",
        json={"code": "688802", "name": "沐曦股份"},
    )
    title = client.post(
        "/api/reviews/2026-07-11/generate-title",
        json={
            "title": "原始标题",
            "body": "市场情绪回暖。",
            "tags": ["B1"],
            "stocks": [{"code": "688802", "name": "沐曦股份"}],
        },
    )

    assert first.status_code == 200
    assert first.json()["data"]["already_exists"] is False
    assert second.json()["data"]["already_exists"] is True
    assert title.status_code == 200
    assert title.json()["data"]["source"] == "local_fallback"
    assert title.json()["data"]["provider_fallback"] is True
    assert "沐曦股份" in title.json()["data"]["title"]


def test_upload_read_list_and_delete_attachment(client: TestClient) -> None:
    """附件上传、二进制读取、列表与删除均只经由仓储安全边界。"""
    client.post("/api/reviews/2026-07-11")
    uploaded = client.post(
        "/api/reviews/2026-07-11/attachments",
        files={"file": ("chart.png", _png_bytes(), "image/png")},
    )

    assert uploaded.status_code == 200
    attachment = uploaded.json()["data"]
    filename = attachment["filename"]
    listed = client.get("/api/reviews/2026-07-11/attachments")
    downloaded = client.get(f"/api/reviews/2026-07-11/attachments/{filename}")
    deleted = client.delete(f"/api/reviews/2026-07-11/attachments/{filename}")
    missing = client.get(f"/api/reviews/2026-07-11/attachments/{filename}")

    assert listed.json()["data"]["items"] == [
        {"filename": filename, "content_type": "image/png", "size": len(_png_bytes())}
    ]
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.content == _png_bytes()
    assert deleted.json()["data"]["deleted"] is True
    assert missing.status_code == 404


def test_invalid_dates_and_path_traversal_are_rejected_without_path_leaks(client: TestClient) -> None:
    """非法日期及附件路径穿越只得到客户端安全的 422 或 404。"""
    invalid_date = client.post("/api/reviews/2026-02-30")
    client.post("/api/reviews/2026-07-11")
    unsafe_upload = client.post(
        "/api/reviews/2026-07-11/attachments",
        files={"file": ("../outside.png", _png_bytes(), "image/png")},
    )
    traversal = client.get("/api/reviews/2026-07-11/attachments/..%2Foutside.png")

    assert invalid_date.status_code == 422
    assert unsafe_upload.status_code == 422
    assert traversal.status_code in {404, 422}
    for response in (invalid_date, unsafe_upload, traversal):
        assert "review_library" not in response.text
        assert "tmp" not in response.text
