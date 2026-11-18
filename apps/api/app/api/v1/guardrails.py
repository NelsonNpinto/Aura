"""Guardrail events and policy surface (§B11)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.auth import CurrentPrincipal
from app.core.db import tenant_tx
from app.guardrails import screen

router = APIRouter(prefix="/guardrails", tags=["guardrails"])


@router.get("/events")
async def events(
    p: CurrentPrincipal,
    surface: str | None = Query(default=None, max_length=20),
    verdict: str | None = Query(default=None, pattern="^(pass|flag|block)$"),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        'SELECT id, run_id, surface, "check", verdict, severity, details, created_at'
                        " FROM ai.guardrail_events"
                        " WHERE (:sf IS NULL OR surface = :sf) AND (:vd IS NULL OR verdict = :vd)"
                        " ORDER BY created_at DESC LIMIT :lim"
                    ),
                    {"sf": surface, "vd": verdict, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
    return {
        "events": [
            {
                **{k: v for k, v in r.items() if k not in ("id", "run_id", "created_at")},
                "id": str(r["id"]),
                "run_id": str(r["run_id"]) if r["run_id"] else None,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.get("/summary")
async def summary(
    p: CurrentPrincipal, days: int = Query(default=30, ge=1, le=180)
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        'SELECT surface, "check", verdict, count(*) AS n FROM ai.guardrail_events'
                        " WHERE created_at > now() - make_interval(days => :d)"
                        ' GROUP BY surface, "check", verdict ORDER BY n DESC'
                    ),
                    {"d": days},
                )
            )
            .mappings()
            .all()
        )
    blocks = sum(r["n"] for r in rows if r["verdict"] == "block")
    return {
        "window_days": days,
        "blocks": blocks,
        "by_check": [dict(r) for r in rows],
    }


@router.get("/policies")
async def policies(p: CurrentPrincipal) -> dict[str, Any]:
    """What the guardrails actually enforce, for the admin screen and the threat model."""
    return {
        "input": [
            {
                "check": "instruction_heuristic",
                "action": "block",
                "detail": "Instruction-like phrases addressed at an AI system.",
            },
            {
                "check": "hidden_text",
                "action": "block",
                "detail": "White, tiny or off-page text found via PDF character metadata.",
            },
            {
                "check": "invisible_characters",
                "action": "flag",
                "detail": "Zero-width and bidi control characters.",
            },
            {
                "check": "prompt_guard",
                "action": "block",
                "detail": "Llama Prompt Guard 2 over overlapping chunks.",
            },
            {
                "check": "pii",
                "action": "redact",
                "detail": "IBAN, account and card numbers, SSN/EIN, PAN/GSTIN, email, phone.",
            },
        ],
        "output": [
            {"check": "citation_valid", "action": "block"},
            {"check": "external_reference", "action": "block"},
            {"check": "bank_from_model", "action": "block"},
        ],
        "chunking": {
            "chars": screen.CHUNK_CHARS,
            "stride": screen.CHUNK_STRIDE,
            "max_chars": screen.MAX_SCREEN_CHARS,
        },
    }
