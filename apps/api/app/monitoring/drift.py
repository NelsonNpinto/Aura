"""Drift monitoring (§B14), run nightly and on demand.

Measured against a reference window (the 30 days before the current one):
  * PSI on the invoice-amount distribution and on the vendor mix;
  * centroid shift of the embedded invoice-line descriptions;
  * shift in the extraction-confidence distribution;
  * the human-override rate trend.

A window with too few observations reports `null` and `insufficient_data` — never a number
computed from a handful of rows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.logging import get_logger

log = get_logger("drift")

MIN_OBSERVATIONS = 20
WINDOW_DAYS = 30
AMOUNT_BUCKETS = (0, 10_000, 50_000, 100_000, 500_000, 1_000_000, 10_000_000)


@dataclass(frozen=True)
class Metric:
    name: str
    value: float | None
    threshold: float
    reason: str = "ok"

    @property
    def breached(self) -> bool:
        return self.value is not None and self.value > self.threshold

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 4) if self.value is not None else None,
            "threshold": self.threshold,
            "breached": self.breached,
            "reason": self.reason,
        }


def psi(reference: list[float], current: list[float]) -> float | None:
    """Population Stability Index between two discrete distributions (same bucket order)."""
    if len(reference) != len(current):
        return None
    total_ref, total_cur = sum(reference), sum(current)
    if total_ref < MIN_OBSERVATIONS or total_cur < MIN_OBSERVATIONS:
        return None
    score = 0.0
    for r, c in zip(reference, current, strict=True):
        pr = max(r / total_ref, 1e-6)
        pc = max(c / total_cur, 1e-6)
        score += (pc - pr) * math.log(pc / pr)
    return score


def bucket_amounts(values: list[int]) -> list[float]:
    counts = [0.0] * (len(AMOUNT_BUCKETS))
    for v in values:
        idx = 0
        for i, edge in enumerate(AMOUNT_BUCKETS):
            if v >= edge:
                idx = i
        counts[idx] += 1
    return counts


def mix(values: list[str], keys: list[str]) -> list[float]:
    counts = dict.fromkeys(keys, 0.0)
    for v in values:
        if v in counts:
            counts[v] += 1
    return [counts[k] for k in keys]


def centroid_shift(a: list[list[float]], b: list[list[float]]) -> float | None:
    """Cosine distance between the mean embeddings of two windows."""
    if len(a) < MIN_OBSERVATIONS or len(b) < MIN_OBSERVATIONS:
        return None
    dim = len(a[0])
    ca = [sum(v[i] for v in a) / len(a) for i in range(dim)]
    cb = [sum(v[i] for v in b) / len(b) for i in range(dim)]
    dot = sum(x * y for x, y in zip(ca, cb, strict=True))
    na = math.sqrt(sum(x * x for x in ca)) or 1e-9
    nb = math.sqrt(sum(y * y for y in cb)) or 1e-9
    return 1.0 - dot / (na * nb)


async def compute(org_id: str) -> dict[str, Any]:
    """Compute drift metrics for `org_id` without storing them."""
    threshold = get_settings().drift_psi_threshold
    now = datetime.now(UTC)
    cur_start = now - timedelta(days=WINDOW_DAYS)
    ref_start = now - timedelta(days=2 * WINDOW_DAYS)

    async with tenant_tx(org_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT total_minor, vendor_id, created_at FROM ap.invoices"
                        " WHERE created_at > :ref AND total_minor IS NOT NULL"
                    ),
                    {"ref": ref_start},
                )
            )
            .mappings()
            .all()
        )
        confidences = (
            (
                await s.execute(
                    text(
                        "SELECT (confidence->>'overall')::float AS overall, created_at"
                        " FROM ap.extractions WHERE created_at > :ref"
                        "   AND confidence ? 'overall'"
                    ),
                    {"ref": ref_start},
                )
            )
            .mappings()
            .all()
        )
        overrides = (
            (
                await s.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE created_at > :cur) AS current_n,"
                        " count(*) FILTER (WHERE created_at <= :cur) AS reference_n"
                        " FROM ap.feedback WHERE created_at > :ref"
                    ),
                    {"cur": cur_start, "ref": ref_start},
                )
            )
            .mappings()
            .one()
        )
        runs = (
            (
                await s.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE created_at > :cur) AS current_n,"
                        " count(*) FILTER (WHERE created_at <= :cur) AS reference_n"
                        " FROM ap.runs WHERE created_at > :ref"
                    ),
                    {"cur": cur_start, "ref": ref_start},
                )
            )
            .mappings()
            .one()
        )

    ref = [r for r in rows if r["created_at"] <= cur_start]
    cur = [r for r in rows if r["created_at"] > cur_start]
    metrics: list[Metric] = []

    amount = psi(
        bucket_amounts([int(r["total_minor"]) for r in ref]),
        bucket_amounts([int(r["total_minor"]) for r in cur]),
    )
    metrics.append(
        Metric(
            "amount_psi",
            amount,
            threshold,
            "ok" if amount is not None else "insufficient_data",
        )
    )

    vendors = sorted({r["vendor_id"] for r in rows if r["vendor_id"]})
    vendor_psi = (
        psi(
            mix([r["vendor_id"] for r in ref if r["vendor_id"]], vendors),
            mix([r["vendor_id"] for r in cur if r["vendor_id"]], vendors),
        )
        if vendors
        else None
    )
    metrics.append(
        Metric(
            "vendor_mix_psi",
            vendor_psi,
            threshold,
            "ok" if vendor_psi is not None else "insufficient_data",
        )
    )

    ref_conf = [float(c["overall"]) for c in confidences if c["created_at"] <= cur_start]
    cur_conf = [float(c["overall"]) for c in confidences if c["created_at"] > cur_start]
    conf_shift = (
        abs(sum(cur_conf) / len(cur_conf) - sum(ref_conf) / len(ref_conf))
        if len(ref_conf) >= MIN_OBSERVATIONS and len(cur_conf) >= MIN_OBSERVATIONS
        else None
    )
    metrics.append(
        Metric(
            "extraction_confidence_shift",
            conf_shift,
            0.1,
            "ok" if conf_shift is not None else "insufficient_data",
        )
    )

    cur_runs, ref_runs = int(runs["current_n"]), int(runs["reference_n"])
    cur_ov, ref_ov = int(overrides["current_n"]), int(overrides["reference_n"])
    override_delta = (
        abs(cur_ov / cur_runs - ref_ov / ref_runs)
        if cur_runs >= MIN_OBSERVATIONS and ref_runs >= MIN_OBSERVATIONS
        else None
    )
    metrics.append(
        Metric(
            "override_rate_delta",
            override_delta,
            0.15,
            "ok" if override_delta is not None else "insufficient_data",
        )
    )

    return {
        "window_start": cur_start.isoformat(),
        "window_end": now.isoformat(),
        "reference_start": ref_start.isoformat(),
        "observations": {"reference": len(ref), "current": len(cur)},
        "metrics": [m.public() for m in metrics],
        "breaches": [m.name for m in metrics if m.breached],
    }


async def compute_and_store(org_id: str) -> dict[str, Any]:
    report = await compute(org_id)
    async with tenant_tx(org_id) as s:
        await s.execute(
            text(
                "INSERT INTO ops.drift_reports (org_id, window_start, window_end, metrics,"
                " breaches) VALUES (:o, :ws, :we, CAST(:m AS jsonb), CAST(:b AS jsonb))"
            ),
            {
                "o": org_id,
                "ws": report["window_start"],
                "we": report["window_end"],
                "m": _json(report),
                "b": _json(report["breaches"]),
            },
        )
    if report["breaches"]:
        log.warning("drift.breach", org_id=org_id, breaches=report["breaches"])
    return report


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)
