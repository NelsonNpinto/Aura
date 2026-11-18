"""Public eval report builder (§B13).

Built from stored `ai.dataset_runs` rows only. Every headline figure carries the run id, the
dataset version and the date it was measured. Anything that has not been measured stays null,
and the page renders it as "not measured" — the builder never fills a gap with an estimate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

PUBLIC_DATASETS = (
    "demo",
    "golden_invoices",
    "finance_copilot",
    "redteam",
    "policy_qa",
    "copilot_tasks",
)


async def latest_runs(
    session: AsyncSession, datasets: tuple[str, ...] = PUBLIC_DATASETS
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (dataset) id, dataset, dataset_version, mode,"
                    " provider_mode, git_sha, case_count, metrics, config, created_at"
                    " FROM ai.dataset_runs WHERE dataset = ANY(:ds)"
                    " ORDER BY dataset, created_at DESC"
                ),
                {"ds": list(datasets)},
            )
        )
        .mappings()
        .all()
    )
    return {r["dataset"]: dict(r) for r in rows}


def _figure(run: dict[str, Any] | None, metric: str) -> dict[str, Any]:
    """One headline figure, always traceable to the run that produced it."""
    if not run:
        return {"value": None, "status": "not measured", "run_id": None}
    value = (run.get("metrics") or {}).get(metric)
    return {
        "value": value,
        "status": "measured" if value is not None else "not measured",
        "run_id": str(run["id"]),
        "dataset": run["dataset"],
        "dataset_version": run["dataset_version"][:12] if run.get("dataset_version") else None,
        "provider_mode": run.get("provider_mode"),
        "measured_at": run["created_at"].isoformat(),
    }


async def build(session: AsyncSession, *, slug: str = "public") -> dict[str, Any]:
    runs = await latest_runs(session)
    workflow = runs.get("golden_invoices") or runs.get("demo")
    report = {
        "slug": slug,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": get_settings().git_sha,
        "headline": {
            "workflow_pass_rate": _figure(workflow, "pass_rate"),
            "false_auto_posts": _figure(workflow, "false_auto_posts"),
            "extraction_f1": _figure(workflow, "extraction_f1"),
            "stp_rate": _figure(workflow, "stp_rate"),
            "attack_success_rate": _figure(runs.get("redteam"), "attack_success_rate"),
            "guardrail_false_positive_rate": _figure(runs.get("redteam"), "false_positive_rate"),
            "copilot_citation_validity": _figure(runs.get("finance_copilot"), "citation_validity"),
            "rag_faithfulness": _figure(runs.get("policy_qa"), "faithfulness"),
            "trajectory_accuracy": _figure(runs.get("copilot_tasks"), "trajectory_accuracy"),
            "cost_microusd_per_case": _figure(workflow, "cost_microusd_per_case"),
            "p95_latency_ms": _figure(workflow, "p95_latency_ms"),
            "judge_kappa": _figure(runs.get("finance_copilot"), "judge_kappa"),
        },
        "runs": [
            {
                "id": str(r["id"]),
                "dataset": r["dataset"],
                "dataset_version": r["dataset_version"],
                "mode": r["mode"],
                "provider_mode": r["provider_mode"],
                "case_count": r["case_count"],
                "git_sha": r["git_sha"],
                "metrics": r["metrics"],
                "measured_at": r["created_at"].isoformat(),
                "limits": (r.get("config") or {}).get("limits"),
            }
            for r in runs.values()
        ],
        "notes": [
            "All data is synthetic. Figures come from stored runs; nothing here is projected.",
            "A figure shown as 'not measured' has no stored run behind it yet.",
            "Fixture (provider_mode=fake) runs measure orchestration, not model accuracy.",
        ],
    }
    return report


async def publish(
    session: AsyncSession, org_id: str, report: dict[str, Any], *, slug: str = "public"
) -> str:
    row = (
        await session.execute(
            text(
                "INSERT INTO ai.eval_reports (org_id, slug, report, published, git_sha)"
                " VALUES (:o, :s, CAST(:r AS jsonb), true, :g)"
                " ON CONFLICT (org_id, slug) DO UPDATE SET report = EXCLUDED.report,"
                "   published = true, git_sha = EXCLUDED.git_sha, created_at = now()"
                " RETURNING id"
            ),
            {
                "o": org_id,
                "s": slug,
                "r": json.dumps(report, default=str),
                "g": get_settings().git_sha,
            },
        )
    ).scalar_one()
    return str(row)
