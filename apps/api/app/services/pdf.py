"""PDF handling on pypdfium2 only (one small native dependency instead of pypdf + pdfminer).

- page text (digital path)
- character-level inspection for hidden text (§B11): near-white fill, tiny font, off-page,
  invisible render mode, zero-width characters
- page rendering to PNG for the vision path (§B6)

All entry points enforce page limits; callers wrap them in timeouts.
"""

from __future__ import annotations

import ctypes
import io
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import AppError

ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿", "­"}
TINY_FONT_PT = 2.0
NEAR_WHITE = 235  # every RGB channel >= this on a white page reads as invisible
INVISIBLE_RENDER_MODES = {3, 7}  # PDF Tr 3 = invisible, 7 = clip only


class PdfRejected(AppError):
    status_code = 422
    code = "pdf_rejected"


@dataclass
class HiddenSpan:
    page: int
    reason: str
    text: str

    def public(self) -> dict[str, Any]:
        return {"page": self.page, "reason": self.reason, "text": self.text[:300]}


@dataclass
class PdfText:
    pages: list[str]
    hidden: list[HiddenSpan] = field(default_factory=list)

    @property
    def has_text_layer(self) -> bool:
        return sum(len(p.strip()) for p in self.pages) >= 20

    @property
    def visible_text(self) -> str:
        """Text with hidden spans removed (what a human reader sees)."""
        out = "\n\n".join(self.pages)
        for h in self.hidden:
            out = out.replace(h.text, " ")
        return out


def _open(data: bytes, max_pages: int) -> Any:
    import pypdfium2 as pdfium

    if not data.startswith(b"%PDF-"):
        raise PdfRejected("Not a PDF (checked by magic bytes)")
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        msg = str(exc).lower()
        if "password" in msg:
            raise PdfRejected("Password-protected PDFs are not accepted") from exc
        raise PdfRejected("Corrupt or unreadable PDF") from exc
    if len(doc) > max_pages:
        n = len(doc)
        doc.close()
        raise PdfRejected(f"PDF has {n} pages; limit is {max_pages}")
    return doc


def page_count(data: bytes, max_pages: int = 50) -> int:
    doc = _open(data, max_pages)
    try:
        return len(doc)
    finally:
        doc.close()


def _flush(spans: list[HiddenSpan], page: int, reason: str | None, buf: list[str]) -> None:
    text = "".join(buf).strip()
    if reason and len(text) >= 3:
        spans.append(HiddenSpan(page, reason, text))


def extract_text(data: bytes, max_pages: int = 20) -> PdfText:
    """Page texts plus hidden-text findings from character metadata."""
    import pypdfium2.raw as raw

    doc = _open(data, max_pages)
    pages: list[str] = []
    hidden: list[HiddenSpan] = []
    try:
        for pi in range(len(doc)):
            page = doc[pi]
            tp = page.get_textpage()
            try:
                pages.append(tp.get_text_range())
                w, h = page.get_size()
                n = raw.FPDFText_CountChars(tp.raw)
                cur_reason: str | None = None
                buf: list[str] = []
                r, g, b, a = (ctypes.c_uint() for _ in range(4))
                left, right, bottom, top = (ctypes.c_double() for _ in range(4))
                for ci in range(n):
                    ch = chr(raw.FPDFText_GetUnicode(tp.raw, ci))
                    reason: str | None = None
                    if ch in ZERO_WIDTH:
                        reason = "zero_width"
                    elif not ch.isspace():
                        size = raw.FPDFText_GetFontSize(tp.raw, ci)
                        raw.FPDFText_GetFillColor(
                            tp.raw,
                            ci,
                            ctypes.byref(r),
                            ctypes.byref(g),
                            ctypes.byref(b),
                            ctypes.byref(a),
                        )
                        raw.FPDFText_GetCharBox(
                            tp.raw,
                            ci,
                            ctypes.byref(left),
                            ctypes.byref(right),
                            ctypes.byref(bottom),
                            ctypes.byref(top),
                        )
                        obj = raw.FPDFText_GetTextObject(tp.raw, ci)
                        mode = raw.FPDFTextObj_GetTextRenderMode(obj) if obj else 0
                        if mode in INVISIBLE_RENDER_MODES:
                            reason = "invisible_render_mode"
                        elif a.value == 0 or min(r.value, g.value, b.value) >= NEAR_WHITE:
                            reason = "white_text"
                        elif 0 < size < TINY_FONT_PT:
                            reason = "tiny_font"
                        elif right.value < 0 or left.value > w or top.value < 0 or bottom.value > h:
                            reason = "off_page"
                    if ch.isspace() and cur_reason:
                        buf.append(ch)
                        continue
                    if reason != cur_reason:
                        _flush(hidden, pi + 1, cur_reason, buf)
                        cur_reason, buf = reason, []
                    if reason:
                        buf.append(ch)
                _flush(hidden, pi + 1, cur_reason, buf)
            finally:
                tp.close()
                page.close()
    finally:
        doc.close()
    return PdfText(pages, hidden)


def render_pages_png(data: bytes, max_pages: int = 5, scale: float = 2.0) -> list[bytes]:
    """Render pages to PNG for vision extraction."""
    doc = _open(data, max_pages=50)
    out: list[bytes] = []
    try:
        for pi in range(min(len(doc), max_pages)):
            page = doc[pi]
            try:
                img = page.render(scale=scale).to_pil()
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="PNG", optimize=True)
                out.append(buf.getvalue())
            finally:
                page.close()
    finally:
        doc.close()
    return out


def find_zero_width(text: str) -> int:
    return sum(1 for c in text if c in ZERO_WIDTH)
