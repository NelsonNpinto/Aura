"""Knowledge ingestion, hybrid retrieval with RRF + rerank, and cited answers (task 0.6)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text

from app.core.auth import Principal
from app.core.db import tenant_tx
from app.core.errors import AppError
from app.llm.router import CallContext, ModelRouter
from app.rag.chunking import chunk_pages
from app.rag.citations import NOT_IN_DATA, check_citations
from app.rag.embeddings import Embedder, Reranker
from app.rag.extract import extract
from app.services.blob import BlobStore

RRF_K = 60
_SELECT = (
    "SELECT c.id, c.document_id, d.filename, c.heading, c.text, c.page, d.doc_type"
    " FROM kb.chunks c JOIN kb.documents d ON d.id = c.document_id WHERE "
)
CANDIDATES = 20
TOP_K = 5


@dataclass
class IngestResult:
    document_id: str
    duplicate: bool
    chunk_count: int


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    filename: str
    heading: str
    text: str
    page: int | None
    doc_type: str
    rrf: float
    vector_rank: int | None
    keyword_rank: int | None
    rerank_score: float | None = None


@dataclass
class Answer:
    text: str
    sources: list[Hit]
    citations: dict[str, Any]
    llm: dict[str, Any] | None = field(default=None)


async def ingest(
    p: Principal,
    *,
    filename: str,
    data: bytes,
    doc_type: str,
    version: str | None,
    effective_from: date | None,
    effective_to: date | None,
    max_pages: int,
    blob: BlobStore,
    embedder: Embedder,
    synthetic: bool = False,
) -> IngestResult:
    sha = hashlib.sha256(data).hexdigest()
    async with tenant_tx(p.org_id, p.user_id) as s:
        existing = (
            await s.execute(
                text("SELECT id, chunk_count FROM kb.documents WHERE org_id=:o AND sha256=:h"),
                {"o": p.org_id, "h": sha},
            )
        ).first()
    if existing:
        return IngestResult(str(existing.id), True, existing.chunk_count)

    doc = await extract(data, filename, max_pages=max_pages)
    chunks = chunk_pages(doc.pages)
    if not chunks:
        raise AppError(
            "Document contains no extractable text", code="empty_document", status_code=422
        )
    vectors = await embedder.embed([f"{c.heading}\n{c.text}" for c in chunks])
    doc_id = uuid.uuid4()
    key = f"kb/{p.org_id}/{sha}"
    await blob.put(key, data, doc.mime)
    async with tenant_tx(p.org_id, p.user_id) as s:
        await s.execute(
            text(
                "INSERT INTO kb.documents (id, org_id, filename, mime, size_bytes, sha256, blob_key, doc_type,"
                " version, effective_from, effective_to, pages, chunk_count, synthetic, created_by)"
                " VALUES (:id,:o,:f,:m,:sz,:h,:k,:dt,:v,:ef,:et,:pg,:cc,:syn,:by)"
                " ON CONFLICT (org_id, sha256) DO NOTHING"
            ),
            {
                "id": doc_id,
                "o": p.org_id,
                "f": filename[:255],
                "m": doc.mime,
                "sz": len(data),
                "h": sha,
                "k": key,
                "dt": doc_type,
                "v": version,
                "ef": effective_from,
                "et": effective_to,
                "pg": len(doc.pages),
                "cc": len(chunks),
                "syn": synthetic,
                "by": p.user_id,
            },
        )
        await s.execute(
            text(
                "INSERT INTO kb.chunks (org_id, document_id, ord, heading, text, page, token_estimate,"
                " embedding, metadata) VALUES (:o,:d,:ord,:h,:t,:pg,:te,CAST(:e AS vector),CAST(:md AS jsonb))"
            ),
            [
                {
                    "o": p.org_id,
                    "d": doc_id,
                    "ord": c.ord,
                    "h": c.heading,
                    "t": c.text,
                    "pg": c.page,
                    "te": c.token_estimate,
                    "e": json.dumps(v),
                    "md": json.dumps({"doc_type": doc_type, "version": version}),
                }
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )
    return IngestResult(str(doc_id), False, len(chunks))


def rrf_fuse(vector_ids: list[str], keyword_ids: list[str], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in (vector_ids, keyword_ids):
        for rank, cid in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return scores


async def search(
    p: Principal,
    query: str,
    *,
    embedder: Embedder,
    reranker: Reranker | None,
    doc_types: list[str] | None = None,
    as_of: date | None = None,
    top_k: int = TOP_K,
) -> list[Hit]:
    qvec = (await embedder.embed([query], query=True))[0]
    filters = "c.org_id = :o"
    params: dict[str, Any] = {"o": p.org_id, "q": query, "e": json.dumps(qvec), "n": CANDIDATES}
    if doc_types:
        filters += " AND d.doc_type = ANY(:dts)"
        params["dts"] = doc_types
    if as_of:
        filters += (
            " AND (d.effective_from IS NULL OR d.effective_from <= :asof)"
            " AND (d.effective_to IS NULL OR d.effective_to >= :asof)"
        )
        params["asof"] = as_of
    base = _SELECT + filters  # constant fragments only; all values are bound parameters
    async with tenant_tx(p.org_id, p.user_id) as s:
        vec_rows = (
            await s.execute(
                text(base + " ORDER BY c.embedding <=> CAST(:e AS vector) LIMIT :n"), params
            )
        ).all()
        kw_rows = (
            await s.execute(
                text(
                    base + " AND c.tsv @@ websearch_to_tsquery('english', :q)"
                    " ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', :q)) DESC LIMIT :n"
                ),
                params,
            )
        ).all()
    rows = {str(r.id): r for r in [*vec_rows, *kw_rows]}
    vec_ids = [str(r.id) for r in vec_rows]
    kw_ids = [str(r.id) for r in kw_rows]
    fused = rrf_fuse(vec_ids, kw_ids)
    ranked = sorted(fused, key=lambda cid: -fused[cid])[:CANDIDATES]
    hits = [
        Hit(
            cid,
            str(rows[cid].document_id),
            rows[cid].filename,
            rows[cid].heading,
            rows[cid].text,
            rows[cid].page,
            rows[cid].doc_type,
            fused[cid],
            vec_ids.index(cid) + 1 if cid in vec_ids else None,
            kw_ids.index(cid) + 1 if cid in kw_ids else None,
        )
        for cid in ranked
    ]
    if reranker and hits:
        scores = await reranker.rerank(query, [f"{h.heading}\n{h.text}" for h in hits])
        for h, sc in zip(hits, scores, strict=True):
            h.rerank_score = sc
        hits.sort(key=lambda h: -(h.rerank_score or 0.0))
    return hits[:top_k]


def format_sources(hits: list[Hit]) -> str:
    parts = []
    for i, h in enumerate(hits, start=1):
        loc = (
            f"{h.filename}"
            + (f", p.{h.page}" if h.page else "")
            + (f" — {h.heading}" if h.heading else "")
        )
        parts.append(f"[{i}] ({loc})\n{h.text}")
    return "\n\n".join(parts)


async def answer(
    p: Principal,
    question: str,
    *,
    router: ModelRouter,
    ctx: CallContext,
    embedder: Embedder,
    reranker: Reranker | None,
    doc_types: list[str] | None = None,
) -> Answer:
    hits = await search(p, question, embedder=embedder, reranker=reranker, doc_types=doc_types)
    if not hits:
        return Answer(NOT_IN_DATA, [], {"used": [], "invalid": [], "uncited": False, "valid": True})
    res = await router.run(
        "rag_answer", {"question": question, "sources": format_sources(hits)}, ctx
    )
    report = check_citations(res.text, len(hits))
    return Answer(
        res.text,
        hits,
        {
            "used": report.used,
            "invalid": report.invalid,
            "uncited": report.uncited,
            "valid": report.valid,
        },
        res.public(),
    )
