"""Public eval report (§B13).

Served from stored runs only. Every figure carries the dataset version, the run id that produced
it and the date it was measured; anything that was not measured is `null` and the UI renders it
as "not measured". Nothing here is computed on the fly from an estimate.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import system_tx
from app.core.errors import NotFound

router = APIRouter(prefix="/eval-report", tags=["eval-report"])

PUBLIC_ORG = "demo"
DEFAULT_SLUG = "public"


@router.get("")
async def public_report(slug: str = Query(default=DEFAULT_SLUG, max_length=60)) -> dict[str, Any]:
    """The published report. 404 when nothing has been published yet — never a placeholder."""
    async with system_tx() as s:
        row = (
            (
                await s.execute(
                    text(
                        "SELECT slug, report, git_sha, created_at FROM ai.eval_reports"
                        " WHERE org_id = :o AND slug = :s AND published"
                        " ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"o": PUBLIC_ORG, "s": slug},
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        raise NotFound(
            "No eval report has been published yet",
            details={"hint": "Run `aura-eval report --publish` after a dataset run."},
        )
    return {
        "slug": row["slug"],
        "git_sha": row["git_sha"],
        "published_at": row["created_at"].isoformat(),
        **row["report"],
    }


@router.get("/badges")
async def badges(slug: str = Query(default=DEFAULT_SLUG, max_length=60)) -> dict[str, Any]:
    """shields.io endpoint payloads for the README badges."""
    try:
        report = await public_report(slug)
    except NotFound:
        return {
            "schemaVersion": 1,
            "label": "evals",
            "message": "not measured",
            "color": "lightgrey",
        }
    headline = report.get("headline", {})
    stp = headline.get("stp_rate")
    return {
        "schemaVersion": 1,
        "label": "straight-through",
        "message": f"{stp:.0%}" if isinstance(stp, (int, float)) else "not measured",
        "color": "brightgreen" if isinstance(stp, (int, float)) and stp >= 0.5 else "lightgrey",
    }


@router.get("/runs")
async def recent_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """Dataset runs behind the published numbers, so each figure can be traced to its run."""
    async with system_tx() as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT id, dataset, dataset_version, mode, provider_mode, git_sha,"
                        " case_count, metrics, created_at FROM ai.dataset_runs"
                        " ORDER BY created_at DESC LIMIT :lim"
                    ),
                    {"lim": limit},
                )
            )
            .mappings()
            .all()
        )
    return {
        "runs": [
            {
                **{k: v for k, v in r.items() if k not in ("id", "created_at")},
                "id": str(r["id"]),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ],
        "git_sha": get_settings().git_sha,
    }
