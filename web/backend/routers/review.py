"""复盘库 FastAPI 接口，负责 HTTP 契约与服务层错误映射。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import logging
from pathlib import Path
import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from web.backend.services.review_repository import (
    AttachmentInfo,
    ReviewAttachmentReferencedError,
    ReviewConflictError,
    ReviewDocument,
    ReviewRepository,
    ReviewStock,
    ReviewValidationError,
)
from web.backend.services.review_service import ReviewService
from web.backend.services.review_title_service import ReviewTitleService


router = APIRouter(prefix="/api/reviews", tags=["复盘库"])
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_REVIEW_ROOT = _PROJECT_ROOT / "data" / "review_library"
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_UPLOAD_CHUNK_BYTES = 1024 * 1024
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class ReviewStockPayload(BaseModel):
    """复盘写入或标题生成时使用的股票元数据。"""

    code: str
    name: str = ""


class ReviewUpdatePayload(BaseModel):
    """带乐观锁版本的完整复盘保存请求。"""

    title: str
    status: Literal["draft", "completed", "follow_up"]
    title_source: Literal["manual", "deepseek", "local_fallback"]
    tags: list[str] = Field(default_factory=list)
    stocks: list[ReviewStockPayload] = Field(default_factory=list)
    body: str
    version: str


class ReviewTitlePayload(BaseModel):
    """生成标题的未保存编辑状态，不会写入复盘文件。"""

    title: str
    body: str
    tags: list[str] = Field(default_factory=list)
    stocks: list[ReviewStockPayload] = Field(default_factory=list)


def get_review_repository() -> ReviewRepository:
    """为生产请求构造默认 Markdown 仓储；测试通过依赖覆盖注入临时目录。"""
    return ReviewRepository(_DEFAULT_REVIEW_ROOT)


def get_review_service(
    repository: Annotated[ReviewRepository, Depends(get_review_repository)],
) -> ReviewService:
    """构造只依赖仓储的复盘编排服务。"""
    return ReviewService(repository)


def get_review_title_service() -> ReviewTitleService:
    """构造显式调用时才使用的标题候选服务。"""
    return ReviewTitleService()


def _document_data(document: ReviewDocument) -> dict:
    return {
        "review_date": document.review_date,
        "title": document.title,
        "status": document.status,
        "title_source": document.title_source,
        "tags": list(document.tags),
        "stocks": [_stock_data(stock) for stock in document.stocks],
        "body": document.body,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "version": document.version,
    }


def _stock_data(stock: ReviewStock) -> dict:
    return {"code": stock.code, "name": stock.name}


def _attachment_data(attachment: AttachmentInfo) -> dict:
    return {
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size": attachment.size,
    }


def _list_item_data(document: ReviewDocument, repository: ReviewRepository) -> dict:
    attachment_urls = [
        f"/api/reviews/{document.review_date}/attachments/{attachment.filename}"
        for attachment in repository.list_attachments(document.review_date)
    ]
    return {
        "review_date": document.review_date,
        "title": document.title,
        "status": document.status,
        "tags": list(document.tags),
        "stocks": [_stock_data(stock) for stock in document.stocks],
        "updated_at": document.updated_at,
        "body_summary": _body_summary(document.body),
        "first_attachment_url": attachment_urls[0] if attachment_urls else None,
        "version": document.version,
    }


def _body_summary(body: str) -> str:
    lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")]
    return " ".join(lines)[:200]


def _title_suggestion_data(suggestion) -> dict:
    """对 provider 失败统一脱敏，避免把配置或本地路径送到客户端。"""
    provider_error = suggestion.provider_error
    if provider_error:
        logger.warning(
            "复盘标题 provider 回退：error_code=provider_unavailable exception_type=%s",
            suggestion.provider_exception_type or "UnknownError",
        )
    return {
        "title": suggestion.title,
        "source": suggestion.source,
        "provider_fallback": suggestion.provider_fallback,
        "provider_error": "标题服务暂不可用，已使用本地候选" if provider_error else None,
        "provider_error_code": "provider_unavailable" if provider_error else None,
    }


def _validate_date_range(date_from: str | None, date_to: str | None) -> None:
    """在 HTTP 边界校验日历日期，避免把非法字符串带入服务层比较。"""
    for value in (date_from, date_to):
        if value is None:
            continue
        if _DATE_PATTERN.fullmatch(value) is None:
            raise ReviewValidationError("日期筛选必须为 YYYY-MM-DD")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ReviewValidationError("日期筛选不是有效日期") from exc
        if parsed.strftime("%Y-%m-%d") != value:
            raise ReviewValidationError("日期筛选必须为 YYYY-MM-DD")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ReviewValidationError("date_from 不能晚于 date_to")


async def _read_limited_upload(file: UploadFile) -> bytes:
    """分块读取到大小上限加一字节，越界后不再消费上传流。"""
    chunks: list[bytes] = []
    total = 0
    while True:
        read_size = min(_UPLOAD_CHUNK_BYTES, _MAX_ATTACHMENT_BYTES - total + 1)
        chunk = await file.read(read_size)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_ATTACHMENT_BYTES:
            raise ReviewValidationError("图片不能超过 10 MiB")


def _raise_mapped_error(error: Exception) -> None:
    if isinstance(error, ReviewValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isinstance(error, (ReviewConflictError, ReviewAttachmentReferencedError)):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, FileNotFoundError):
        raise HTTPException(status_code=404, detail="复盘或附件不存在") from error
    raise error


@router.get("")
def list_reviews(
    repository: Annotated[ReviewRepository, Depends(get_review_repository)],
    service: Annotated[ReviewService, Depends(get_review_service)],
    query: str = "",
    status: Literal["draft", "completed", "follow_up"] | None = None,
    stock: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """返回按日期倒序的复盘检索结果和前端所需摘要。"""
    try:
        _validate_date_range(date_from, date_to)
        result = service.list_reviews(
            query=query,
            status=status,
            stock=stock,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return {
            "success": True,
            "data": {
                "items": [_list_item_data(item, repository) for item in result["items"]],
                "total": result["total"],
                "limit": result["limit"],
                "offset": result["offset"],
                "warnings": result["warnings"],
            },
        }
    except Exception as error:
        _raise_mapped_error(error)


@router.post("/{review_date}")
def create_review(
    review_date: str,
    service: Annotated[ReviewService, Depends(get_review_service)],
):
    """幂等地创建或返回指定日期的标准复盘。"""
    try:
        document, created = service.create_or_get(review_date)
        return {"success": True, "data": {**_document_data(document), "created": created}}
    except Exception as error:
        _raise_mapped_error(error)


@router.get("/{review_date}")
def get_review(
    review_date: str,
    service: Annotated[ReviewService, Depends(get_review_service)],
):
    """读取一篇既有复盘。"""
    try:
        return {"success": True, "data": _document_data(service.get_review(review_date))}
    except Exception as error:
        _raise_mapped_error(error)


@router.put("/{review_date}")
def update_review(
    review_date: str,
    payload: ReviewUpdatePayload,
    service: Annotated[ReviewService, Depends(get_review_service)],
):
    """以客户端版本令牌保存完整复盘，冲突时不覆盖服务器版本。"""
    try:
        document = service.update_review(
            review_date,
            title=payload.title,
            status=payload.status,
            title_source=payload.title_source,
            tags=payload.tags,
            stocks=[_stock_data(stock) for stock in payload.stocks],
            body=payload.body,
            expected_version=payload.version,
        )
        return {"success": True, "data": _document_data(document)}
    except Exception as error:
        _raise_mapped_error(error)


@router.post("/{review_date}/stocks")
def add_stock(
    review_date: str,
    payload: ReviewStockPayload,
    service: Annotated[ReviewService, Depends(get_review_service)],
):
    """向当天复盘幂等地加入一只重点股票；缺失时由服务层创建。"""
    try:
        result = service.add_stock(review_date, payload.code, payload.name)
        return {
            "success": True,
            "data": {
                **_document_data(result["document"]),
                "already_exists": result["already_exists"],
            },
        }
    except Exception as error:
        _raise_mapped_error(error)


@router.post("/{review_date}/generate-title")
def generate_title(
    review_date: str,
    payload: ReviewTitlePayload,
    service: Annotated[ReviewService, Depends(get_review_service)],
    title_service: Annotated[ReviewTitleService, Depends(get_review_title_service)],
):
    """根据当前未保存编辑状态生成候选标题，不修改原始文件。"""
    try:
        current = service.get_review(review_date)
        candidate = replace(
            current,
            title=payload.title,
            tags=tuple(payload.tags),
            stocks=tuple(ReviewStock(stock.code, stock.name) for stock in payload.stocks),
            body=payload.body,
        )
        suggestion = title_service.generate(candidate)
        return {"success": True, "data": _title_suggestion_data(suggestion)}
    except Exception as error:
        _raise_mapped_error(error)


@router.get("/{review_date}/attachments")
def list_attachments(
    review_date: str,
    repository: Annotated[ReviewRepository, Depends(get_review_repository)],
):
    """列出指定复盘的安全图片附件元数据。"""
    try:
        return {
            "success": True,
            "data": {"items": [_attachment_data(item) for item in repository.list_attachments(review_date)]},
        }
    except Exception as error:
        _raise_mapped_error(error)


@router.post("/{review_date}/attachments")
async def upload_attachment(
    review_date: str,
    repository: Annotated[ReviewRepository, Depends(get_review_repository)],
    file: UploadFile = File(...),
):
    """写入通过签名与 MIME 校验的图片附件并返回可移植 Markdown。"""
    try:
        attachment = repository.save_attachment(
            review_date,
            file.filename or "",
            file.content_type or "",
            await _read_limited_upload(file),
        )
        return {
            "success": True,
            "data": {
                **_attachment_data(attachment),
                "markdown": f"![](./{review_date}.assets/{attachment.filename})",
            },
        }
    except Exception as error:
        _raise_mapped_error(error)


@router.get("/{review_date}/attachments/{filename}")
def read_attachment(
    review_date: str,
    filename: str,
    repository: Annotated[ReviewRepository, Depends(get_review_repository)],
):
    """读取一张已验证附件的原始图片字节。"""
    try:
        attachment = repository.read_attachment(review_date, filename)
        return Response(content=attachment.raw, media_type=attachment.content_type)
    except Exception as error:
        _raise_mapped_error(error)


@router.delete("/{review_date}/attachments/{filename}")
def delete_attachment(
    review_date: str,
    filename: str,
    repository: Annotated[ReviewRepository, Depends(get_review_repository)],
    force: bool = False,
):
    """删除未被正文引用的附件；强制删除必须由调用方显式确认。"""
    try:
        repository.delete_attachment(review_date, filename, force=force)
        return {"success": True, "data": {"filename": filename, "deleted": True}}
    except Exception as error:
        _raise_mapped_error(error)
