"""Workflow evaluation CLI. Fixture runs measure orchestration, never model extraction quality."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.config import datasets_root, get_settings
from app.core.db import tenant_tx


def assess(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    wanted = set(expected.get("flags", []))
    found = {f["code"] for f in actual.get("flags", [])}
    route_ok = expected["route"] == actual.get("route")
    status_ok = expected["status"] == actual.get("status")
    flags_ok = wanted <= found
    false_auto = actual.get("route") == "auto" and expected["route"] != "auto"
    return {
        "passed": route_ok
        and status_ok
        and flags_ok
        and not false_auto
        and not actual.get("errors"),
        "route_correct": route_ok,
        "status_correct": status_ok,
        "missing_flags": sorted(wanted - found),
        "false_auto_post": false_auto,
    }


async def run(
    dataset: str, limit: int, fake: bool, org: str | None = None, delay: float = 2.1
) -> dict[str, Any]:
    from erp_mock.seed import bootstrap, seed

    from app.agents.invoice_to_pay.runner import execute
    from app.services.runs import create_document, create_run

    root = datasets_root()
    folder = root / ("demo" if dataset == "demo" else "golden_invoices/v1")
    source = (folder / "cases.jsonl").read_bytes()
    cases = [json.loads(line) for line in source.splitlines() if line.strip()][:limit]
    if not all(case.get("synthetic") is True for case in cases):
        raise ValueError("Public workflow reports require an explicitly synthetic dataset")
    org = org or "eval-" + uuid.uuid4().hex[:12]
    await bootstrap()
    await seed(org, root / "world")
    results = []
    started = time.monotonic()
    for index, case in enumerate(cases):
        if index and len(cases) > 5:
            await asyncio.sleep(delay)
        name = case["file"]["name"]
        path = folder / "files" / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != case["file"]["sha256"]:
            raise ValueError(f"Dataset file hash differs: {name}")
        doc = await create_document(
            org,
            "system:eval",
            name,
            path.read_bytes(),
            synthetic=True,
            demo_key=case.get("demo_key"),
        )
        run_id = await create_run(
            org,
            "system:eval",
            doc["document_id"],
            mode="fake" if fake else "live",
            git_sha=get_settings().git_sha,
        )
        try:
            outcome = await execute(
                run_id, org, "system:eval", document_id=doc["document_id"], fake=fake
            )
            async with tenant_tx(org) as session:
                state = (
                    await session.execute(
                        text("SELECT state FROM ap.runs WHERE id=:id"), {"id": run_id}
                    )
                ).scalar_one()
                if outcome.get("status") == "awaiting_approval":
                    # Paused runs have not executed finalize; use the persisted approval evidence.
                    packet = (
                        await session.execute(
                            text(
                                "SELECT packet FROM ap.approvals WHERE run_id=:id ORDER BY step DESC LIMIT 1"
                            ),
                            {"id": run_id},
                        )
                    ).scalar_one()
                    state = {
                        **state,
                        **outcome,
                        "flags": [{"code": code} for code in packet.get("flags", [])],
                    }
            result = assess(case["expected"], state)
            results.append(
                {
                    "case_id": case["case_id"],
                    "run_id": run_id,
                    "actual_status": state.get("status"),
                    "actual_route": state.get("route"),
                    "runtime_errors": state.get("errors", []),
                    **result,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "case_id": case["case_id"],
                    "run_id": run_id,
                    "passed": False,
                    "error": type(exc).__name__,
                }
            )
    count = len(results)
    errors = sum(bool(r.get("error") or r.get("runtime_errors")) for r in results)
    false_auto = sum(bool(r.get("false_auto_post")) for r in results)
    score = sum(bool(r["passed"]) for r in results) / count if count else None
    report = {
        "dataset": dataset,
        "dataset_version": hashlib.sha256(source).hexdigest(),
        "case_snapshot": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
        "org_id": org,
        "created_at": datetime.now(UTC).isoformat(),
        "provider_mode": "fake" if fake else "live",
        "mode": "workflow",
        "case_count": count,
        "metrics": {
            "pass_rate": score,
            "errors": errors,
            "false_auto_posts": false_auto,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "extraction_f1": None,
            "judge_agreement": None,
        },
        "results": results,
        "gate_passed": count > 0 and score == 1 and errors == 0 and false_auto == 0,
        "limits": "Fixture extraction is supplied ground truth; this is not a model accuracy benchmark."
        if fake
        else "Workflow route/status/flag checks only; extraction and judge calibration are not measured.",
    }
    async with tenant_tx(org) as session:
        await session.execute(
            text(
                "INSERT INTO ai.dataset_runs (dataset,dataset_version,mode,provider_mode,git_sha,case_count,metrics,results,config) VALUES (:d,:v,'workflow',:p,:g,:n,CAST(:m AS jsonb),CAST(:r AS jsonb),CAST(:c AS jsonb))"
            ),
            {
                "d": dataset,
                "v": report["dataset_version"],
                "p": report["provider_mode"],
                "g": get_settings().git_sha,
                "n": count,
                "m": json.dumps(report["metrics"]),
                "r": json.dumps(results),
                "c": json.dumps(
                    {
                        "org_id": org,
                        "synthetic": True,
                        "public_report": dataset == "demo",
                        "case_snapshot": report["case_snapshot"],
                        "gate_passed": report["gate_passed"],
                        "limits": report["limits"],
                    }
                ),
            },
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--dataset", choices=["demo", "golden_invoices"], default="demo")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--live", action="store_true", help="Calls real providers; consumes configured quotas"
    )
    parser.add_argument("--gate", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--delay",
        type=float,
        default=2.1,
        help="Seconds between invoices in larger runs; tool quotas remain enforced",
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 250:
        parser.error("limit must be between 1 and 250")
    if not 0 <= args.delay <= 60:
        parser.error("delay must be between 0 and 60 seconds")
    report = asyncio.run(run(args.dataset, args.limit, not args.live, delay=args.delay))
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n")
    print(rendered)
    if args.gate and not report["gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
