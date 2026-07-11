"""验证复盘业务服务的模板、检索和股票去重行为。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from web.backend.services.review_repository import ReviewDocument, ReviewRepository
from web.backend.services.review_service import ReviewService


def test_create_or_get_saves_standard_template_once(tmp_path) -> None:
    """首次创建写入标准模板，重复请求返回同一份文档。"""
    service = ReviewService(ReviewRepository(tmp_path))

    created, was_created = service.create_or_get("2026-07-11")
    loaded, was_created_again = service.create_or_get("2026-07-11")

    assert was_created is True
    assert was_created_again is False
    assert loaded.version == created.version
    assert created.body == (
        "# 2026-07-11 交易复盘\n\n"
        "## 市场环境\n\n"
        "## 今日计划与实际执行\n\n"
        "## 重点股票\n\n"
        "## 错误与交易纪律\n\n"
        "## 明日跟踪清单\n"
    )


def test_add_stock_appends_one_section_and_deduplicates(tmp_path) -> None:
    """同一股票代码只写入一次 frontmatter 和标准章节。"""
    service = ReviewService(ReviewRepository(tmp_path))
    service.create_or_get("2026-07-11")

    first = service.add_stock("2026-07-11", "688802", "沐曦股份")
    second = service.add_stock("2026-07-11", "688802", "沐曦股份")

    assert first["already_exists"] is False
    assert second["already_exists"] is True
    assert first["document"].body.count("### 688802 沐曦股份") == 1
    assert second["document"].stocks == first["document"].stocks


def test_add_stock_creates_missing_review_with_standard_template(tmp_path) -> None:
    """首次加入股票会原子创建当天复盘，并保留标准模板章节。"""
    service = ReviewService(ReviewRepository(tmp_path))

    result = service.add_stock("2026-07-11", "688802", "沐曦股份")

    assert result["already_exists"] is False
    assert [(stock.code, stock.name) for stock in result["document"].stocks] == [("688802", "沐曦股份")]
    assert "## 市场环境" in result["document"].body
    assert "### 688802 沐曦股份" in result["document"].body


def test_list_reviews_searches_title_stock_tag_and_body(tmp_path) -> None:
    """关键词同时覆盖标题、股票、标签与正文。"""
    service = ReviewService(ReviewRepository(tmp_path))
    service.create_or_get("2026-07-11")
    service.add_stock("2026-07-11", "688802", "沐曦股份")
    current = service.get_review("2026-07-11")
    service.update_review(
        "2026-07-11",
        title="沐曦放量突破",
        status="follow_up",
        title_source="manual",
        tags=["B1"],
        stocks=[{"code": "688802", "name": "沐曦股份"}],
        body="半导体观察",
        expected_version=current.version,
    )

    assert len(service.list_reviews(query="放量")["items"]) == 1
    assert len(service.list_reviews(query="688802")["items"]) == 1
    assert len(service.list_reviews(query="b1")["items"]) == 1
    assert len(service.list_reviews(query="半导体")["items"]) == 1


def test_list_reviews_applies_status_date_and_pagination(tmp_path) -> None:
    """列表先过滤再按日期倒序分页，并提供总数。"""
    service = ReviewService(ReviewRepository(tmp_path))
    for review_date, status in [
        ("2026-07-09", "draft"),
        ("2026-07-10", "follow_up"),
        ("2026-07-11", "follow_up"),
    ]:
        document, _ = service.create_or_get(review_date)
        service.update_review(
            review_date,
            title=f"{review_date} 交易复盘",
            status=status,
            title_source="manual",
            tags=[],
            stocks=[],
            body="",
            expected_version=document.version,
        )

    result = service.list_reviews(
        status="follow_up",
        date_from="2026-07-10",
        date_to="2026-07-11",
        limit=1,
        offset=1,
    )

    assert result["total"] == 2
    assert [item.review_date for item in result["items"]] == ["2026-07-10"]


def test_list_reviews_returns_recoverable_warning_for_corrupt_markdown(tmp_path) -> None:
    """单篇损坏文件不阻断列表，并返回相对路径与恢复提示。"""
    service = ReviewService(ReviewRepository(tmp_path))
    service.create_or_get("2026-07-10")
    malformed = tmp_path / "2026" / "07" / "2026-07-11.md"
    malformed.write_bytes(b"---\ntitle: [unterminated\n---\nbody")

    result = service.list_reviews()

    assert [item.review_date for item in result["items"]] == ["2026-07-10"]
    assert result["warnings"] == [{
        "review_date": "2026-07-11",
        "relative_path": "2026/07/2026-07-11.md",
        "message": "复盘文件无法解析，请先备份原文件后修复 frontmatter 或 UTF-8 编码",
    }]


def test_update_review_deduplicates_normalized_stock_codes(tmp_path) -> None:
    """更新路径保留同一代码的第一条股票，并规范化代码空白。"""
    repository = ReviewRepository(tmp_path)
    service = ReviewService(repository)
    current, _ = service.create_or_get("2026-07-11")

    saved = service.update_review(
        "2026-07-11",
        title="今日复盘",
        status="draft",
        title_source="manual",
        tags=[],
        stocks=[
            {"code": " 688802 ", "name": "沐曦股份"},
            {"code": "688802", "name": "重复名称"},
        ],
        body="半导体观察",
        expected_version=current.version,
    )

    assert [(stock.code, stock.name) for stock in saved.stocks] == [("688802", "沐曦股份")]
    assert [(stock.code, stock.name) for stock in repository.load("2026-07-11").stocks] == [
        ("688802", "沐曦股份")
    ]


def test_create_or_get_is_atomic_when_two_calls_start_together(tmp_path, monkeypatch) -> None:
    """并发创建返回一个新建和一个既有版本，二者版本均仍可读取。"""
    service = ReviewService(ReviewRepository(tmp_path))
    barrier = Barrier(2)
    original_new = ReviewDocument.new.__func__

    def synchronized_new(cls, review_date: str):
        barrier.wait(timeout=5)
        return original_new(cls, review_date)

    monkeypatch.setattr(ReviewDocument, "new", classmethod(synchronized_new))
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(service.create_or_get, "2026-07-11") for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]

    documents, created_flags = zip(*results)
    assert sorted(created_flags) == [False, True]
    assert len({document.version for document in documents}) == 1
    assert service.get_review("2026-07-11").version == documents[0].version


def test_add_stock_normalizes_code_and_name_before_deduplication(tmp_path) -> None:
    """带首尾空白的既有代码应返回幂等结果，而不是触发仓储校验失败。"""
    service = ReviewService(ReviewRepository(tmp_path))
    service.create_or_get("2026-07-11")
    service.add_stock("2026-07-11", "688802", "沐曦股份")

    result = service.add_stock("2026-07-11", " 688802 ", " 沐曦股份 ")

    assert result["already_exists"] is True
    assert [(stock.code, stock.name) for stock in result["document"].stocks] == [("688802", "沐曦股份")]


def test_concurrent_adds_keep_different_stocks(tmp_path, monkeypatch) -> None:
    """不同股票并发加入时不能因旧版本冲突而丢失任一只。"""
    repository = ReviewRepository(tmp_path)
    service = ReviewService(repository)
    service.create_or_get("2026-07-11")
    barrier = Barrier(2)
    original_save = repository.save

    def synchronized_save(document, expected_version=None):
        barrier.wait(timeout=5)
        return original_save(document, expected_version)

    monkeypatch.setattr(repository, "save", synchronized_save)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.add_stock, "2026-07-11", "688802", "沐曦股份"),
            executor.submit(service.add_stock, "2026-07-11", "688256", "寒武纪"),
        ]
        results = [future.result(timeout=10) for future in futures]

    current = service.get_review("2026-07-11")
    assert all(result["already_exists"] is False for result in results)
    assert {stock.code for stock in current.stocks} == {"688802", "688256"}
    assert current.body.count("### 688802 沐曦股份") == 1
    assert current.body.count("### 688256 寒武纪") == 1


def test_concurrent_adds_of_same_stock_are_idempotent(tmp_path, monkeypatch) -> None:
    """同股票并发加入最终只保留一次，后一结果报告 already_exists。"""
    repository = ReviewRepository(tmp_path)
    service = ReviewService(repository)
    service.create_or_get("2026-07-11")
    barrier = Barrier(2)
    original_save = repository.save

    def synchronized_save(document, expected_version=None):
        barrier.wait(timeout=5)
        return original_save(document, expected_version)

    monkeypatch.setattr(repository, "save", synchronized_save)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.add_stock, "2026-07-11", "688802", "沐曦股份")
            for _ in range(2)
        ]
        results = [future.result(timeout=10) for future in futures]

    current = service.get_review("2026-07-11")
    assert sorted(result["already_exists"] for result in results) == [False, True]
    assert [stock.code for stock in current.stocks] == ["688802"]
    assert current.body.count("### 688802 沐曦股份") == 1
