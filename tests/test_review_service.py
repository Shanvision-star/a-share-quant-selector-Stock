"""验证复盘业务服务的模板、检索和股票去重行为。"""

from web.backend.services.review_repository import ReviewRepository
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
