from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from sqlalchemy import text

from app.api.deps import call_context
from app.core.auth import CurrentPrincipal, Principal, require_roles
from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.errors import AppError
from app.core.limits import charge_run
from app.llm.router import get_router
from app.monitoring.tracing import get_tracer
from app.rag import service
from app.rag.embeddings import get_embedder, get_reranker
from app.schemas.api import AskRequest, SearchRequest
from app.services.blob import get_blob_store

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
DOC_TYPES = {
    "policy",
    "approval_matrix",
    "tax_guide",
    "contract",
    "chart_of_accounts",
    "faq",
    "general",
}


@router.post("/documents", status_code=201)
async def upload(
    file: Annotated[UploadFile, File()],
    doc_type: Annotated[str, Form(max_length=32)] = "general",
    version: Annotated[str | None, Form(max_length=32)] = None,
    effective_from: Annotated[date | None, Form()] = None,
    effective_to: Annotated[date | None, Form()] = None,
    p: Principal = require_roles("admin", "controller", "clerk"),
) -> dict[str, Any]:
    s = get_settings()
    if doc_type not in DOC_TYPES:
        raise AppError(
            f"doc_type must be one of {sorted(DOC_TYPES)}", code="invalid_doc_type", status_code=422
        )
    data = await file.read(s.kb_max_bytes + 1)
    if len(data) > s.kb_max_bytes:
        raise AppError("File too large", code="payload_too_large", status_code=413)
    if not data:
        raise AppError("Empty file", code="empty_document", status_code=422)
    async with get_tracer().span(
        p.org_id, "kb.ingest", kind="retriever", input={"filename": file.filename}
    ) as sp:
        res = await service.ingest(
            p,
            filename=file.filename or "upload",
            data=data,
            doc_type=doc_type,
            version=version,
            effective_from=effective_from,
            effective_to=effective_to,
            max_pages=s.kb_max_pages,
            blob=get_blob_store(),
            embedder=get_embedder(),
        )
        sp.set_output(asdict(res))
    return asdict(res)


@router.get("/documents")
async def documents(p: CurrentPrincipal) -> list[dict[str, Any]]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            await s.execute(
                text(
                    "SELECT id, filename, mime, size_bytes, doc_type, version, effective_from, effective_to,"
                    " pages, chunk_count, synthetic, created_at FROM kb.documents ORDER BY created_at DESC LIMIT 200"
                )
            )
        ).all()
    return [dict(r._mapping) | {"id": str(r.id)} for r in rows]


@router.post("/search")
async def search(body: SearchRequest, p: CurrentPrincipal) -> dict[str, Any]:
    async with get_tracer().span(
        p.org_id, "kb.search", kind="retriever", input=body.model_dump(mode="json")
    ) as sp:
        hits = await service.search(
            p,
            body.query,
            embedder=get_embedder(),
            reranker=get_reranker(),
            doc_types=body.doc_types,
            as_of=body.as_of,
            top_k=body.top_k,
        )
        sp.set_output([h.chunk_id for h in hits])
    return {"hits": [asdict(h) for h in hits]}


@router.post("/ask")
async def ask(body: AskRequest, request: Request, p: CurrentPrincipal) -> dict[str, Any]:
    await charge_run(p)
    async with get_tracer().span(
        p.org_id, "kb.ask", kind="chain", input={"question": body.question}
    ) as sp:
        ans = await service.answer(
            p,
            body.question,
            router=get_router(),
            ctx=call_context(request, p),
            embedder=get_embedder(),
            reranker=get_reranker(),
            doc_types=body.doc_types,
        )
        sp.set_output(ans.text, citations=ans.citations)
    return {
        "answer": ans.text,
        "sources": [{"n": i, **asdict(h)} for i, h in enumerate(ans.sources, start=1)],
        "citations": ans.citations,
        "llm": ans.llm,
        "trace_id": sp.trace_id,
    }
