"""从多种文件格式中提取文本，供导入使用。"""
from __future__ import annotations

import base64
import io
import mimetypes
from pathlib import Path

from fastapi import HTTPException, UploadFile

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB


def _is_text_mime(mime: str | None) -> bool:
    if not mime:
        return False
    return mime.startswith("text/") or mime in {
        "application/json",
        "application/javascript",
        "application/xml",
        "application/xhtml+xml",
    }


def _extract_text_plain(content: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    return "\n".join(parts)


def _extract_pdf(content: bytes) -> str:
    import fitz  # pymupdf

    doc = fitz.open(stream=content, filetype="pdf")
    parts = []
    for page in doc:
        parts.append(page.get_text())
    return "\n".join(parts)


def _extract_epub(content: bytes) -> str:
    """从 EPUB 提取纯文本（按 spine 顺序拼接）。"""
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(io.BytesIO(content), options={"ignore_ncx": True})
    parts: list[str] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        html = item.get_body_content() or b""
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        text = soup.get_text(separator="\n")
        # 折叠连续空行
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if lines:
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


def _image_to_base64(content: bytes, mime: str | None) -> str:
    mime = mime or "image/png"
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


async def extract_text_or_image(file: UploadFile) -> tuple[str, bool]:
    """从上传文件中提取内容。

    返回 (content, is_image)。
    - 文本文件：返回纯文本
    - docx/pdf：返回提取的文本
    - 图片：返回 base64 data URL，is_image=True
    """
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"文件过大（{len(content)} bytes），最大允许 {MAX_UPLOAD_SIZE} bytes")
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    mime = file.content_type or mimetypes.guess_type(filename)[0]

    # 图片
    if mime and mime.startswith("image/"):
        return _image_to_base64(content, mime), True

    # 文档格式（解析失败时降级为纯文本，避免浏览器 MIME 误判导致 500）
    import logging
    _logger = logging.getLogger(__name__)
    if suffix == ".docx" or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            return _extract_docx(content), False
        except Exception as e:
            _logger.warning("docx 解析失败，降级为纯文本: %s", e)
            return _extract_text_plain(content), False
    if suffix == ".pdf" or mime == "application/pdf":
        try:
            return _extract_pdf(content), False
        except Exception as e:
            _logger.warning("pdf 解析失败，降级为纯文本: %s", e)
            return _extract_text_plain(content), False
    if suffix == ".epub" or mime == "application/epub+zip":
        try:
            return _extract_epub(content), False
        except Exception as e:
            _logger.warning("epub 解析失败，降级为纯文本: %s", e)
            return _extract_text_plain(content), False

    # 纯文本类（包括 .txt/.md/.json/.csv/.html/.xml/.py/.js 等）
    if _is_text_mime(mime) or suffix in {
        ".txt", ".md", ".markdown", ".json", ".csv", ".html", ".htm",
        ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log",
        ".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".scss",
        ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".rb",
        ".php", ".swift", ".kt", ".sql", ".sh", ".bat", ".ps1",
    }:
        return _extract_text_plain(content), False

    # 未知类型按文本兜底尝试
    return _extract_text_plain(content), False
