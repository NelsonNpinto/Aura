"""Deterministic risk score and route (§B6 risk_route). Never auto-posts on error."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.domain.approval import ApprovalMatrix, Level, Requirement, required_approval
from app.domain.flags import Flag, Severity
from app.domain.matching import MatchResult

WEIGHTS = {Severity.HIGH: 40, Severity.MEDIUM: 15, Severity.LOW: 2}


class Route(StrEnum):
    AUTO = "auto"
    APPROVAL = "approval"
    EXCEPTION = "exception"


@dataclass(frozen=True)
class RiskDecision:
    score: int
    level: str
    route: Route
    approval: Requirement | None
    reasons: tuple[str, ...]


def decide(
    *,
    amount_base_minor: int,
    flags: list[Flag],
    match: MatchResult | None,
    matrix: ApprovalMatrix,
    errors: list[str] | None = None,
    missing_po_allowed: bool = False,
) -> RiskDecision:
    reasons: list[str] = []
    score = min(100, sum(WEIGHTS[f.severity] for f in flags))
    level = "high" if score >= 40 else "medium" if score >= 15 else "low"
    req = required_approval(amount_base_minor, flags, matrix)

    if errors:
        return RiskDecision(
            score, level, Route.EXCEPTION, None, ("processing errors: " + "; ".join(errors),)
        )
    if any(f.severity == Severity.HIGH for f in flags):
        reasons.extend(req.reasons)
        return RiskDecision(score, level, Route.APPROVAL, req, tuple(reasons))

    unresolved = []
    if match is not None:
        for m in match.lines:
            if m.outcome.value in ("no_po",) and missing_po_allowed:
                continue
            if m.outcome.value in ("no_po", "no_receipt", "uom_mismatch"):
                unresolved.append(f"line {m.index}: {m.outcome.value}")
            if m.outcome.value in ("price_variance", "qty_variance"):
                unresolved.append(f"line {m.index}: {m.outcome.value}")
        if any("exceeds" in n for m in match.lines for n in m.notes):
            unresolved.append("non-PO charge above tolerance")
        if not match.header_ok:
            unresolved.append("header total outside tolerance")
    if unresolved:
        return RiskDecision(score, level, Route.EXCEPTION, None, tuple(unresolved))

    if req.level != Level.AUTO:
        return RiskDecision(score, level, Route.APPROVAL, req, req.reasons)
    return RiskDecision(score, level, Route.AUTO, req, req.reasons)
