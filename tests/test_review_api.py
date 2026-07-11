"""验证复盘 FastAPI 接口的 HTTP 契约与文件安全映射。"""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from starlette.datastructures import UploadFile

from web.backend.routers import review
from web.backend.services import review_title_service as title_module
from web.backend.services.review_repository import ReviewDocument, ReviewRepository
from web.backend.services.review_service import ReviewService


def _image_bytes(image_format: str) -> bytes:
    image = Image.new("RGB", (2, 2), "red")
    raw = BytesIO()
    image.save(raw, format=image_format)
    return raw.getvalue()


def _png_bytes() -> bytes:
    return _image_bytes("PNG")


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


def test_add_stock_creates_a_missing_review(client: TestClient) -> None:
    """首个股票追加请求必须创建标准复盘，而不是要求客户端先发创建请求。"""
    response = client.post(
        "/api/reviews/2026-07-11/stocks",
        json={"code": "688802", "name": "沐曦股份"},
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["already_exists"] is False
    assert payload["title"] == "2026-07-11 交易复盘"
    assert payload["stocks"] == [{"code": "688802", "name": "沐曦股份"}]


def test_generate_title_sanitizes_provider_errors(client: TestClient, monkeypatch, caplog) -> None:
    """标题 provider 的内部错误只能留在服务端，响应必须使用固定脱敏信息。"""
    client.post("/api/reviews/2026-07-11")
    private_path = r"C:\private\review_library\config.json"
    monkeypatch.setattr(
        title_module,
        "load_llm_config",
        lambda: {"provider": "deepseek", "deepseek": {"api_key": "test-key"}},
    )

    def raise_provider_error(**_kwargs):
        raise RuntimeError(f"provider failed: {private_path}")

    monkeypatch.setattr(title_module, "call_deepseek", raise_provider_error)

    with caplog.at_level("WARNING", logger="web.backend.routers.review"):
        response = client.post(
            "/api/reviews/2026-07-11/generate-title",
            json={"title": "原始标题", "body": "市场回暖。", "tags": [], "stocks": []},
        )

    assert response.status_code == 200
    assert response.json()["data"]["provider_error"] == "标题服务暂不可用，已使用本地候选"
    assert response.json()["data"]["provider_error_code"] == "provider_unavailable"
    assert private_path not in response.text
    assert "review_library" not in response.text
    assert private_path not in caplog.text
    assert "provider failed" not in caplog.text
    assert "provider_unavailable" in caplog.text
    assert "RuntimeError" in caplog.text


def test_update_deduplicates_normalized_stock_codes(client: TestClient) -> None:
    """HTTP 保存必须复用服务层规则，只持久化同一代码的第一条股票。"""
    created = client.post("/api/reviews/2026-07-11").json()["data"]
    payload = {
        "title": "今日复盘",
        "status": "draft",
        "title_source": "manual",
        "tags": [],
        "stocks": [
            {"code": " 688802 ", "name": "沐曦股份"},
            {"code": "688802", "name": "重复名称"},
        ],
        "body": "半导体观察",
        "version": created["version"],
    }

    saved = client.put("/api/reviews/2026-07-11", json=payload)
    loaded = client.get("/api/reviews/2026-07-11")

    assert saved.status_code == 200
    assert saved.json()["data"]["stocks"] == [{"code": "688802", "name": "沐曦股份"}]
    assert loaded.json()["data"]["stocks"] == [{"code": "688802", "name": "沐曦股份"}]


def test_create_review_is_atomic_for_concurrent_posts(client: TestClient, monkeypatch) -> None:
    """两个并发 POST 只有一个可报告 created=true，版本不会被另一请求立刻覆盖。"""
    barrier = Barrier(2)
    original_new = ReviewDocument.new.__func__

    def synchronized_new(cls, review_date: str):
        barrier.wait(timeout=5)
        return original_new(cls, review_date)

    monkeypatch.setattr(ReviewDocument, "new", classmethod(synchronized_new))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(client.post, "/api/reviews/2026-07-11") for _ in range(2)]
        responses = [future.result(timeout=10) for future in futures]

    payloads = [response.json()["data"] for response in responses]
    current = client.get("/api/reviews/2026-07-11").json()["data"]
    assert all(response.status_code == 200 for response in responses)
    assert sorted(payload["created"] for payload in payloads) == [False, True]
    assert {payload["version"] for payload in payloads} == {current["version"]}


