"""Structure-aware chunking (§B8.1): split on Markdown headings, keep tables whole,
pack paragraphs up to a size budget, remember the heading path and page."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
MAX_CHARS = 1600
MIN_CHARS = 200


@dataclass
class Chunk:
    ord: int
    heading: str
    text: str
    page: int | None

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.text) // 4)


def _blocks(text: str) -> list[tuple[str, str]]:
    """Yields (kind, block) where kind is heading|table|para."""
    out: list[tuple[str, str]] = []
    para: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if para:
            out.append(("para", "\n".join(para).strip()))
            para.clear()
        if table:
            out.append(("table", "\n".join(table)))
            table.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if _HEADING.match(stripped):
            flush()
            out.append(("heading", stripped))
        elif stripped.startswith("|"):
            if para:
                out.append(("para", "\n".join(para).strip()))
                para.clear()
            table.append(stripped)
        elif not stripped:
            flush()
        else:
            if table:
                out.append(("table", "\n".join(table)))
                table.clear()
            para.append(line.rstrip())
    flush()
    return [(k, b) for k, b in out if b]


def chunk_pages(pages: list[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    path: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_page: int | None = None

    def heading() -> str:
        return " > ".join(t for _, t in path)

    def emit() -> None:
        nonlocal buf_page
        if buf:
            chunks.append(Chunk(len(chunks), heading(), "\n\n".join(buf), buf_page))
            buf.clear()
            buf_page = None

    multi = len(pages) > 1
    for pno, page in enumerate(pages, start=1):
        for kind, block in _blocks(page):
            if kind == "heading":
                emit()
                m = _HEADING.match(block)
                assert m
                level, title = len(m.group(1)), m.group(2)
                path[:] = [(lvl, t) for lvl, t in path if lvl < level] + [(level, title)]
                continue
            pieces = [block] if kind == "table" else _split_long(block)
            for piece in pieces:
                if buf and sum(len(b) for b in buf) + len(piece) > MAX_CHARS:
                    emit()
                buf.append(piece)
                if buf_page is None:
                    buf_page = pno if multi else None
                if kind == "table":
                    emit()
        if multi and sum(len(b) for b in buf) >= MIN_CHARS:
            emit()
    emit()
    return chunks


def _split_long(block: str) -> list[str]:
    if len(block) <= MAX_CHARS:
        return [block]
    sentences = re.split(r"(?<=[.!?])\s+", block)
    out, cur = [], ""
    for s in sentences:
        while len(s) > MAX_CHARS:
            out.append(s[:MAX_CHARS])
            s = s[MAX_CHARS:]
        if len(cur) + len(s) + 1 > MAX_CHARS and cur:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out
