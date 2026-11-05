"""Runs, documents, approvals, exceptions and audit API (§C 1.7)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Header, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.agents.invoice_to_pay import runner
from app.agents.invoice_to_pay.events import TERMINAL, events_after
from app.audit.chain import events_for_run, verify
from app.core.auth import CurrentPrincipal, Principal
from app.core.config import datasets_root, get_settings
from app.core.db import tenant_tx
from app.core.errors import AppError, Conflict, Forbidden, NotFound, RateLimited
from app.core.limits import charge_run
from app.services import approvals as ap_svc
from app.services.blob import get_blob_store
from app.services.runs import create_document, create_run

router = APIRouter(tags=["runs"])
DEMO = {
    "a": {"title": "Clean invoice", "expect": "Auto-posts and schedules payment"},
    "b": {
        "title": "Price variance beyond tolerance",
        "expect": "Exception with explanation and drafted vendor email",
    },
    "c": {
        "title": "Vendor bank account changed",
        "expect": "Flagged, controller approval with call-back",
    },
    "d": {"title": "Hidden prompt injection", "expect": "Blocked and logged"},
    "e": {"title": "Scanned image", "expect": "Vision extraction, human review"},
}
FINAL = {"posted", "rejected", "exception", "blocked", "failed", "cancelled"}


def actor_for(p: Principal, persona: str | None) -> ap_svc.Actor:
    """Guests in the demo org act through a persona (§B16); everyone else acts as themselves."""
    if persona and p.org_id == "demo":
        pp = ap_svc.PERSONAS.get(persona)
        if not pp:
            raise AppError("Unknown persona", code="unknown_persona", status_code=422)
        return ap_svc.Actor(pp["id"], pp["roles"], pp["name"], pp["limit_minor"])
    limit = 1_000_000 if p.roles & {"approver"} and not p.roles & {"controller", "admin"} else None
    return ap_svc.Actor(p.user_id, p.roles, p.email or p.user_id, limit)


def _sse(ev: dict[str, Any]) -> bytes:
    return f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {json.dumps(ev, default=str)}\n\n".encode()


def _datasets() -> Path:
    return datasets_root()


@router.get("/personas")
async def personas() -> dict[str, Any]:
    return {
        "personas": [
            {
                "key": k,
                "id": v["id"],
                "name": v["name"],
                "roles": sorted(v["roles"]),
                "limit_minor": v["limit_minor"],
            }
            for k, v in ap_svc.PERSONAS.items()
        ]
    }


@router.get("/demo/invoices")
async def demo_invoices(p: CurrentPrincipal) -> dict[str, Any]:
    rows = [
        json.loads(line) for line in (_datasets() / "demo" / "cases.jsonl").read_text().splitlines()
    ]
    return {
        "invoices": [
            {
                "key": r["demo_key"],
                "file": r["file"]["name"],
                **DEMO[r["demo_key"]],
                "expected_route": r["expected"]["route"],
                "expected_status": r["expected"]["status"],
                "synthetic": True,
            }
            for r in rows
        ]
    }


@router.post("/documents", status_code=201)
async def upload_document(
    p: CurrentPrincipal, file: Annotated[UploadFile, File()]
) -> dict[str, Any]:
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise AppError("File too large (10 MB limit)", code="too_large", status_code=413)
    return await create_document(
        p.org_id, p.user_id, file.filename or "upload", data, guest=p.is_guest
    )


class RunRequest(BaseModel):
    document_id: str | None = Field(default=None, max_length=64)
    demo_key: str | None = Field(default=None, pattern="^[a-e]$")


async def _demo_document(p: Principal, key: str) -> str:
    rows = [
        json.loads(line) for line in (_datasets() / "demo" / "cases.jsonl").read_text().splitlines()
    ]
    c = next(r for r in rows if r["demo_key"] == key)
    data = (_datasets() / "demo" / "files" / c["file"]["name"]).read_bytes()
    doc = await create_document(
        p.org_id,
        "persona:rahul" if p.org_id == "demo" else p.user_id,
        c["file"]["name"],
        data,
        source="demo",
        synthetic=True,
        demo_key=key,
    )
    return str(doc["document_id"])


@router.post("/runs")
async def start_run(
    body: RunRequest,
    request: Request,
    p: CurrentPrincipal,
    x_aura_persona: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    if not (body.document_id or body.demo_key):
        raise AppError("document_id or demo_key required", code="invalid_request", status_code=422)
    actor = actor_for(p, x_aura_persona or ("rahul" if p.org_id == "demo" else None))
    doc_id = body.document_id or await _demo_document(p, body.demo_key or "a")
    mode = "live"
    try:
        await charge_run(p)
    except RateLimited:
        if not body.demo_key:
            raise
        mode = "replay"  # budget exhausted: deterministic fixture run, no provider calls, clearly labelled
    if get_settings().provider_mode == "fake":
        mode = "fake"
    run_id = await create_run(
        p.org_id, actor.user_id, doc_id, mode=mode, git_sha=get_settings().git_sha
    )
    country = request.headers.get("x-vercel-ip-country")

    async def gen() -> AsyncIterator[bytes]:
        yield f"event: run.created\ndata: {json.dumps({'run_id': run_id, 'mode': mode})}\n\n".encode()
        async for ev in runner.stream(
            run_id,
            p.org_id,
            actor.user_id,
            document_id=doc_id,
            country=country,
            fake=mode in ("replay", "fake"),
        ):
            yield _sse(ev)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Run-Id": run_id},
    )


@router.get("/runs")
async def list_runs(
    p: CurrentPrincipal, limit: int = 50, status: str | None = None
) -> dict[str, Any]:
    q = (
        "SELECT r.id, r.status, r.route, r.mode, r.created_at, r.finished_at, r.latency_ms, r.tokens, r.est_cost_microusd,"
        " r.started_by, r.seed, d.filename, d.demo_key, i.vendor_name, i.invoice_number, i.total_minor, i.currency, i.risk_level"
        " FROM ap.runs r JOIN ap.documents d ON d.id = r.document_id LEFT JOIN ap.invoices i ON i.run_id = r.id"
    )
    params: dict[str, Any] = {"n": min(max(limit, 1), 200)}
    if status:
        q += " WHERE r.status = :s"
        params["s"] = status
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (await s.execute(text(q + " ORDER BY r.created_at DESC LIMIT :n"), params))
            .mappings()
            .all()
        )
    return {"runs": [dict(r) for r in rows]}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        run = (
            (
                await s.execute(
                    text(
                        "SELECT r.*, d.filename, d.mime, d.demo_key, d.hidden_text_findings FROM ap.runs r JOIN ap.documents d ON d.id = r.document_id"
                        " WHERE r.id = :r"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .first()
        )
        if not run:
            raise NotFound("Run not found")
        inv = (
            (await s.execute(text("SELECT * FROM ap.invoices WHERE run_id = :r"), {"r": run_id}))
            .mappings()
            .first()
        )
        lines = []
        if inv:
            lines = [
                dict(x)
                for x in (
                    await s.execute(
                        text(
                            "SELECT * FROM ap.invoice_lines WHERE invoice_id = :i ORDER BY line_no"
                        ),
                        {"i": inv["id"]},
                    )
                )
                .mappings()
                .all()
            ]
        flags = [
            dict(x)
            for x in (
                await s.execute(
                    text(
                        "SELECT code, severity, message, evidence FROM ap.flags WHERE run_id = :r"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .all()
        ]
        approvals = [
            dict(x)
            for x in (
                await s.execute(
                    text(
                        "SELECT step, required_role, status, decision, comment, decided_by, decided_at, callback_verified, packet, packet_hash, due_at"
                        " FROM ap.approvals WHERE run_id = :r ORDER BY step"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .all()
        ]
        exc = (
            (
                await s.execute(
                    text(
                        "SELECT id, type, status, reason, explanation, drafted_email, resolution FROM ap.exceptions WHERE run_id = :r"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .first()
        )
        posting = (
            (
                await s.execute(
                    text(
                        "SELECT erp_ref, payment_ref, amount_minor, currency, created_at FROM ap.postings WHERE run_id = :r"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .first()
        )
        extraction = (
            (
                await s.execute(
                    text(
                        "SELECT path, data, confidence, evidence FROM ap.extractions WHERE run_id = :r ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"r": run_id},
                )
            )
            .mappings()
            .first()
        )
    r = dict(run)
    r.pop("thread_id", None)
    return {
        "run": r,
        "invoice": dict(inv) if inv else None,
        "lines": lines,
        "flags": flags,
        "approvals": approvals,
        "exception": dict(exc) if exc else None,
        "posting": dict(posting) if posting else None,
        "extraction": dict(extraction) if extraction else None,
    }


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    p: CurrentPrincipal,
    last_event_id: Annotated[str | None, Header()] = None,
    after: int = 0,
) -> StreamingResponse:
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

    async def gen() -> AsyncIterator[bytes]:
        seen, idle = start, 0
        while True:
            evs = await events_after(p.org_id, run_id, seen)
            for ev in evs:
                seen = ev["seq"]
                yield _sse(ev)
                if ev["type"] in TERMINAL:
                    return
            async with tenant_tx(p.org_id) as s:
                st = (
                    await s.execute(text("SELECT status FROM ap.runs WHERE id = :r"), {"r": run_id})
                ).scalar()
            if st is None:
                return
            if (st in FINAL or st == "awaiting_approval") and not evs:
                return
            idle = 0 if evs else idle + 1
            if (
                idle > 280
            ):  # ~280 s: stay under the 300 s function limit; client reconnects with Last-Event-ID
                return
            await asyncio.sleep(1)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )


class Decision(BaseModel):
    decision: str = Field(pattern="^(approve|reject|request_info)$")
    comment: str | None = Field(default=None, max_length=2000)
    callback_verified: bool = False
    packet_hash: str | None = Field(default=None, max_length=64)


@router.get("/runs/{run_id}/approval-check")
async def approval_check(
    run_id: str, p: CurrentPrincipal, x_aura_persona: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    return await ap_svc.check_actor(p.org_id, run_id, actor_for(p, x_aura_persona))


@router.post("/runs/{run_id}/resume")
async def resume(
    run_id: str,
    body: Decision,
    request: Request,
    p: CurrentPrincipal,
    x_aura_persona: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    actor = actor_for(p, x_aura_persona)
    if not actor.roles & {"approver", "controller", "admin"}:
        raise Forbidden("Only approvers and controllers can decide", code="role_required")
    async with tenant_tx(p.org_id) as s:
        mode = (
            await s.execute(text("SELECT mode FROM ap.runs WHERE id=:r"), {"r": run_id})
        ).scalar()
    out = await ap_svc.decide(
        p.org_id,
        run_id,
        actor,
        decision=body.decision,
        comment=body.comment,
        callback_verified=body.callback_verified,
        packet_hash=body.packet_hash,
    )
    resume_val = {
        k: out[k] for k in ("decision", "approver_id", "comment", "callback_verified", "step")
    }
    country = request.headers.get("x-vercel-ip-country")

    async def gen() -> AsyncIterator[bytes]:
        async for ev in runner.stream(
            run_id,
            p.org_id,
            actor.user_id,
            resume=resume_val,
            approval_token=out.get("token"),
            country=country,
            fake=mode in ("replay", "fake"),
        ):
            yield _sse(ev)

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )


@router.post("/runs/{run_id}/cancel")
async def cancel(run_id: str, p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        st = (
            await s.execute(
                text(
                    "UPDATE ap.runs SET status='cancelled', finished_at=now() WHERE id=:r"
                    " AND status IN ('queued','running','awaiting_approval','awaiting_receipt') RETURNING status"
                ),
                {"r": run_id},
            )
        ).scalar()
        if st is None:
            raise Conflict("Run is already finished", code="not_cancellable")
        await s.execute(
            text(
                "UPDATE ap.approvals SET status='superseded' WHERE run_id=:r AND status='pending'"
            ),
            {"r": run_id},
        )
    return {"run_id": run_id, "status": "cancelled"}


@router.get("/approvals")
async def list_approvals(
    p: CurrentPrincipal, x_aura_persona: Annotated[str | None, Header()] = None
) -> dict[str, Any]:
    actor = actor_for(p, x_aura_persona)
    async with tenant_tx(p.org_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT a.run_id, a.step, a.required_role, a.packet, a.packet_hash, a.due_at, a.created_at, r.started_by,"
                        " i.vendor_name, i.invoice_number, i.total_minor, i.currency, i.risk_level"
                        " FROM ap.approvals a JOIN ap.runs r ON r.id = a.run_id LEFT JOIN ap.invoices i ON i.run_id = a.run_id"
                        " WHERE a.status = 'pending' AND r.status = 'awaiting_approval' ORDER BY a.created_at"
                    )
                )
            )
            .mappings()
            .all()
        )
    rank = {"approver": 1, "controller": 2}
    have = max((rank.get(r, 0) for r in actor.roles), default=0) + (
        2 if "admin" in actor.roles else 0
    )
    out = []
    for r in rows:
        d = dict(r)
        d["role_ok"] = have >= rank[r["required_role"]]
        d["is_preparer"] = r["started_by"] == actor.user_id
        out.append(d)
    return {
        "approvals": out,
        "actor": {"id": actor.user_id, "name": actor.name, "roles": sorted(actor.roles)},
    }


@router.get("/exceptions")
async def list_exceptions(p: CurrentPrincipal, status: str = "open") -> dict[str, Any]:
    async with tenant_tx(p.org_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT e.id, e.run_id, e.type, e.status, e.reason, e.explanation, e.drafted_email, e.created_at,"
                        " i.vendor_name, i.invoice_number, i.total_minor, i.currency, r.status AS run_status"
                        " FROM ap.exceptions e JOIN ap.runs r ON r.id = e.run_id LEFT JOIN ap.invoices i ON i.run_id = e.run_id"
                        " WHERE e.status = :s ORDER BY e.created_at DESC LIMIT 200"
                    ),
                    {"s": status},
                )
            )
            .mappings()
            .all()
        )
    return {"exceptions": [dict(r) for r in rows]}


class Resolution(BaseModel):
    resolution: str = Field(pattern="^(resolved|dismissed)$")
    note: str = Field(min_length=3, max_length=2000)


@router.post("/exceptions/{exc_id}/resolve")
async def resolve_exception(
    exc_id: str,
    body: Resolution,
    p: CurrentPrincipal,
    x_aura_persona: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    from app.audit.chain import AuditEvent, append

    actor = actor_for(p, x_aura_persona)
    if not actor.roles & {"clerk", "approver", "controller", "admin"}:
        raise Forbidden("Not allowed to resolve exceptions")
    async with tenant_tx(p.org_id, actor.user_id) as s:
        run_id = (
            await s.execute(
                text(
                    "UPDATE ap.exceptions SET status=:st, resolution=:n, resolved_by=:u, resolved_at=now() WHERE id=:i AND status='open' RETURNING run_id"
                ),
                {"st": body.resolution, "n": body.note, "u": actor.user_id, "i": exc_id},
            )
        ).scalar()
        if run_id is None:
            raise Conflict("Exception is not open")
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="exception.resolved",
                actor_type="human",
                actor_id=actor.user_id,
                run_id=str(run_id),
                decision=body.resolution,
                details={"note": body.note[:500]},
            ),
        )
    return {"id": exc_id, "status": body.resolution}


@router.get("/documents/{doc_id}/file")
async def document_file(doc_id: str, p: CurrentPrincipal) -> Response:
    async with tenant_tx(p.org_id) as s:
        row = (
            (
                await s.execute(
                    text("SELECT blob_key, mime FROM ap.documents WHERE id = :i"), {"i": doc_id}
                )
            )
            .mappings()
            .first()
        )
    if not row:
        raise NotFound("Document not found")
    data = await get_blob_store().get(row["blob_key"])
    return Response(
        data,
        media_type=row["mime"],
        headers={"Cache-Control": "private, max-age=300", "Content-Disposition": "inline"},
    )


@router.get("/audit/verify")
async def audit_verify(p: CurrentPrincipal, run_id: str | None = None) -> dict[str, Any]:
    async with tenant_tx(p.org_id) as s:
        v = await verify(s, p.org_id, run_id)
    return v.public()


@router.get("/audit/runs/{run_id}")
async def audit_events(run_id: str, p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id) as s:
        evs = await events_for_run(s, p.org_id, run_id)
        v = await verify(s, p.org_id, run_id)
    return {"events": evs, "verification": v.public()}