def test_add_stock_normalizes_existing_code_before_deduplication(client: TestClient) -> None:
    """API 追加带空白的既有股票代码时应返回 already_exists，而不是 422。"""
    client.post("/api/reviews/2026-07-11")
    client.post(
        "/api/reviews/2026-07-11/stocks",
        json={"code": "688802", "name": "沐曦股份"},
    )

    response = client.post(
        "/api/reviews/2026-07-11/stocks",
        json={"code": " 688802 ", "name": " 沐曦股份 "},
    )

    assert response.status_code == 200
    assert response.json()["data"]["already_exists"] is True
    assert response.json()["data"]["stocks"] == [{"code": "688802", "name": "沐曦股份"}]


def test_concurrent_same_stock_requests_return_200_and_idempotent_result(client: TestClient) -> None:
    """同股票并发请求不能向用户暴露 409，最终应有一次幂等命中。"""
    client.post("/api/reviews/2026-07-11")
    barrier = Barrier(2)

    def post_stock():
        barrier.wait(timeout=5)
        return client.post(
            "/api/reviews/2026-07-11/stocks",
            json={"code": "688802", "name": "沐曦股份"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = [future.result(timeout=10) for future in [executor.submit(post_stock) for _ in range(2)]]

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["data"]["already_exists"] for response in responses) == [False, True]
    current = client.get("/api/reviews/2026-07-11").json()["data"]
    assert current["stocks"] == [{"code": "688802", "name": "沐曦股份"}]


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


@pytest.mark.parametrize(
    ("filename", "image_format", "content_type"),
    [
        ("chart.jpg", "JPEG", "image/jpeg"),
        ("chart.webp", "WEBP", "image/webp"),
        ("chart.gif", "GIF", "image/gif"),
    ],
)
def test_upload_accepts_supported_image_formats(
    client: TestClient,
    filename: str,
    image_format: str,
    content_type: str,
) -> None:
    """JPEG、WebP 与 GIF 均须通过真实图片签名校验后保存。"""
    client.post("/api/reviews/2026-07-11")

    response = client.post(
        "/api/reviews/2026-07-11/attachments",
        files={"file": (filename, _image_bytes(image_format), content_type)},
    )

    assert response.status_code == 200
    assert response.json()["data"]["content_type"] == content_type


def test_upload_rejects_svg_forged_mime_and_oversized_images(client: TestClient) -> None:
    """SVG、MIME 与签名不符、超过 10 MiB 的附件都必须被拒绝。"""
    client.post("/api/reviews/2026-07-11")
    oversized_png = _png_bytes() + (b"\0" * (10 * 1024 * 1024))
    corrupted_png = bytearray(_png_bytes())
    corrupted_png[corrupted_png.index(b"IDAT") + 4] ^= 0xFF
    responses = [
        client.post(
            "/api/reviews/2026-07-11/attachments",
            files={"file": ("chart.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")},
        ),
        client.post(
            "/api/reviews/2026-07-11/attachments",
            files={"file": ("chart.png", _png_bytes(), "image/jpeg")},
        ),
        client.post(
            "/api/reviews/2026-07-11/attachments",
            files={"file": ("large.png", oversized_png, "image/png")},
        ),
        client.post(
            "/api/reviews/2026-07-11/attachments",
            files={"file": ("corrupted.png", bytes(corrupted_png), "image/png")},
        ),
    ]

    assert all(response.status_code == 422 for response in responses)


def test_oversized_upload_is_read_in_bounded_chunks_and_stops_early(
    client: TestClient,
    monkeypatch,
) -> None:
    """上传超过 10 MiB 时只允许分块读取，并在越界后立即停止。"""
    client.post("/api/reviews/2026-07-11")
    requested_sizes: list[int] = []
    original_read = UploadFile.read

    async def recording_read(upload, size: int = -1):
        requested_sizes.append(size)
        return await original_read(upload, size)

    monkeypatch.setattr(UploadFile, "read", recording_read)
    response = client.post(
        "/api/reviews/2026-07-11/attachments",
        files={"file": ("large.png", _png_bytes() + b"0" * (11 * 1024 * 1024), "image/png")},
    )

    assert response.status_code == 422
    assert requested_sizes
    assert all(0 < size <= 1024 * 1024 for size in requested_sizes)
    assert len(requested_sizes) == 11


@pytest.mark.parametrize(
    "params",
    [
        {"date_from": "2026-7-01"},
        {"date_to": "2026-02-30"},
        {"date_from": "2026-07-12", "date_to": "2026-07-11"},
    ],
)
def test_list_rejects_invalid_or_reversed_date_range(client: TestClient, params: dict) -> None:
    """日期筛选在 API 边界严格校验格式、日历日期与先后顺序。"""
    response = client.get("/api/reviews", params=params)

    assert response.status_code == 422


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
