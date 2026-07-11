"""验证 Markdown 复盘仓储的持久化与文件安全边界。"""

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import threading
import time

from PIL import Image
import pytest

from web.backend.services.review_repository import (
    ReviewAttachmentReferencedError,
    ReviewConflictError,
    ReviewDocument,
    ReviewRepository,
    ReviewStock,
    ReviewValidationError,
)


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_save_and_load_round_trip_preserves_frontmatter_and_stock_code(tmp_path):
    repo = ReviewRepository(tmp_path)
    document = ReviewDocument.new("2026-07-11")
    document = replace(
        document,
        title="沐曦放量突破",
        status="follow_up",
        title_source="manual",
        tags=("B1", "半导体"),
        stocks=(ReviewStock(code="000001", name="平安银行"),),
        body="## 重点股票\n\n观察量能。\n",
    )

    saved = repo.save(document)
    loaded = repo.load("2026-07-11")

    assert saved.version
    assert loaded == saved
    assert loaded.stocks[0].code == "000001"
    assert (tmp_path / "2026" / "07" / "2026-07-11.md").is_file()


@pytest.mark.parametrize("review_date", ["2026-7-11", "2026-02-30", "../2026-07-11", "2026-07-11/evil"])
def test_rejects_invalid_review_date_and_path_traversal(tmp_path, review_date):
    repo = ReviewRepository(tmp_path)

    with pytest.raises(ReviewValidationError):
        repo.load(review_date)


def test_iter_documents_returns_dates_in_descending_order(tmp_path):
    repo = ReviewRepository(tmp_path)
    repo.save(ReviewDocument.new("2026-07-10"))
    repo.save(ReviewDocument.new("2026-07-11"))

    assert [document.review_date for document in repo.iter_documents()] == ["2026-07-11", "2026-07-10"]


def test_create_if_absent_is_atomic_for_concurrent_calls(tmp_path):
    """同一日期并发条件创建时，只有一个调用可创建文件。"""
    repo = ReviewRepository(tmp_path)
    barrier = threading.Barrier(2)

    def create():
        barrier.wait(timeout=5)
        return repo.create_if_absent(ReviewDocument.new("2026-07-11"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]

    documents, created_flags = zip(*results)
    assert sorted(created_flags) == [False, True]
    assert len({document.version for document in documents}) == 1
    assert repo.load("2026-07-11").version == documents[0].version


def test_save_uses_same_directory_atomic_replace(tmp_path, monkeypatch):
    repo = ReviewRepository(tmp_path)
    calls = []
    original_replace = __import__("os").replace

    def recording_replace(source, target):
        calls.append((source, target))
        return original_replace(source, target)

    monkeypatch.setattr("web.backend.services.review_repository.os.replace", recording_replace)

    repo.save(ReviewDocument.new("2026-07-11"))

    source, target = calls[-1]
    assert source.parent == target.parent == tmp_path / "2026" / "07"
    assert target.name == "2026-07-11.md"


def test_save_rejects_stale_version(tmp_path):
    repo = ReviewRepository(tmp_path)
    original = repo.save(ReviewDocument.new("2026-07-11"))
    repo.save(replace(original, title="新标题"), expected_version=original.version)

    with pytest.raises(ReviewConflictError):
        repo.save(replace(original, title="旧页面标题"), expected_version=original.version)


def test_concurrent_saves_allow_only_one_matching_expected_version(tmp_path, monkeypatch):
    repo = ReviewRepository(tmp_path)
    original = repo.save(ReviewDocument.new("2026-07-11"))
    start = threading.Barrier(2)
    original_atomic_write = repo._atomic_write

    def delayed_atomic_write(path, raw):
        time.sleep(0.1)
        original_atomic_write(path, raw)

    monkeypatch.setattr(repo, "_atomic_write", delayed_atomic_write)

    def save(title):
        start.wait()
        try:
            return repo.save(replace(original, title=title), expected_version=original.version)
        except ReviewConflictError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, ("标题一", "标题二")))

    assert len([result for result in results if isinstance(result, ReviewDocument)]) == 1
    assert len([result for result in results if isinstance(result, ReviewConflictError)]) == 1


def test_attachment_requires_valid_image_signature_and_size_limit(tmp_path):
    repo = ReviewRepository(tmp_path)

    with pytest.raises(ReviewValidationError):
        repo.save_attachment("2026-07-11", "not-image.png", "image/png", b"not a PNG")
    with pytest.raises(ReviewValidationError):
        repo.save_attachment("2026-07-11", "large.png", "image/png", b"0" * (10 * 1024 * 1024 + 1))

    attachment = repo.save_attachment("2026-07-11", "chart.png", "image/png", _png_bytes())

    assert attachment.filename == "chart.png"
    assert repo.read_attachment("2026-07-11", "chart.png").raw == _png_bytes()


@pytest.mark.parametrize(
    "reference",
    ["./2026-07-11.assets/chart.png", "2026-07-11.assets/chart.png"],
)
def test_attachment_rejects_path_traversal_and_referenced_delete(tmp_path, reference):
    repo = ReviewRepository(tmp_path)
    repo.save(ReviewDocument.new("2026-07-11"))
    repo.save_attachment("2026-07-11", "chart.png", "image/png", _png_bytes())
    current = repo.load("2026-07-11")
    repo.save(
        replace(current, body=f"![图表]({reference})"),
        expected_version=current.version,
    )

    with pytest.raises(ReviewValidationError):
        repo.read_attachment("2026-07-11", "../outside.png")
    with pytest.raises(ReviewAttachmentReferencedError):
        repo.delete_attachment("2026-07-11", "chart.png")

    repo.delete_attachment("2026-07-11", "chart.png", force=True)
    assert repo.list_attachments("2026-07-11") == []


def test_iter_documents_skips_malformed_yaml_frontmatter(tmp_path):
    repo = ReviewRepository(tmp_path)
    malformed = tmp_path / "2026" / "07" / "2026-07-11.md"
    malformed.parent.mkdir(parents=True)
    malformed.write_bytes(b"---\ntitle: [unterminated\n---\nbody")

    assert repo.iter_documents() == []
