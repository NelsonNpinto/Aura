"""Safe text extraction for knowledge documents: magic-byte typing, size/page limits, timeouts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.core.errors import AppError


class UnsupportedDocument(AppError):
    status_code = 415
    code = "unsupported_document"


@dataclass
class ExtractedDoc:
    mime: str
    pages: list[str]  # one entry per page (text files: one page)


def sniff_mime(data: bytes, filename: str) -> str:
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data[:4] in (b"PK\x03\x04", b"\x1f\x8b\x08\x00") or data[:2] == b"MZ":
        raise UnsupportedDocument("Archives and executables are not accepted")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UnsupportedDocument("Only PDF, Markdown and plain-text files are accepted") from exc
    return "text/markdown" if filename.lower().endswith((".md", ".markdown")) else "text/plain"


def _pdf_pages(data: bytes, max_pages: int) -> list[str]:
    from app.services.pdf import PdfRejected, extract_text

    try:
        return extract_text(data, max_pages=max_pages).pages
    except PdfRejected as exc:
        raise UnsupportedDocument(exc.message) from exc


async def extract(
    data: bytes, filename: str, *, max_pages: int, timeout_s: float = 20
) -> ExtractedDoc:
    mime = sniff_mime(data, filename)
    if mime == "application/pdf":
        try:
            pages = await asyncio.wait_for(
                asyncio.to_thread(_pdf_pages, data, max_pages), timeout_s
            )
        except TimeoutError as exc:
            raise UnsupportedDocument("PDF parsing timed out") from exc
        if not any(p.strip() for p in pages):
            raise UnsupportedDocument(
                "PDF has no text layer. Scanned documents go through the invoice vision path, "
                "not the knowledge base."
            )
        return ExtractedDoc(mime, pages)
    return ExtractedDoc(mime, [data.decode("utf-8")])
