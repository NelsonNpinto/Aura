"""Baselines and regression gates (§B13).

A comparison is only valid when the baseline and the candidate share the same case snapshot and
the same run mode. A mismatch is reported as `invalid_comparison`, never silently compared —
otherwise a gate can "pass" because the dataset changed underneath it.

Hard gates (never relaxed by thresholds):
  * no false auto-post on a HIGH-risk case;
  * human-in-the-loop triggered wherever the case requires it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Thresholds:
    min_score: float = 1.0
    max_score_drop: float = 0.0
    max_latency_increase: float = 0.25  # relative
    max_errors: int = 0

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Thresholds:
        d = data or {}
        return cls(
            min_score=float(d.get("min_score", 1.0)),
            max_score_drop=float(d.get("max_score_drop", 0.0)),
            max_latency_increase=float(d.get("max_latency_increase", 0.25)),
            max_errors=int(d.get("max_errors", 0)),
        )


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]
    comparison: str  # baseline | no_baseline | invalid_comparison
    details: dict[str, Any]

    def public(self) -> dict[str, Any]:
        return asdict(self)


def hard_gate_failures(report: dict[str, Any]) -> list[str]:
    metrics = report.get("metrics", {})
    reasons = []
    if metrics.get("false_auto_posts"):
        reasons.append(f"{metrics['false_auto_posts']} false auto-post(s) on non-auto cases")
    missed = metrics.get("hitl_missed")
    if missed:
        reasons.append(f"human-in-the-loop not triggered on {missed} case(s) that required it")
    return reasons


def evaluate(
    report: dict[str, Any],
    baseline: dict[str, Any] | None,
    thresholds: Thresholds | None = None,
    *,
    score_metric: str = "pass_rate",
) -> GateResult:
    t = thresholds or Thresholds()
    metrics = report.get("metrics", {})
    score = metrics.get(score_metric)
    reasons = list(hard_gate_failures(report))

    if int(metrics.get("errors") or 0) > t.max_errors:
        reasons.append(f"{metrics['errors']} error(s) exceeds max_errors={t.max_errors}")
    if score is None:
        reasons.append(f"{score_metric} was not measured")
    elif score < t.min_score:
        reasons.append(f"{score_metric} {score:.3f} below min_score {t.min_score:.3f}")

    comparison = "no_baseline"
    details: dict[str, Any] = {
        "thresholds": asdict(t),
        "score_metric": score_metric,
        "score": score,
    }
    if baseline:
        same_snapshot = baseline.get("case_snapshot") == report.get("case_snapshot")
        same_mode = baseline.get("mode") == report.get("mode")
        if not (same_snapshot and same_mode):
            comparison = "invalid_comparison"
            reasons.append(
                "baseline is not comparable: "
                + ("case snapshot differs" if not same_snapshot else "run mode differs")
            )
        else:
            comparison = "baseline"
            base_metrics = baseline.get("metrics", {})
            base_score = base_metrics.get(score_metric)
            details["baseline_score"] = base_score
            if base_score is not None and score is not None:
                drop = base_score - score
                details["score_drop"] = round(drop, 4)
                if drop > t.max_score_drop:
                    reasons.append(
                        f"{score_metric} dropped {drop:.3f} vs baseline"
                        f" (max {t.max_score_drop:.3f})"
                    )
            base_latency = base_metrics.get("duration_ms")
            latency = metrics.get("duration_ms")
            if base_latency and latency:
                increase = (latency - base_latency) / base_latency
                details["latency_increase"] = round(increase, 4)
                if increase > t.max_latency_increase:
                    reasons.append(
                        f"duration increased {increase:.0%} (max {t.max_latency_increase:.0%})"
                    )
    return GateResult(not reasons, tuple(reasons), comparison, details)


async def load_baseline(session: AsyncSession, org_id: str, dataset: str) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT b.dataset, b.case_snapshot, b.mode, b.metrics, b.run_id, b.created_at"
                    " FROM ai.baselines b WHERE b.org_id = :o AND b.dataset = :d"
                ),
                {"o": org_id, "d": dataset},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def set_baseline(
    session: AsyncSession,
    org_id: str,
    *,
    dataset: str,
    run_id: str,
    case_snapshot: str,
    mode: str,
    metrics: dict[str, Any],
    created_by: str,
    justification: str,
) -> None:
    """Promote one error-free run to the dataset's baseline. Written justification required."""
    if not justification.strip():
        raise ValueError("A written justification is required to move a baseline")
    await session.execute(
        text(
            "INSERT INTO ai.baselines (org_id, dataset, run_id, case_snapshot, mode, metrics,"
            " justification, created_by)"
            " VALUES (:o, :d, :r, :cs, :m, CAST(:met AS jsonb), :j, :u)"
            " ON CONFLICT (org_id, dataset) DO UPDATE SET run_id = EXCLUDED.run_id,"
            "   case_snapshot = EXCLUDED.case_snapshot, mode = EXCLUDED.mode,"
            "   metrics = EXCLUDED.metrics, justification = EXCLUDED.justification,"
            "   created_by = EXCLUDED.created_by, created_at = now()"
        ),
        {
            "o": org_id,
            "d": dataset,
            "r": run_id,
            "cs": case_snapshot,
            "m": mode,
            "met": json.dumps(metrics),
            "j": justification,
            "u": created_by,
        },
    )
