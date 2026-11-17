"""Nightly maintenance jobs (§B14, §B8.2, §B8.3).

    python -m app.scripts.nightly --drift --memory-decay --graph-sync --anchor

Each job is independent and records its outcome in `ops.job_runs`; one failing job never stops
the others. Nothing here writes a metric it did not measure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.core.db import system_tx, tenant_tx
from app.core.logging import get_logger

log = get_logger("nightly")


async def _record(job: str, status: str, details: dict[str, Any]) -> None:
    async with system_tx() as s:
        await s.execute(
            text(
                "INSERT INTO ops.job_runs (job, status, details, finished_at)"
                " VALUES (:j, :s, CAST(:d AS jsonb), :f)"
            ),
            {"j": job, "s": status, "d": json.dumps(details, default=str), "f": datetime.now(UTC)},
        )


async def _orgs() -> list[str]:
    async with system_tx() as s:
        rows = (await s.execute(text("SELECT org_id FROM core.org_settings"))).all()
    return [r[0] for r in rows] or ["demo"]


async def job_drift() -> dict[str, Any]:
    from app.monitoring.drift import compute_and_store

    out = {}
    for org in await _orgs():
        report = await compute_and_store(org)
        out[org] = {"breaches": report["breaches"], "observations": report["observations"]}
    return out


async def job_memory_decay() -> dict[str, Any]:
    from app.memory.store import decay

    out = {}
    for org in await _orgs():
        async with tenant_tx(org) as s:
            out[org] = await decay(s, org)
    return out


async def job_graph_sync() -> dict[str, Any]:
    from app.graph.sync import drain

    return await drain(500)


async def job_anchor() -> dict[str, Any]:
    """Print each org's audit chain head so the anchor workflow can commit it (§B12)."""
    from app.audit.chain import verify

    out = {}
    for org in await _orgs():
        async with tenant_tx(org) as s:
            v = await verify(s, org)
        out[org] = {
            "head_seq": v.head_seq,
            "head_hash": v.head_hash,
            "verified": v.verified,
            "events": v.events_checked,
        }
    return out


JOBS = {
    "drift": job_drift,
    "memory_decay": job_memory_decay,
    "graph_sync": job_graph_sync,
    "anchor": job_anchor,
}


async def _main(selected: list[str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name in selected:
        try:
            results[name] = await JOBS[name]()
            await _record(name, "ok", results[name])
        except Exception as exc:  # one failing job never stops the rest
            log.error("nightly.job_failed", job=name, error=type(exc).__name__)
            results[name] = {"error": type(exc).__name__}
            await _record(name, "error", results[name])
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in JOBS:
        parser.add_argument(f"--{name.replace('_', '-')}", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    selected = [n for n in JOBS if args.all or getattr(args, n)]
    if not selected:
        parser.error("choose at least one job, or --all")
    results = asyncio.run(_main(selected))
    print(json.dumps(results, indent=2, default=str))
    sys.exit(1 if any("error" in (v or {}) for v in results.values()) else 0)


if __name__ == "__main__":
    main()
