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


def _png_bytes(color: str = "white") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color).save(buffer, format="PNG")
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


def test_new_document_uses_manual_title_source_by_default() -> None:
    """新建复盘默认由用户手动维护标题。"""
    assert ReviewDocument.new("2026-07-11").title_source == "manual"


def test_saved_frontmatter_uses_date_and_migrates_legacy_review_date(tmp_path) -> None:
    """旧 review_date 可读，但下一次保存必须迁移到规范 date 字段。"""
    repo = ReviewRepository(tmp_path)
    path = tmp_path / "2026" / "07" / "2026-07-11.md"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        (
            "---\n"
            "review_date: '2026-07-11'\n"
            "title: 旧格式复盘\n"
            "status: draft\n"
            "title_source: manual\n"
            "tags: []\n"
            "stocks: []\n"
            "created_at: '2026-07-11T09:00:00+08:00'\n"
            "updated_at: '2026-07-11T09:00:00+08:00'\n"
            "---\n"
            "正文\n"
        ).encode("utf-8")
    )

    legacy = repo.load("2026-07-11")
    repo.save(legacy, expected_version=legacy.version)
    snapshot = path.read_text(encoding="utf-8")

    assert legacy.review_date == "2026-07-11"
    assert "\ndate: '2026-07-11'\n" in snapshot
    assert "review_date:" not in snapshot


def test_load_accepts_utf8_bom_and_crlf_without_rewriting_body_newlines(tmp_path) -> None:
    """解析 BOM/CRLF frontmatter 时保留正文原始换行。"""
    repo = ReviewRepository(tmp_path)
    path = tmp_path / "2026" / "07" / "2026-07-11.md"
    path.parent.mkdir(parents=True)
    raw = (
        b"\xef\xbb\xbf---\r\n"
        b"date: '2026-07-11'\r\n"
        b"title: CRLF review\r\n"
        b"status: draft\r\n"
        b"title_source: manual\r\n"
        b"tags: []\r\n"
        b"stocks: []\r\n"
        b"created_at: '2026-07-11T09:00:00+08:00'\r\n"
        b"updated_at: '2026-07-11T09:00:00+08:00'\r\n"
        b"---\r\n"
        b"line one\r\nline two\r\n"
    )
    path.write_bytes(raw)

    loaded = repo.load("2026-07-11")

    assert loaded.body == "line one\r\nline two\r\n"
    assert repo.iter_documents() == [loaded]


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

    assert attachment.filename == "chart-0001.png"
    assert repo.read_attachment("2026-07-11", attachment.filename).raw == _png_bytes()


def test_repeated_attachment_names_are_unique_sorted_and_keep_real_extension(tmp_path):
    """重复剪贴板文件名不得覆盖，生成名按序号稳定排序并保留图片真实格式。"""
    repo = ReviewRepository(tmp_path)
    first_raw = _png_bytes("white")
    second_raw = _png_bytes("black")

    first = repo.save_attachment("2026-07-11", "clipboard.png", "image/png", first_raw)
    second = repo.save_attachment("2026-07-11", "clipboard.png", "image/png", second_raw)

    assert [first.filename, second.filename] == ["clipboard-0001.png", "clipboard-0002.png"]
    assert [item.filename for item in repo.list_attachments("2026-07-11")] == [
        "clipboard-0001.png",
        "clipboard-0002.png",
    ]
    assert repo.read_attachment("2026-07-11", first.filename).raw == first_raw
    assert repo.read_attachment("2026-07-11", second.filename).raw == second_raw


def test_attachment_delete_and_document_save_share_the_date_lock(tmp_path, monkeypatch):
    """附件引用检查到删除期间，同日期文档保存不得穿插进入。"""
    repo = ReviewRepository(tmp_path)
    current = repo.save(ReviewDocument.new("2026-07-11"))
    attachment = repo.save_attachment("2026-07-11", "chart.png", "image/png", _png_bytes())
    attachment_path = tmp_path / "2026" / "07" / "2026-07-11.assets" / attachment.filename
    unlink_started = threading.Event()
    allow_unlink = threading.Event()
    original_unlink = type(attachment_path).unlink

    def delayed_unlink(path, *args, **kwargs):
        if path == attachment_path:
            unlink_started.set()
            assert allow_unlink.wait(timeout=5)
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(attachment_path), "unlink", delayed_unlink)
    updated = replace(current, title="并发保存")
    with ThreadPoolExecutor(max_workers=2) as executor:
        deleting = executor.submit(repo.delete_attachment, "2026-07-11", attachment.filename)
        assert unlink_started.wait(timeout=5)
        saving = executor.submit(repo.save, updated, current.version)
        time.sleep(0.1)
        save_was_blocked = not saving.done()
        allow_unlink.set()
        deleting.result(timeout=5)
        saving.result(timeout=5)

    assert save_was_blocked is True


@pytest.mark.parametrize(
    "reference_prefix",
    ["./2026-07-11.assets/", "2026-07-11.assets/"],
)
def test_attachment_rejects_path_traversal_and_referenced_delete(tmp_path, reference_prefix):
    repo = ReviewRepository(tmp_path)
    repo.save(ReviewDocument.new("2026-07-11"))
    attachment = repo.save_attachment("2026-07-11", "chart.png", "image/png", _png_bytes())
    current = repo.load("2026-07-11")
    repo.save(
        replace(current, body=f"![图表]({reference_prefix}{attachment.filename})"),
        expected_version=current.version,
    )

    with pytest.raises(ReviewValidationError):
        repo.read_attachment("2026-07-11", "../outside.png")
    with pytest.raises(ReviewAttachmentReferencedError):
        repo.delete_attachment("2026-07-11", attachment.filename)

    repo.delete_attachment("2026-07-11", attachment.filename, force=True)
    assert repo.list_attachments("2026-07-11") == []


def test_scan_documents_reports_malformed_yaml_without_blocking_valid_files(tmp_path):
    repo = ReviewRepository(tmp_path)
    repo.save(ReviewDocument.new("2026-07-10"))
    malformed = tmp_path / "2026" / "07" / "2026-07-11.md"
    malformed.parent.mkdir(parents=True, exist_ok=True)
    malformed.write_bytes(b"---\ntitle: [unterminated\n---\nbody")

    documents, warnings = repo.scan_documents()

    assert [document.review_date for document in documents] == ["2026-07-10"]
    assert len(warnings) == 1
    assert warnings[0].review_date == "2026-07-11"
    assert warnings[0].relative_path == "2026/07/2026-07-11.md"
    assert "备份" in str(warnings[0])
    assert str(tmp_path.resolve()) not in str(warnings[0])
    assert repo.iter_documents() == documents


def test_parse_failure_does_not_expose_absolute_document_path(tmp_path):
    """损坏 Markdown 的校验错误不得包含磁盘绝对路径。"""
    repo = ReviewRepository(tmp_path)
    malformed = tmp_path / "2026" / "07" / "2026-07-11.md"
    malformed.parent.mkdir(parents=True)
    malformed.write_bytes(b"not-frontmatter")

    with pytest.raises(ReviewValidationError) as captured:
        repo.load("2026-07-11")

    assert str(tmp_path.resolve()) not in str(captured.value)
