"""Knowledge-graph explorer and guarded query endpoints (§B8.2).

Tenant data is read through parameterised templates. Free-form, model-generated Cypher is
confined to the synthetic demo workspace, validated, run in a READ transaction, and logged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.api.deps import call_context
from app.core.auth import CurrentPrincipal, Principal, require_roles
from app.graph import guard, queries, service
from app.graph.client import GraphUnavailable, availability, ping
from app.graph.sync import drain
from app.llm.router import get_router

router = APIRouter(prefix="/graph", tags=["graph"])


class TemplateQuery(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    params: dict[str, str | int] = Field(default_factory=dict)


class AskGraph(BaseModel):
    question: str = Field(min_length=3, max_length=300)


@router.get("/status")
async def status(p: CurrentPrincipal) -> dict[str, Any]:
    usable, reason = availability()
    return {"configured": usable, "reason": reason, "templates": queries.catalog()}


@router.get("/vendor/{vendor_id}")
async def vendor(p: CurrentPrincipal, vendor_id: str) -> dict[str, Any]:
    return await service.neighborhood(p.org_id, vendor_id)


@router.get("/patterns")
async def patterns(p: CurrentPrincipal) -> dict[str, Any]:
    return await service.org_fraud_overview(p.org_id)


@router.post("/query")
async def run_template(body: TemplateQuery, p: CurrentPrincipal) -> dict[str, Any]:
    return await service.explore_template(p.org_id, body.name, dict(body.params))


@router.post("/ask")
async def ask(body: AskGraph, request: Request, p: CurrentPrincipal) -> dict[str, Any]:
    """Text-to-Cypher: generate, validate, run read-only, drop foreign rows, log the query."""
    if not guard.free_form_allowed(p.org_id):
        raise guard.CypherRejected(
            "Generated Cypher runs only against the synthetic demo workspace",
            details={"reason": "org_not_allowed"},
        )
    labels = ", ".join(
        "Vendor, BankAccount, Employee, PurchaseOrder, Invoice, User, Decision, Evidence".split()
    )
    result = await get_router().run(
        "text2cypher",
        {"question": body.question, "schema": labels},
        call_context(request, p),
    )
    cypher = result.text.strip().removeprefix("```cypher").removeprefix("```").removesuffix("```")
    try:
        out = await service.run_generated(p.org_id, cypher)
    except GraphUnavailable as exc:
        return {
            "status": "unavailable",
            "reason": exc.details.get("reason"),
            "cypher": cypher,
            "rows": [],
            "llm": result.public(),
        }
    return {"status": "ok", **out, "llm": result.public()}


@router.post("/sync")
async def sync(
    p: Principal = require_roles("admin", "controller"),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """Drain pending projections (admin; also run by the nightly reconcile job)."""
    return await drain(limit)


@router.get("/health")
async def graph_health(p: CurrentPrincipal) -> dict[str, str]:
    return await ping()
