"""日期 Markdown 复盘库的文件仓储与路径安全边界。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Callable, Literal
from zoneinfo import ZoneInfo

from PIL import Image, UnidentifiedImageError
import yaml


_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
_FILENAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_STOCK_CODE_PATTERN = re.compile(r"\d{6}")
_IMAGE_TYPES = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
    "GIF": "image/gif",
}
_IMAGE_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
_PROCESS_LOCKS: dict[Path, threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


class ReviewConflictError(RuntimeError):
    """表示保存请求基于过期版本。"""


class ReviewValidationError(ValueError):
    """表示输入不满足复盘文件边界。"""


class ReviewCorruptDocumentError(ReviewValidationError):
    """表示磁盘中的单篇复盘无法解析，并只暴露相对定位。"""

    def __init__(self, review_date: str, relative_path: str):
        self.review_date = review_date
        self.relative_path = relative_path
        super().__init__(
            f"复盘文件 {relative_path} 无法解析，请先备份原文件后修复 frontmatter 或 UTF-8 编码"
        )


class ReviewAttachmentReferencedError(RuntimeError):
    """表示正文仍引用待删除附件。"""


@dataclass(frozen=True)
class ReviewStock:
    code: str
    name: str


@dataclass(frozen=True)
class ReviewDocument:
    review_date: str
    title: str
    status: Literal["draft", "completed", "follow_up"]
    title_source: Literal["manual", "deepseek", "local_fallback"]
    tags: tuple[str, ...]
    stocks: tuple[ReviewStock, ...]
    body: str
    created_at: str
    updated_at: str
    version: str = ""

    @classmethod
    def new(cls, review_date: str) -> "ReviewDocument":
        _validate_review_date(review_date)
        now = _now()
        return cls(
            review_date=review_date,
            title=f"{review_date} 交易复盘",
            status="draft",
            title_source="manual",
            tags=(),
            stocks=(),
            body="",
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class AttachmentInfo:
    filename: str
    content_type: str
    size: int


@dataclass(frozen=True)
class AttachmentContent:
    filename: str
    content_type: str
    raw: bytes

    def __iter__(self):
        return iter((self.raw, self.content_type))


class ReviewRepository:
    """以 Markdown 文件作为唯一真相源的复盘仓储。"""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def load(self, review_date: str) -> ReviewDocument | None:
        path = self._document_path(review_date)
        return self._load_unlocked(path, review_date)

    def _load_unlocked(self, path: Path, review_date: str) -> ReviewDocument | None:
        """调用方可在持有日期文档锁时读取，避免重复获取非重入文件锁。"""
        if not path.is_file():
            return None
        raw = path.read_bytes()
        try:
            metadata, body = _parse_document(raw)
            document = _document_from_metadata(metadata, body)
            if document.review_date != review_date:
                raise ReviewValidationError("复盘文件日期与文件名不一致")
        except ReviewValidationError as exc:
            relative_path = path.relative_to(self.root).as_posix()
            raise ReviewCorruptDocumentError(review_date, relative_path) from exc
        return replace(document, version=_version(raw))

    def save(self, document: ReviewDocument, expected_version: str | None = None) -> ReviewDocument:
        _validate_document(document)
        path = self._document_path(document.review_date)
        with self._document_lock(path):
            current = self._load_unlocked(path, document.review_date)
            if expected_version is not None and (current is None or current.version != expected_version):
                raise ReviewConflictError("复盘已被其他保存操作更新")
            return self._persist_locked(path, document, current)

    def create_if_absent(self, document: ReviewDocument) -> tuple[ReviewDocument, bool]:
        """在单篇文档锁内执行条件创建，避免并发请求互相覆盖版本。"""
        _validate_document(document)
        path = self._document_path(document.review_date)
        with self._document_lock(path):
            current = self._load_unlocked(path, document.review_date)
            if current is not None:
                return current, False
            return self._persist_locked(path, document, None), True

    def mutate(
        self,
        review_date: str,
        mutation: Callable[[ReviewDocument | None], tuple[ReviewDocument, bool]],
    ) -> tuple[ReviewDocument, bool]:
        """在单篇文档锁内执行读改写，返回持久化文档和是否发生修改。"""
        path = self._document_path(review_date)
        with self._document_lock(path):
            current = self._load_unlocked(path, review_date)
            document, changed = mutation(current)
            _validate_document(document)
            if document.review_date != review_date:
                raise ReviewValidationError("复盘文件日期与请求日期不一致")
            if not changed:
                if current is None:
                    raise ReviewValidationError("复盘原子修改未创建文档")
                return current, False
            return self._persist_locked(path, document, current), True

    def _persist_locked(
        self,
        path: Path,
        document: ReviewDocument,
        current: ReviewDocument | None,
    ) -> ReviewDocument:
        """调用方持有文档锁时写入，保留首次创建时间并生成新版本。"""
        now = _now()
        created_at = current.created_at if current is not None else document.created_at
        persisted = replace(document, created_at=created_at, updated_at=now, version="")
        raw = _serialize_document(persisted)
        self._atomic_write(path, raw)
        return replace(persisted, version=_version(raw))

    def iter_documents(self) -> list[ReviewDocument]:
        documents, _warnings = self.scan_documents()
        return documents

    def scan_documents(self) -> tuple[list[ReviewDocument], list[ReviewCorruptDocumentError]]:
        """扫描全部 Markdown，并把单篇损坏文件作为可恢复告警返回。"""
        documents: list[ReviewDocument] = []
        warnings: list[ReviewCorruptDocumentError] = []
        for path in self.root.glob("*/*/*.md"):
            self._inside_root(path)
            review_date = path.stem
            try:
                document = self.load(review_date)
            except ReviewCorruptDocumentError as error:
                warnings.append(error)
                continue
            except ReviewValidationError:
                warnings.append(ReviewCorruptDocumentError(review_date, path.relative_to(self.root).as_posix()))
                continue
            if document is not None:
                documents.append(document)
        return (
            sorted(documents, key=lambda document: document.review_date, reverse=True),
            sorted(warnings, key=lambda warning: warning.review_date, reverse=True),
        )

    def save_attachment(self, review_date: str, upload_name: str, content_type: str, raw: bytes) -> AttachmentInfo:
        _validate_review_date(review_date)
        _validate_upload_name(upload_name)
        actual_type = _validate_image(raw, content_type)
        document_path = self._document_path(review_date)
        with self._document_lock(document_path):
            assets_path = self._assets_path(review_date)
            assets_path.mkdir(parents=True, exist_ok=True)
            filename = _next_attachment_filename(assets_path, actual_type)
            target = self._attachment_path(review_date, filename)
            self._atomic_write(target, raw)
        return AttachmentInfo(filename=filename, content_type=actual_type, size=len(raw))

    def first_attachment(self, review_date: str) -> AttachmentInfo | None:
        """只读取首个有效附件，供列表缩略图使用，避免扫描当天全部图片。"""
        document_path = self._document_path(review_date)
        with self._document_lock(document_path):
            assets_path = self._assets_path(review_date)
            if not assets_path.is_dir():
                return None
            for path in sorted(assets_path.iterdir(), key=lambda item: item.name):
                if not path.is_file():
                    continue
                self._inside_root(path)
                try:
                    content_type = _validate_image(path.read_bytes(), None)
                except ReviewValidationError:
                    continue
                return AttachmentInfo(path.name, content_type, path.stat().st_size)
            return None

    def list_attachments(self, review_date: str) -> list[AttachmentInfo]:
        document_path = self._document_path(review_date)
        with self._document_lock(document_path):
            assets_path = self._assets_path(review_date)
            if not assets_path.is_dir():
                return []
            attachments: list[AttachmentInfo] = []
            for path in assets_path.iterdir():
                if not path.is_file():
                    continue
                self._inside_root(path)
                try:
                    content_type = _validate_image(path.read_bytes(), None)
                except ReviewValidationError:
                    continue
                attachments.append(AttachmentInfo(path.name, content_type, path.stat().st_size))
            return sorted(attachments, key=lambda attachment: attachment.filename)

    def read_attachment(self, review_date: str, filename: str) -> AttachmentContent:
        document_path = self._document_path(review_date)
        with self._document_lock(document_path):
            path = self._attachment_path(review_date, filename)
            raw = path.read_bytes()
            return AttachmentContent(filename=path.name, content_type=_validate_image(raw, None), raw=raw)

    def delete_attachment(self, review_date: str, filename: str, force: bool = False) -> None:
        document_path = self._document_path(review_date)
        with self._document_lock(document_path):
            path = self._attachment_path(review_date, filename)
            if not path.is_file():
                raise FileNotFoundError(path.name)
            if not force:
                document = self._load_unlocked(document_path, review_date)
                references = (
                    f"./{review_date}.assets/{path.name}",
                    f"{review_date}.assets/{path.name}",
                )
                if document is not None and any(reference in document.body for reference in references):
                    raise ReviewAttachmentReferencedError("附件仍被复盘正文引用")
            path.unlink()

    def _document_path(self, review_date: str) -> Path:
        _validate_review_date(review_date)
        year, month, _ = review_date.split("-")
        return self._inside_root(self.root / year / month / f"{review_date}.md")

    def _assets_path(self, review_date: str) -> Path:
        document_path = self._document_path(review_date)
        return self._inside_root(document_path.parent / f"{review_date}.assets")

    def _attachment_path(self, review_date: str, filename: str) -> Path:
        return self._inside_root(self._assets_path(review_date) / _validate_filename(filename))

    def _inside_root(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ReviewValidationError("路径不在复盘库目录内") from exc
        return resolved

    @contextmanager
    def _document_lock(self, document_path: Path):
        lock_path = self._inside_root(document_path.with_name(f".{document_path.name}.lock"))
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        process_lock = _process_lock(lock_path)
        with process_lock:
            with lock_path.open("a+b") as lock_file:
                _lock_file(lock_file)
                try:
                    yield
                finally:
                    _unlock_file(lock_file)

    def _atomic_write(self, path: Path, raw: bytes) -> None:
        path = self._inside_root(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=path.parent,
                prefix=f".{path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(raw)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(Path(temporary_name), path)
        finally:
            if temporary_name is not None:
                temporary_path = Path(temporary_name)
                if temporary_path.exists():
                    temporary_path.unlink()


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _validate_review_date(review_date: str) -> None:
    if not isinstance(review_date, str) or not _DATE_PATTERN.fullmatch(review_date):
        raise ReviewValidationError("复盘日期必须为 YYYY-MM-DD")
    try:
        parsed = datetime.strptime(review_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ReviewValidationError("复盘日期不是有效日期") from exc
    if parsed.strftime("%Y-%m-%d") != review_date:
        raise ReviewValidationError("复盘日期必须为 YYYY-MM-DD")


def _validate_filename(filename: str) -> str:
    if not isinstance(filename, str) or not _FILENAME_PATTERN.fullmatch(filename):
        raise ReviewValidationError("附件名不安全")
    return filename


def _validate_upload_name(filename: str) -> None:
    """原始名称不落盘，只拒绝路径与 NUL，避免把上传解释为目录操作。"""
    if not isinstance(filename, str) or not filename or "\0" in filename:
        raise ReviewValidationError("附件名不安全")
    if "/" in filename or "\\" in filename:
        raise ReviewValidationError("附件名不安全")


def _validate_image(raw: bytes, declared_content_type: str | None) -> str:
    if not isinstance(raw, bytes) or not raw:
        raise ReviewValidationError("附件必须是非空图片")
    if len(raw) > _MAX_ATTACHMENT_BYTES:
        raise ReviewValidationError("图片不能超过 10 MiB")
    try:
        with Image.open(BytesIO(raw)) as image:
            image_format = image.format
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ReviewValidationError("附件图片签名无效") from exc
    content_type = _IMAGE_TYPES.get(image_format or "")
    if content_type is None:
        raise ReviewValidationError("图片格式不被支持")
    if declared_content_type is not None and declared_content_type.lower() != content_type:
        raise ReviewValidationError("图片内容与声明类型不一致")
    return content_type


def _next_attachment_filename(assets_path: Path, content_type: str) -> str:
    """按上海时区时间戳与锁内序号生成与原始上传名无关的磁盘名。"""
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
    extension = _IMAGE_EXTENSIONS[content_type]
    for sequence in range(1, 1000):
        filename = f"{timestamp}-{sequence:03d}{extension}"
        if not (assets_path / filename).exists():
            return _validate_filename(filename)
    raise ReviewValidationError("同一秒上传图片过多，请稍后重试")


def _validate_document(document: ReviewDocument) -> None:
    _validate_review_date(document.review_date)
    if document.status not in {"draft", "completed", "follow_up"}:
        raise ReviewValidationError("复盘状态无效")
    if document.title_source not in {"manual", "deepseek", "local_fallback"}:
        raise ReviewValidationError("标题来源无效")
    if not isinstance(document.title, str) or not isinstance(document.body, str):
        raise ReviewValidationError("标题和正文必须为文本")
    if any(not isinstance(tag, str) for tag in document.tags):
        raise ReviewValidationError("标签必须为文本")
    for stock in document.stocks:
        if not isinstance(stock, ReviewStock) or not _STOCK_CODE_PATTERN.fullmatch(stock.code):
            raise ReviewValidationError("股票代码必须为六位数字")
        if not isinstance(stock.name, str):
            raise ReviewValidationError("股票名称必须为文本")


def _serialize_document(document: ReviewDocument) -> bytes:
    metadata = {
        "date": document.review_date,
        "title": document.title,
        "status": document.status,
        "title_source": document.title_source,
        "tags": list(document.tags),
        "stocks": [{"code": stock.code, "name": stock.name} for stock in document.stocks],
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n{document.body}".encode("utf-8")


def _parse_document(raw: bytes) -> tuple[dict, str]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ReviewValidationError("复盘文件不是 UTF-8 文本") from exc
    if re.match(r"\A---\r?\n", text) is None:
        raise ReviewValidationError("复盘文件缺少 frontmatter")
    match = re.match(r"\A---\r?\n(?P<frontmatter>.*?)\r?\n---\r?\n", text, flags=re.DOTALL)
    if match is None:
        raise ReviewValidationError("复盘文件 frontmatter 未闭合")
    frontmatter = match.group("frontmatter")
    body = text[match.end() :]
    try:
        metadata = yaml.safe_load(frontmatter)
    except yaml.YAMLError as exc:
        raise ReviewValidationError("复盘文件 frontmatter YAML 无效") from exc
    if not isinstance(metadata, dict):
        raise ReviewValidationError("复盘文件 frontmatter 无效")
    return metadata, body


def _document_from_metadata(metadata: dict, body: str) -> ReviewDocument:
    try:
        stocks = tuple(
            ReviewStock(code=str(stock["code"]), name=str(stock.get("name", "")))
            for stock in metadata.get("stocks", [])
        )
        review_date = metadata.get("date", metadata.get("review_date"))
        if review_date is None:
            raise KeyError("date")
        document = ReviewDocument(
            review_date=str(review_date),
            title=str(metadata["title"]),
            status=str(metadata["status"]),
            title_source=str(metadata["title_source"]),
            tags=tuple(str(tag) for tag in metadata.get("tags", [])),
            stocks=stocks,
            body=body,
            created_at=str(metadata["created_at"]),
            updated_at=str(metadata["updated_at"]),
        )
    except (KeyError, TypeError) as exc:
        raise ReviewValidationError("复盘文件缺少必要字段") from exc
    _validate_document(document)
    return document


def _version(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _process_lock(lock_path: Path) -> threading.Lock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(lock_path, threading.Lock())


def _lock_file(lock_file) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        lock_file.write(b"\0")
        lock_file.flush()
        while True:
            try:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.05)
    else:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)


def _unlock_file(lock_file) -> None:
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
