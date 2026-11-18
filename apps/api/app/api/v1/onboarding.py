"""Vendor onboarding workflow pack (Phase 5.3).

A second domain on the same platform: the deterministic rules in `app.domain.onboarding` decide,
guardrails screen the submitted text, the audit chain records every step, and approvals enforce
that the person who created a case is not the person who approves it.
"""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.audit.chain import AuditEvent, append
from app.core.auth import CurrentPrincipal, Principal, require_roles
from app.core.db import tenant_tx
from app.core.errors import AppError, Conflict, NotFound
from app.domain import onboarding as rules
from app.guardrails import screen
from app.guardrails.pii import redact

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class BankDetails(BaseModel):
    routing: str = Field(default="", max_length=20)
    account_number: str = Field(default="", max_length=34)
    verified_by_callback: bool = False


class OnboardingIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    tax_id: str = Field(default="", max_length=40)
    tax_scheme: Literal["US_EIN", "IN_GSTIN", "IN_PAN", "EU_VAT"] | None = None
    documents: dict[str, str] = Field(default_factory=dict)
    bank: BankDetails = Field(default_factory=BankDetails)
    notes: str = Field(default="", max_length=2000)


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(min_length=3, max_length=1000)


def _public(row: Any) -> dict[str, Any]:
    state = dict(row["state"])
    bank = state.get("bank") or {}
    return {
        "id": str(row["id"]),
        "vendor_name": row["vendor_name"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"].isoformat(),
        "assessment": state.get("assessment"),
        "documents": state.get("documents", {}),
        "tax_id_last4": (state.get("tax_id") or "")[-4:] or None,
        "bank_last4": bank.get("last4"),  # full numbers are never returned (§B16)
        "decisions": state.get("decisions", []),
        "guardrails": state.get("guardrails"),
    }


@router.get("/cases")
async def list_cases(p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT id, vendor_name, status, state, created_by, created_at"
                        " FROM ap.onboarding_cases ORDER BY created_at DESC LIMIT 100"
                    )
                )
            )
            .mappings()
            .all()
        )
    return {"cases": [_public(r) for r in rows]}


@router.get("/cases/{case_id}")
async def get_case(case_id: UUID, p: CurrentPrincipal) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = (
            (
                await s.execute(
                    text(
                        "SELECT id, vendor_name, status, state, created_by, created_at"
                        " FROM ap.onboarding_cases WHERE id = :i"
                    ),
                    {"i": str(case_id)},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise NotFound("onboarding case not found")
    return _public(row)


@router.post("/cases")
async def create_case(body: OnboardingIn, p: CurrentPrincipal) -> dict[str, Any]:
    """Screen, assess and record a new onboarding case."""
    if not p.has_any("clerk", "purchasing", "controller", "approver", "admin", "finance"):
        raise AppError("Not permitted to onboard vendors", code="role_required", status_code=403)
    findings = screen.heuristics(f"{body.legal_name}\n{body.notes}")
    blocked = any(f.verdict == "block" for f in findings)

    async with tenant_tx(p.org_id, p.user_id) as s:
        existing = [
            r[0]
            for r in (
                await s.execute(text("SELECT vendor_name FROM ap.onboarding_cases LIMIT 500"))
            ).all()
        ]
        employee_hashes = [
            r[0]
            for r in (
                await s.execute(
                    text(
                        "SELECT value FROM ap.onboarding_cases, "
                        " jsonb_array_elements_text(COALESCE(state->'employee_bank_hashes','[]'::jsonb))"
                        " LIMIT 100"
                    )
                )
            ).all()
        ]
        assessment = rules.assess(
            legal_name=body.legal_name,
            tax_id=body.tax_id,
            tax_scheme=body.tax_scheme,
            documents=dict(body.documents),
            bank=body.bank.model_dump(),
            existing_vendor_names=existing,
            employee_bank_hashes=employee_hashes,
        )
        status = (
            "blocked"
            if blocked
            else ("auto_approved" if assessment.route is rules.Route.AUTO else "awaiting_approval")
        )
        state = {
            "tax_id": body.tax_id,
            "tax_scheme": body.tax_scheme,
            "documents": {k: bool(v) for k, v in body.documents.items()},
            "notes": redact(body.notes),
            "bank": {
                # Only the hash and last4 are stored; the full number never persists here.
                "hash": rules.account_hash(body.bank.routing, body.bank.account_number)
                if body.bank.routing and body.bank.account_number
                else None,
                "last4": body.bank.account_number[-4:] if body.bank.account_number else None,
                "verified_by_callback": body.bank.verified_by_callback,
            },
            "assessment": assessment.public(),
            "guardrails": [f.public() for f in findings],
            "decisions": [],
        }
        row = (
            (
                await s.execute(
                    text(
                        "INSERT INTO ap.onboarding_cases (org_id, vendor_name, status, state,"
                        " created_by) VALUES (:o, :n, :st, CAST(:s AS jsonb), :u)"
                        " RETURNING id, vendor_name, status, state, created_by, created_at"
                    ),
                    {
                        "o": p.org_id,
                        "n": body.legal_name,
                        "st": status,
                        "s": json.dumps(state),
                        "u": p.user_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        await screen.record(s, p.org_id, findings, surface="onboarding")
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="onboarding.created",
                actor_type="human",
                actor_id=p.user_id,
                target_type="onboarding_case",
                target_id=str(row["id"]),
                decision=status,
                output=assessment.public(),
            ),
        )
    return _public(row)


@router.post("/cases/{case_id}/decide")
async def decide(
    case_id: UUID,
    body: Decision,
    p: Principal = require_roles("approver", "controller", "admin"),
) -> dict[str, Any]:
    """Approve or reject. The creator may never decide their own case (segregation of duties)."""
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = (
            (
                await s.execute(
                    text(
                        "SELECT id, vendor_name, status, state, created_by, created_at"
                        " FROM ap.onboarding_cases WHERE id = :i FOR UPDATE"
                    ),
                    {"i": str(case_id)},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise NotFound("onboarding case not found")
        if row["status"] not in ("awaiting_approval", "blocked"):
            raise Conflict(
                f"This case is {row['status']} and cannot be decided again",
                code="already_decided",
            )
        if row["created_by"] == p.user_id:
            raise AppError(
                "The person who created the case cannot approve it",
                code="sod_violation",
                status_code=403,
            )
        assessment = (row["state"].get("assessment") or {}).get("required_role")
        if assessment == "controller" and not p.has_any("controller", "admin"):
            raise AppError("This case needs a controller", code="role_required", status_code=403)
        state = dict(row["state"])
        state["decisions"] = [
            *state.get("decisions", []),
            {"decision": body.decision, "by": p.user_id, "comment": body.comment},
        ]
        status = "approved" if body.decision == "approve" else "rejected"
        await s.execute(
            text(
                "UPDATE ap.onboarding_cases SET status = :st, state = CAST(:s AS jsonb)"
                " WHERE id = :i"
            ),
            {"st": status, "s": json.dumps(state), "i": str(case_id)},
        )
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="onboarding.decided",
                actor_type="human",
                actor_id=p.user_id,
                target_type="onboarding_case",
                target_id=str(case_id),
                decision=status,
                details={"comment": body.comment},
            ),
        )
    return {"id": str(case_id), "status": status, "decided_by": p.user_id}
