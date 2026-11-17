"""Observability dashboards (§B14): cost, latency, routing outcomes, drift, guardrails.

Everything is computed from stored rows (`ai.llm_calls`, `ap.runs`, `ai.guardrail_events`,
`ops.drift_reports`). Where there is no data the value is null and the UI shows "not measured" —
there are no estimated or filled-in numbers here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.auth import CurrentPrincipal, Principal, require_roles
from app.core.db import tenant_tx
from app.monitoring import drift as drift_mod

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/costs")
async def costs(p: CurrentPrincipal, days: int = Query(default=14, ge=1, le=90)) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        by_day = (
            (
                await s.execute(
                    text(
                        "SELECT date_trunc('day', created_at)::date AS day,"
                        " count(*) AS calls, sum(tokens_in) AS tokens_in,"
                        " sum(tokens_out) AS tokens_out, sum(est_cost_microusd) AS cost_microusd,"
                        " count(*) FILTER (WHERE cache_hit) AS cache_hits,"
                        " count(*) FILTER (WHERE fallback_reason IS NOT NULL) AS fallbacks"
                        " FROM ai.llm_calls"
                        " WHERE created_at > now() - make_interval(days => :d)"
                        " GROUP BY 1 ORDER BY 1"
                    ),
                    {"d": days},
                )
            )
            .mappings()
            .all()
        )
        by_task = (
            (
                await s.execute(
                    text(
                        "SELECT task, model, count(*) AS calls,"
                        " sum(est_cost_microusd) AS cost_microusd,"
                        " percentile_disc(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,"
                        " percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms"
                        " FROM ai.llm_calls"
                        " WHERE created_at > now() - make_interval(days => :d)"
                        " GROUP BY task, model ORDER BY sum(est_cost_microusd) DESC NULLS LAST"
                        " LIMIT 50"
                    ),
                    {"d": days},
                )
            )
            .mappings()
            .all()
        )
        per_invoice = (
            await s.execute(
                text(
                    "SELECT avg(est_cost_microusd)::bigint AS avg_cost_microusd FROM ap.runs"
                    " WHERE finished_at > now() - make_interval(days => :d)"
                ),
                {"d": days},
            )
        ).scalar()
    return {
        "window_days": days,
        "by_day": [{**dict(r), "day": r["day"].isoformat()} for r in by_day],
        "by_task": [dict(r) for r in by_task],
        "avg_cost_microusd_per_run": int(per_invoice) if per_invoice is not None else None,
        "source": "ai.llm_calls, ap.runs",
    }


@router.get("/runs")
async def run_metrics(
    p: CurrentPrincipal, days: int = Query(default=14, ge=1, le=90)
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT status, route, count(*) AS n,"
                        " percentile_disc(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50_ms,"
                        " percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_ms"
                        " FROM ap.runs"
                        " WHERE created_at > now() - make_interval(days => :d)"
                        " GROUP BY status, route"
                    ),
                    {"d": days},
                )
            )
            .mappings()
            .all()
        )
        overrides = (
            (
                await s.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE kind = 'decision_override') AS decisions,"
                        " count(*) FILTER (WHERE kind = 'gl_override') AS gl,"
                        " count(*) FILTER (WHERE kind = 'field_correction') AS fields"
                        " FROM ap.feedback"
                        " WHERE created_at > now() - make_interval(days => :d)"
                    ),
                    {"d": days},
                )
            )
            .mappings()
            .one()
        )
    total = sum(r["n"] for r in rows) or 0
    auto = sum(r["n"] for r in rows if r["route"] == "auto")
    hitl = sum(r["n"] for r in rows if r["route"] in ("approval", "exception"))
    return {
        "window_days": days,
        "runs": total,
        "stp_rate": round(auto / total, 4) if total else None,
        "hitl_rate": round(hitl / total, 4) if total else None,
        "by_status": [dict(r) for r in rows],
        "human_overrides": dict(overrides),
        "source": "ap.runs, ap.feedback",
    }


@router.get("/drift")
async def drift_reports(
    p: CurrentPrincipal, limit: int = Query(default=14, ge=1, le=90)
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT id, window_start, window_end, metrics, breaches, created_at"
                        " FROM ops.drift_reports ORDER BY created_at DESC LIMIT :lim"
                    ),
                    {"lim": limit},
                )
            )
            .mappings()
            .all()
        )
    return {
        "reports": [
            {
                "id": str(r["id"]),
                "window_start": r["window_start"].isoformat(),
                "window_end": r["window_end"].isoformat(),
                "metrics": r["metrics"],
                "breaches": r["breaches"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/drift/run")
async def run_drift(p: Principal = require_roles("admin", "controller")) -> dict[str, Any]:
    """Compute a drift report now (the nightly job calls the same function)."""
    return await drift_mod.compute_and_store(p.org_id)


@router.get("/hallucination")
async def hallucination(
    p: CurrentPrincipal, days: int = Query(default=30, ge=1, le=180)
) -> dict[str, Any]:
    """Copilot grounding: citation validity over stored answers (§B14)."""
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = (
            (
                await s.execute(
                    text(
                        "SELECT count(*) AS answers,"
                        " count(*) FILTER (WHERE jsonb_array_length(citations) > 0) AS with_citations"
                        " FROM ai.copilot_messages"
                        " WHERE role = 'assistant'"
                        "   AND created_at > now() - make_interval(days => :d)"
                    ),
                    {"d": days},
                )
            )
            .mappings()
            .one()
        )
        blocks = (
            await s.execute(
                text(
                    "SELECT count(*) FROM ai.guardrail_events"
                    " WHERE surface = 'output' AND verdict = 'block'"
                    "   AND created_at > now() - make_interval(days => :d)"
                ),
                {"d": days},
            )
        ).scalar_one()
    answers = int(row["answers"])
    return {
        "window_days": days,
        "answers": answers,
        "with_citations": int(row["with_citations"]),
        "citation_rate": round(int(row["with_citations"]) / answers, 4) if answers else None,
        "output_blocks": int(blocks),
        "judge_faithfulness": None,  # measured only by an eval run; never estimated here
        "source": "ai.copilot_messages, ai.guardrail_events",
    }
