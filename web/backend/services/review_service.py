"""日期 Markdown 复盘的模板、检索与股票编排服务。"""

from __future__ import annotations

from dataclasses import replace
import re

from .review_repository import (
    ReviewDocument,
    ReviewRepository,
    ReviewStock,
    ReviewValidationError,
)


class ReviewService:
    """在不绕过 Markdown 仓储的前提下编排复盘业务规则。"""

    def __init__(self, repository: ReviewRepository):
        self.repository = repository

    def create_or_get(self, review_date: str) -> tuple[ReviewDocument, bool]:
        """取得当日复盘；不存在时按标准模板创建。"""
        document = ReviewDocument.new(review_date)
        document = replace(document, body=_standard_template(document.title))
        return self.repository.create_if_absent(document)

    def get_review(self, review_date: str) -> ReviewDocument:
        """读取既有复盘，缺失时明确返回文件不存在错误。"""
        document = self.repository.load(review_date)
        if document is None:
            raise FileNotFoundError(f"未找到 {review_date} 的复盘")
        return document

    def list_reviews(
        self,
        *,
        query: str = "",
        status: str | None = None,
        stock: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """按关键词、状态、股票和日期返回倒序分页的复盘列表。"""
        normalized_query = _normalize(query)
        normalized_stock = _normalize(stock)
        documents = self.repository.iter_documents()
        matched = [
            document
            for document in documents
            if _matches(
                document,
                normalized_query,
                status,
                normalized_stock,
                date_from,
                date_to,
            )
        ]
        safe_limit = max(0, int(limit))
        safe_offset = max(0, int(offset))
        return {
            "items": matched[safe_offset : safe_offset + safe_limit],
            "total": len(matched),
            "limit": safe_limit,
            "offset": safe_offset,
        }

    def update_review(
        self,
        review_date: str,
        *,
        title: str,
        status: str,
        title_source: str,
        tags: list[str],
        stocks: list[dict],
        body: str,
        expected_version: str,
    ) -> ReviewDocument:
        """用当前版本条件保存标题、元数据和正文。"""
        current = self.get_review(review_date)
        clean_title = _compact(title)
        if not clean_title:
            raise ReviewValidationError("标题不能为空")

        updated = replace(
            current,
            title=clean_title,
            status=status,
            title_source=title_source,
            tags=tuple(str(tag) for tag in tags),
            stocks=_stocks_from_mappings(stocks),
            body=_body_with_title(clean_title, body),
        )
        return self.repository.save(updated, expected_version=expected_version)

    def add_stock(self, review_date: str, code: str, name: str) -> dict:
        """原子确保当天复盘存在，再按股票代码幂等地追加重点股票。"""
        clean_code = str(code).strip()
        clean_name = str(name).strip()
        stock = ReviewStock(code=clean_code, name=clean_name)

        def append_stock(current: ReviewDocument | None) -> tuple[ReviewDocument, bool]:
            if current is None:
                current = ReviewDocument.new(review_date)
                current = replace(current, body=_standard_template(current.title))
            if any(item.code == clean_code for item in current.stocks):
                return current, False
            return (
                replace(
                    current,
                    stocks=(*current.stocks, stock),
                    body=_append_stock_section(current.body, stock),
                ),
                True,
            )

        document, added = self.repository.mutate(review_date, append_stock)
        return {"document": document, "already_exists": not added}


def _standard_template(title: str) -> str:
    return (
        f"# {title}\n\n"
        "## 市场环境\n\n"
        "## 今日计划与实际执行\n\n"
        "## 重点股票\n\n"
        "## 错误与交易纪律\n\n"
        "## 明日跟踪清单\n"
    )


def _stock_from_mapping(stock: dict) -> ReviewStock:
    if not isinstance(stock, dict):
        raise ReviewValidationError("股票必须为对象")
    return ReviewStock(code=str(stock.get("code") or "").strip(), name=str(stock.get("name") or ""))


def _stocks_from_mappings(stocks: list[dict]) -> tuple[ReviewStock, ...]:
    """规范化股票代码并保留首次出现的条目，避免写入重复 frontmatter。"""
    result: list[ReviewStock] = []
    seen_codes: set[str] = set()
    for mapping in stocks:
        stock = _stock_from_mapping(mapping)
        if stock.code in seen_codes:
            continue
        seen_codes.add(stock.code)
        result.append(stock)
    return tuple(result)


def _body_with_title(title: str, body: str) -> str:
    content = str(body).lstrip()
    content = re.sub(r"^#\s+[^\n]*(?:\n+)?", "", content, count=1)
    return f"# {title}\n\n{content}".rstrip() + "\n"


def _append_stock_section(body: str, stock: ReviewStock) -> str:
    section = (
        f"### {stock.code} {stock.name}\n\n"
        "#### 观察逻辑\n\n"
        "#### 走势与截图\n\n"
        "#### 当前结论\n\n"
        "#### 下一步动作\n"
    )
    marker = re.search(r"(?m)^## 重点股票\s*$", body)
    if marker is None:
        return body.rstrip() + f"\n\n## 重点股票\n\n{section}"
    return body[: marker.end()] + f"\n\n{section}" + body[marker.end() :]


def _matches(
    document: ReviewDocument,
    query: str,
    status: str | None,
    stock: str,
    date_from: str | None,
    date_to: str | None,
) -> bool:
    if status is not None and document.status != status:
        return False
    if date_from is not None and document.review_date < date_from:
        return False
    if date_to is not None and document.review_date > date_to:
        return False
    stock_text = " ".join(f"{item.code} {item.name}" for item in document.stocks)
    if stock and stock not in _normalize(stock_text):
        return False
    searchable = " ".join((document.title, " ".join(document.tags), stock_text, document.body))
    return not query or query in _normalize(searchable)


def _normalize(value: str) -> str:
    return _compact(str(value)).casefold()


def _compact(value: str) -> str:
    return " ".join(value.split())
