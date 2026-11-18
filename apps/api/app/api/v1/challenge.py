"""Public red-team challenge (§B13.5).

A visitor tries to make the agent do something it should not. The attempt runs against a
sandbox tenant with **no write tools**: it is screened by the same guardrails the workflow uses
and, when it gets past them, answered by a read-only copilot over synthetic data.

Every attempt is stored with its per-check verdicts. An attempt that gets through is filed to
the feedback inbox so it can become a regression case.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.errors import AppError
from app.core.limits import verify_turnstile
from app.core.logging import get_logger
from app.core.store import Window, get_store
from app.guardrails import screen
from app.guardrails.pii import redact
from app.llm.router import CallContext, get_router

log = get_logger("challenge")
router = APIRouter(prefix="/challenge", tags=["challenge"])

SANDBOX_ORG = "demo"
CATEGORIES = (
    "direct_injection",
    "indirect_injection",
    "hidden_text",
    "exfiltration",
    "tool_misuse",
    "memory_poisoning",
    "jailbreak",
)


class Attempt(BaseModel):
    category: str = Field(max_length=40)
    attempt: str = Field(min_length=5, max_length=2000)
    turnstile_token: str | None = Field(default=None, max_length=4000)


def _visitor_hash(request: Request) -> str:
    # Only Vercel-provided headers are trusted; a client-set X-Forwarded-For cannot dodge limits.
    ip = request.headers.get("x-vercel-forwarded-for") or (
        request.client.host if request.client else "unknown"
    )
    return hashlib.sha256(f"challenge:{ip}".encode()).hexdigest()[:32]


@router.get("/categories")
async def categories() -> dict[str, Any]:
    s = get_settings()
    return {
        "enabled": s.challenge_enabled,
        "categories": list(CATEGORIES),
        "daily_attempts": s.challenge_daily_attempts,
        "rules": (
            "The sandbox has read-only tools over synthetic data. Attempts are logged. "
            "Do not submit real personal or financial data."
        ),
    }


@router.get("/scoreboard")
async def scoreboard() -> dict[str, Any]:
    """Per-category results, computed from stored attempts only."""
    async with tenant_tx(SANDBOX_ORG, "challenge") as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT category, count(*) AS attempts,"
                        " count(*) FILTER (WHERE blocked) AS blocked"
                        " FROM ai.challenge_attempts GROUP BY category ORDER BY category"
                    )
                )
            )
            .mappings()
            .all()
        )
    total = sum(r["attempts"] for r in rows)
    blocked = sum(r["blocked"] for r in rows)
    return {
        "total_attempts": total,
        "blocked": blocked,
        "block_rate": round(blocked / total, 4) if total else None,
        "by_category": [
            {
                "category": r["category"],
                "attempts": r["attempts"],
                "blocked": r["blocked"],
                "block_rate": round(r["blocked"] / r["attempts"], 4) if r["attempts"] else None,
            }
            for r in rows
        ],
        "measured_from": "stored attempts",
    }


@router.post("/attempt")
async def attempt(body: Attempt, request: Request) -> dict[str, Any]:
    s = get_settings()
    if not s.challenge_enabled:
        raise AppError("The challenge is currently disabled", code="challenge_disabled")
    if body.category not in CATEGORIES:
        raise AppError(f"category must be one of {', '.join(CATEGORIES)}", code="bad_category")
    visitor = _visitor_hash(request)
    if s.challenge_daily_attempts:
        allowed = await get_store().take(
            [Window(f"challenge:{visitor}", s.challenge_daily_attempts, 86400)]
        )
        if not allowed.allowed:
            raise AppError(
                "Daily challenge attempts used up. Try again tomorrow.",
                code="rate_limited",
                status_code=429,
                headers={"Retry-After": str(allowed.retry_after_s or 3600)},
            )
    await verify_turnstile(body.turnstile_token, request)

    text_in = redact(body.attempt)
    findings = screen.heuristics(text_in)
    router_ = get_router()
    ctx = CallContext(org_id=SANDBOX_ORG, user_id=f"challenge:{visitor}")

    async def classify(chunk: str) -> Any:
        return await router_.run("injection_check", {"text": chunk}, ctx)

    if not any(f.verdict == "block" for f in findings):
        findings.extend(await screen.classify(text_in, classify))
    blocked = any(f.verdict == "block" for f in findings)

    answer = None
    if not blocked:
        # Got past the guardrails: answer with the read-only copilot so the visitor sees exactly
        # what the attack would have achieved, then file it as a miss.
        from app.agents.copilot.agent import run_copilot
        from app.core.auth import Principal

        sandbox = Principal(f"challenge:{visitor}", SANDBOX_ORG, frozenset({"guest"}))
        result = await run_copilot(sandbox, text_in, ctx)
        answer = result["answer"]
        out_findings = screen.validate_output(
            answer, known_ids={str(sv["id"]) for sv in result.get("sources", [])}
        )
        findings.extend(out_findings)
        blocked = any(f.verdict == "block" for f in out_findings)

    verdicts = [f.public() for f in findings]
    async with tenant_tx(SANDBOX_ORG, f"challenge:{visitor}") as sess:
        await sess.execute(
            text(
                "INSERT INTO ai.challenge_attempts (org_id, category, attempt, blocked, verdicts,"
                " visitor_hash) VALUES (:o, :c, :a, :b, CAST(:v AS jsonb), :h)"
            ),
            {
                "o": SANDBOX_ORG,
                "c": body.category,
                "a": text_in[:2000],
                "b": blocked,
                "v": json.dumps(verdicts),
                "h": visitor,
            },
        )
        await screen.record(sess, SANDBOX_ORG, findings, surface="challenge")
        if not blocked:
            # A miss becomes a regression case through the normal triage queue (§B13).
            digest = hashlib.sha256(text_in.encode()).hexdigest()[:32]
            await sess.execute(
                text(
                    "INSERT INTO ai.feedback_events (org_id, event_id, source, payload,"
                    " payload_hash) VALUES (:o, :e, 'challenge', CAST(:p AS jsonb), :h)"
                    " ON CONFLICT (org_id, event_id) DO NOTHING"
                ),
                {
                    "o": SANDBOX_ORG,
                    "e": f"challenge:{digest}",
                    "p": json.dumps(
                        {
                            "event_id": f"challenge:{digest}",
                            "category": body.category,
                            "attempt": text_in[:2000],
                            "answer": answer,
                        }
                    ),
                    "h": digest,
                },
            )
    log.info("challenge.attempt", category=body.category, blocked=blocked)
    return {
        "blocked": blocked,
        "category": body.category,
        "verdicts": verdicts,
        "answer": None if blocked else answer,
        "message": (
            "Blocked before the model saw it."
            if blocked
            else "This one got through. It has been filed as a regression case."
        ),
    }
