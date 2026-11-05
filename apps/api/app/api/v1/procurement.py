"""Procurement assignment: scoped documents, mandatory reviews and payment confirmation."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.deps import call_context
from app.audit.chain import AuditEvent, append
from app.core.auth import CurrentPrincipal, Principal
from app.core.db import system_tx, tenant_tx
from app.core.errors import Conflict, Forbidden, NotFound
from app.core.limits import charge_run
from app.domain.procurement import EvidenceDocument, compare, transition
from app.guardrails.pii import redact
from app.llm.router import get_router
from app.services.blob import get_blob_store
from app.services.payment_email import dispatch
from app.services.pdf import extract_text, render_pages_png
from app.services.runs import create_document

router = APIRouter(prefix="/procurement", tags=["procurement"])


@router.post("/cases/{case_id}/extract/{kind}")
async def extract_document(
    case_id: uuid.UUID,
    kind: Literal["po", "invoice", "receipt"],
    request: Request,
    p: CurrentPrincipal,
    file: UploadFile = File(),
    synthetic_confirmed: bool = Form(False),
) -> dict[str, Any]:
    roles, vendor = await actor(p)
    required = {
        "invoice": {"vendor", "clerk", "admin"},
        "po": {"purchasing", "clerk", "admin"},
        "receipt": {"purchasing", "receiving", "clerk", "admin"},
    }[kind]
    if not roles & required or ("vendor" in roles and not vendor):
        raise Forbidden("This document belongs to another workflow role")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, vendor)
        if row["state"]["payment"]:
            raise Conflict("Paid cases cannot accept more documents")
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise Conflict("Document exceeds 10 MB")
    if not synthetic_confirmed:
        raise Conflict("Confirm that this upload contains only synthetic demo data")
    pdf = await asyncio.to_thread(extract_text, data, 20) if data.startswith(b"%PDF-") else None
    if pdf and pdf.hidden:
        raise Conflict("Document needs manual review: hidden text detected")
    source = await create_document(
        p.org_id, p.user_id, file.filename or "document.pdf", data, guest=p.is_guest
    )
    await charge_run(p)
    if pdf and pdf.has_text_layer:
        result = await get_router().run(
            "extract_procurement",
            {"kind": kind, "document": redact(pdf.visible_text[:18000])},
            call_context(request, p),
        )
    else:
        images = await asyncio.to_thread(render_pages_png, data, 3, 1.5) if pdf else [data]
        parts: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": "Read the synthetic document images; every field will be reviewed by a person.",
            }
        ]
        for image in images:
            mime = "image/png" if image.startswith(b"\x89PNG") else "image/jpeg"
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{base64.b64encode(image).decode()}"},
                }
            )
        result = await get_router().run(
            "extract_procurement_vision",
            {"kind": kind, "document": "Synthetic page images follow."},
            call_context(request, p),
            extra_messages=[{"role": "user", "content": parts}],
        )
    draft = result.parsed.model_dump(mode="json") if result.parsed else json.loads(result.text)
    draft["source_document_id"] = source["document_id"]
    return {
        "draft": draft,
        "source_document_id": source["document_id"],
        "requires_human_confirmation": True,
        "llm": result.public(),
    }


@router.get("/cases/{case_id}/documents/{kind}/file")
async def file_for_case(
    case_id: uuid.UUID, kind: Literal["po", "invoice", "receipt"], p: CurrentPrincipal
) -> Response:
    roles, vendor = await actor(p)
    if "vendor" in roles and not vendor:
        raise Forbidden("Vendor identity required")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, vendor)
        did = row["state"]["documents"].get(kind, {}).get("source_document_id")
        doc = (
            await s.execute(
                text("SELECT blob_key,mime FROM ap.documents WHERE id::text=:d"), {"d": did}
            )
        ).first()
    if not doc:
        raise NotFound("No source file attached")
    return Response(
        await get_blob_store().get(doc.blob_key),
        media_type=doc.mime,
        headers={"Cache-Control": "private, no-store"},
    )


async def actor(p: Principal) -> tuple[frozenset[str], str | None]:
    # Re-read membership on every operation: revocation does not wait for JWT expiry.
    async with tenant_tx(p.org_id, p.user_id) as s:
        member = (
            await s.execute(
                text("SELECT role,vendor_id FROM ap.procurement_members WHERE user_id=:u"),
                {"u": p.user_id},
            )
        ).first()
    if member:
        return frozenset({member.role}), member.vendor_id
    if p.kind == "jwt":
        async with system_tx() as s:
            row = (
                await s.execute(
                    text('SELECT role FROM auth.member WHERE "userId"=:u AND "organizationId"=:o'),
                    {"u": p.user_id, "o": p.org_id},
                )
            ).first()
        if not row:
            raise Forbidden("Workspace membership required")
        return frozenset(row.role.split(",")), None
    if "vendor" in p.roles:
        raise Forbidden("Vendor access must be assigned by purchasing")
    return p.roles, None


async def case_row(
    s: Any, p: Principal, case_id: uuid.UUID, vendor: str | None, lock: bool = False
) -> Any:
    row = (
        (
            await s.execute(
                text(
                    "SELECT * FROM ap.procurement_cases WHERE id=:id FOR UPDATE"
                    if lock
                    else "SELECT * FROM ap.procurement_cases WHERE id=:id"
                ),
                {"id": case_id},
            )
        )
        .mappings()
        .first()
    )
    if not row or (vendor is not None and row["vendor_id"] != vendor):
        raise NotFound("Procurement case not found")
    return row


async def save(
    s: Any, p: Principal, case_id: uuid.UUID, state: dict[str, Any], action: str
) -> None:
    await s.execute(
        text("UPDATE ap.procurement_cases SET state=CAST(:state AS jsonb) WHERE id=:id"),
        {"id": case_id, "state": json.dumps(state)},
    )
    await append(
        s,
        p.org_id,
        AuditEvent(
            action=action,
            actor_type="human",
            actor_id=p.user_id,
            target_type="procurement_case",
            target_id=str(case_id),
            output=state,
        ),
    )


class MemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Literal["vendor", "purchasing", "receiving", "approver", "finance", "auditor"]
    vendor_id: str | None = Field(default=None, min_length=1, max_length=80)


@router.post("/members")
async def member(body: MemberRequest, p: CurrentPrincipal) -> dict[str, str]:
    roles, _ = await actor(p)
    if "admin" not in roles or p.is_guest:
        raise Forbidden("Only the workspace administrator can assign access")
    if body.role == "vendor" and not body.vendor_id:
        raise Conflict("A vendor identifier is required")
    async with system_tx() as s:
        user = (
            await s.execute(
                text('SELECT id FROM auth."user" WHERE lower(email)=lower(:e)'), {"e": body.email}
            )
        ).first()
        if not user:
            raise NotFound("Ask this person to create an AURA account first")
        if user.id == p.user_id:
            raise Forbidden("Assign other accounts; do not replace your administrator role")
        await s.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"),
            {"k": f"membership:{p.org_id}:{user.id}"},
        )
        await s.execute(
            text(
                'INSERT INTO auth.member (id,"organizationId","userId",role,"createdAt") SELECT :id,:o,:u,:r,now() WHERE NOT EXISTS (SELECT 1 FROM auth.member WHERE "organizationId"=:o AND "userId"=:u)'
            ),
            {"id": str(uuid.uuid4()), "o": p.org_id, "u": user.id, "r": body.role},
        )
        await s.execute(
            text('UPDATE auth.member SET role=:r WHERE "organizationId"=:o AND "userId"=:u'),
            {"r": body.role, "o": p.org_id, "u": user.id},
        )
        await s.execute(
            text(
                "INSERT INTO ap.procurement_members (org_id,user_id,role,vendor_id) VALUES (:o,:u,:r,:v) ON CONFLICT (org_id,user_id) DO UPDATE SET role=excluded.role,vendor_id=excluded.vendor_id"
            ),
            {
                "o": p.org_id,
                "u": user.id,
                "r": body.role,
                "v": body.vendor_id if body.role == "vendor" else None,
            },
        )
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="procurement.access_assigned",
                actor_type="human",
                actor_id=p.user_id,
                target_id=user.id,
                details={"role": body.role, "vendor_id": body.vendor_id},
            ),
        )
    return {"status": "assigned"}


class CreateRequest(BaseModel):
    vendor_id: str = Field(min_length=1, max_length=80)
    po_number: str = Field(min_length=1, max_length=80)


@router.post("/cases", status_code=201)
async def create(body: CreateRequest, p: CurrentPrincipal) -> dict[str, str]:
    roles, _ = await actor(p)
    if not roles & {"purchasing", "clerk", "admin"}:
        raise Forbidden("Purchasing access required")
    cid = uuid.uuid4()
    state = {
        "status": "collecting_documents",
        "revision": 0,
        "documents": {},
        "evidence": {},
        "approvals": [],
        "payment": None,
        "created_by": p.user_id,
    }
    async with tenant_tx(p.org_id, p.user_id) as s:
        exists = (
            await s.execute(
                text("SELECT id FROM ap.procurement_cases WHERE po_number=:n"),
                {"n": body.po_number},
            )
        ).first()
        if exists:
            raise Conflict("This PO already has a case")
        await s.execute(
            text(
                "INSERT INTO ap.procurement_cases (id,org_id,vendor_id,po_number,state) VALUES (:id,:o,:v,:n,CAST(:st AS jsonb))"
            ),
            {
                "id": cid,
                "o": p.org_id,
                "v": body.vendor_id,
                "n": body.po_number,
                "st": json.dumps(state),
            },
        )
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="procurement.created",
                actor_type="human",
                actor_id=p.user_id,
                target_id=str(cid),
            ),
        )
    return {"id": str(cid)}


@router.get("/cases")
async def cases(p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if "vendor" in roles and not vendor:
        raise Forbidden("No vendor identity assigned")
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT * FROM ap.procurement_cases WHERE (CAST(:v AS text) IS NULL OR vendor_id=:v) ORDER BY created_at DESC LIMIT 100"
                    ),
                    {"v": vendor},
                )
            )
            .mappings()
            .all()
        )
    return {"roles": sorted(roles), "vendor_id": vendor, "cases": [dict(x) for x in rows]}


@router.put("/cases/{case_id}/documents/{kind}")
async def document(
    case_id: uuid.UUID,
    kind: Literal["po", "invoice", "receipt"],
    body: EvidenceDocument,
    p: CurrentPrincipal,
) -> dict[str, Any]:
    roles, vendor = await actor(p)
    allowed = {
        "po": {"purchasing", "clerk", "admin"},
        "invoice": {"vendor", "clerk", "admin"},
        "receipt": {"receiving", "purchasing", "clerk", "admin"},
    }
    if not roles & allowed[kind] or ("vendor" in roles and not vendor):
        raise Forbidden("This role cannot supply this document")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, vendor, True)
        state: dict[str, Any] = row["state"]
        if state["payment"]:
            raise Conflict("Paid cases cannot be edited")
        if body.po_number != row["po_number"]:
            raise Conflict("Document PO number differs from this case")
        if kind == "invoice":
            # Serialize duplicate invoice checks across different POs for the same vendor.
            key = f"{p.org_id}:{row['vendor_id']}:{body.number.strip().upper()}"
            await s.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k,0))"), {"k": key}
            )
            duplicate = (
                await s.execute(
                    text(
                        "SELECT id FROM ap.procurement_cases WHERE vendor_id=:v AND id<>:id AND upper(trim(state->'documents'->'invoice'->>'number'))=:n LIMIT 1"
                    ),
                    {"v": row["vendor_id"], "id": case_id, "n": body.number.strip().upper()},
                )
            ).first()
            if duplicate:
                raise Conflict(
                    "This vendor invoice number is already attached to another PO",
                    code="duplicate_invoice",
                )
        if body.source_document_id:
            source = (
                await s.execute(
                    text("SELECT uploaded_by FROM ap.documents WHERE id::text=:d"),
                    {"d": body.source_document_id},
                )
            ).first()
            if not source or source.uploaded_by != p.user_id:
                raise Forbidden("Source must be a document uploaded by you")
        state["documents"][kind] = body.model_dump(mode="json")
        state["evidence"][kind] = {"actor": p.user_id, "at": datetime.now(UTC).isoformat()}
        state["revision"] += 1
        state["approvals"] = []
        result = compare(state["documents"])
        state["comparison"] = result
        state["status"] = (
            "awaiting_l1"
            if result["matched"]
            else "collecting_documents"
            if result["missing"]
            else "needs_correction"
        )
        await save(s, p, case_id, state, "procurement.document_confirmed")
    return state


class ReviewRequest(BaseModel):
    revision: int = Field(strict=True, ge=1)
    action: Literal["l1", "finance", "reject"]
    comment: str = Field(min_length=1, max_length=2000)


@router.post("/cases/{case_id}/review")
async def review(case_id: uuid.UUID, body: ReviewRequest, p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if vendor or "vendor" in roles:
        raise Forbidden("Vendors cannot approve")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, None, True)
        state: dict[str, Any] = row["state"]
        if state["revision"] != body.revision:
            raise Conflict("Documents changed; refresh the evidence", code="revision_changed")
        state = transition(state, body.action, p.user_id, roles, body.comment)
        await save(s, p, case_id, state, "procurement." + body.action)
    return state


class PaidRequest(BaseModel):
    revision: int = Field(strict=True, ge=1)
    reference: str = Field(min_length=1, max_length=100)
    date: date
    amount_minor: int = Field(strict=True, gt=0, le=100000000000)


@router.post("/cases/{case_id}/paid")
async def paid(case_id: uuid.UUID, body: PaidRequest, p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if vendor or not roles & {"finance", "controller"}:
        raise Forbidden("Finance access required")
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = await case_row(s, p, case_id, None, True)
        state: dict[str, Any] = row["state"]
        payment = {
            "reference": body.reference,
            "date": body.date.isoformat(),
            "amount_minor": body.amount_minor,
            "revision": body.revision,
        }
        if state["payment"]:
            if all(state["payment"].get(k) == v for k, v in payment.items()):
                return state
            raise Conflict("Payment already recorded with different details")
        if state["status"] != "approved_for_payment" or state["revision"] != body.revision:
            raise Conflict("Both current approvals are required")
        if (
            body.date > date.today()
            or body.amount_minor != state["documents"]["invoice"]["total_minor"]
        ):
            raise Conflict("Payment date or amount is invalid")
        recipients = (
            await s.execute(
                text(
                    "SELECT user_id FROM ap.procurement_members WHERE role='vendor' AND vendor_id=:v"
                ),
                {"v": row["vendor_id"]},
            )
        ).all()
        if not recipients:
            raise Conflict("Assign the vendor login before recording payment")
        payment.update(
            {
                "actor": p.user_id,
                "recorded_at": datetime.now(UTC).isoformat(),
                "simulated": True,
                "currency": state["documents"]["invoice"]["currency"],
            }
        )
        state["payment"] = payment
        state["status"] = "paid"
        state["notification"] = {"status": "pending", "event_id": f"procurement-paid:{case_id}"}
        await s.execute(
            text(
                "INSERT INTO ops.outbox (org_id,topic,payload) VALUES (:o,'procurement.payment_email',CAST(:p AS jsonb))"
            ),
            {
                "o": p.org_id,
                "p": json.dumps(
                    {
                        "case_id": str(case_id),
                        "vendor_id": row["vendor_id"],
                        "recipients": [r.user_id for r in recipients],
                        "invoice_number": state["documents"]["invoice"]["number"],
                        "po_number": row["po_number"],
                        "payment": payment,
                    }
                ),
            },
        )
        await save(s, p, case_id, state, "procurement.paid")
    try:
        state["notification"].update(await dispatch(p.org_id, case_id))
    except Exception:
        # Payment already committed. The durable outbox can be dispatched after recovery.
        state["notification"]["status"] = "pending"
    return state


@router.post("/cases/{case_id}/notification/retry")
async def retry_notification(case_id: uuid.UUID, p: CurrentPrincipal) -> dict[str, Any]:
    roles, vendor = await actor(p)
    if vendor or not roles & {"finance", "controller", "admin"}:
        raise Forbidden("Finance access required")
    async with tenant_tx(p.org_id, p.user_id) as s:
        await case_row(s, p, case_id, None)
    return await dispatch(p.org_id, case_id)
