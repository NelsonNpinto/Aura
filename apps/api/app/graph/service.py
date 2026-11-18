"""Graph-backed risk checks and exploration (§B8.2).

Every result carries a status. When AuraDB is paused, not configured or the driver is absent the
status is `unavailable` with a reason — callers raise a MEDIUM flag and route to human review.
A graph check never reports a silent pass (§B18).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.core.logging import get_logger
from app.graph import guard, queries
from app.graph.client import GraphUnavailable, availability, read

log = get_logger("graph.service")

SPLIT_WINDOW_DAYS = 30


@dataclass(frozen=True)
class GraphFinding:
    code: str
    severity: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphResult:
    status: str  # ok | unavailable
    findings: tuple[GraphFinding, ...] = ()
    reason: str = "ok"

    @property
    def available(self) -> bool:
        return self.status == "ok"

    def public(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "findings": [asdict(f) for f in self.findings],
        }


def _unavailable(reason: str) -> GraphResult:
    return GraphResult(status="unavailable", reason=reason)


async def run_template(
    org_id: str, name: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Run a named, parameterised template. Raises GraphUnavailable when the graph is down."""
    cypher, bound = queries.resolve(name, org_id, params)
    rows = await read(cypher, bound)
    return guard.drop_foreign_rows(rows, org_id)


async def run_generated(org_id: str, cypher: str) -> dict[str, Any]:
    """Run guarded, model-generated Cypher. Synthetic demo tenant only (§B8.2)."""
    if not guard.free_form_allowed(org_id):
        raise guard.CypherRejected(
            "Generated Cypher runs only against the synthetic demo workspace",
            details={"reason": "org_not_allowed"},
        )
    safe = guard.validate(cypher)
    log.info("graph.generated_query", org_id=org_id, cypher=safe[:400])
    rows = await read(safe, {"org_id": org_id})
    return {"cypher": safe, "rows": guard.drop_foreign_rows(rows, org_id)}


async def neighborhood(org_id: str, vendor_id: str) -> dict[str, Any]:
    """Vendor-centric view for the explorer UI, with fraud patterns highlighted."""
    usable, reason = availability()
    if not usable:
        return {"status": "unavailable", "reason": reason, "vendor": None, "findings": []}
    try:
        rows = await run_template(org_id, "vendor_neighborhood", {"vendor_id": vendor_id})
    except GraphUnavailable as exc:
        return {
            "status": "unavailable",
            "reason": str(exc.details.get("reason", "error")),
            "vendor": None,
            "findings": [],
        }
    checks = await vendor_checks(org_id, vendor_id)
    return {
        "status": "ok",
        "reason": "ok",
        "vendor": rows[0] if rows else None,
        "findings": [asdict(f) for f in checks.findings],
    }


async def vendor_checks(
    org_id: str,
    vendor_id: str,
    *,
    approval_limit_minor: int | None = None,
    since: date | None = None,
) -> GraphResult:
    """Fraud and risk checks for one vendor (§B8.2).

    HIGH: a bank account shared with another vendor or an employee.
    MEDIUM: split invoices under an approval limit, a new vendor approved by its creator,
    duplicates across vendor aliases.
    """
    usable, reason = availability()
    if not usable:
        return _unavailable(reason)
    window_start = since or (datetime.now(UTC).date() - timedelta(days=SPLIT_WINDOW_DAYS))
    findings: list[GraphFinding] = []
    try:
        for row in await run_template(org_id, "vendor_bank_shared_with", {"vendor_id": vendor_id}):
            bank = row.get("bank_account") or {}
            others = [v.get("id") for v in row.get("vendors") or [] if v]
            employees = [e.get("id") for e in row.get("employees") or [] if e]
            if employees:
                findings.append(
                    GraphFinding(
                        "VENDOR_EMPLOYEE_CONFLICT",
                        "HIGH",
                        f"Bank account ending {bank.get('last4')} is also held by employee(s) "
                        f"{', '.join(employees)}.",
                        {"bank_last4": bank.get("last4"), "employees": employees},
                    )
                )
            if others:
                findings.append(
                    GraphFinding(
                        "SHARED_BANK_ACCOUNT",
                        "HIGH",
                        f"Bank account ending {bank.get('last4')} is shared with vendor(s) "
                        f"{', '.join(others)}.",
                        {"bank_last4": bank.get("last4"), "vendors": others},
                    )
                )
        if approval_limit_minor:
            for row in await run_template(
                org_id,
                "split_invoices",
                {
                    "vendor_id": vendor_id,
                    "since": window_start.isoformat(),
                    "limit_minor": int(approval_limit_minor),
                },
            ):
                invoices = [i.get("id") for i in row.get("invoices") or [] if i]
                findings.append(
                    GraphFinding(
                        "SPLIT_INVOICE_SUSPECTED",
                        "MEDIUM",
                        f"{len(invoices)} invoices in {SPLIT_WINDOW_DAYS} days each sit under the "
                        f"approval limit but total {row.get('total_minor')} minor units.",
                        {"invoices": invoices, "total_minor": row.get("total_minor")},
                    )
                )
        for row in await run_template(org_id, "new_vendor_fast_approval"):
            if (row.get("vendor") or {}).get("id") != vendor_id:
                continue
            findings.append(
                GraphFinding(
                    "VENDOR_CREATOR_APPROVED",
                    "MEDIUM",
                    "This vendor's invoice was approved by the user who created the vendor.",
                    {
                        "approver": (row.get("approver") or {}).get("id"),
                        "invoice": (row.get("invoice") or {}).get("id"),
                    },
                )
            )
        for row in await run_template(org_id, "duplicate_across_aliases"):
            ids = {(row.get("vendor_a") or {}).get("id"), (row.get("vendor_b") or {}).get("id")}
            if vendor_id not in ids:
                continue
            findings.append(
                GraphFinding(
                    "ALIAS_DUPLICATE",
                    "MEDIUM",
                    "The same invoice number is billed by two vendor records sharing a tax ID.",
                    {"vendors": sorted(i for i in ids if i)},
                )
            )
    except GraphUnavailable as exc:
        return _unavailable(str(exc.details.get("reason", "error")))
    return GraphResult(status="ok", findings=tuple(findings))


async def org_fraud_overview(org_id: str) -> dict[str, Any]:
    """Portfolio-level patterns for the graph explorer landing view."""
    usable, reason = availability()
    if not usable:
        return {"status": "unavailable", "reason": reason, "patterns": {}}
    try:
        patterns = {
            "shared_bank_accounts": await run_template(org_id, "shared_bank_accounts"),
            "employee_vendor_conflicts": await run_template(org_id, "employee_vendor_conflicts"),
            "new_vendor_fast_approval": await run_template(org_id, "new_vendor_fast_approval"),
            "duplicate_across_aliases": await run_template(org_id, "duplicate_across_aliases"),
        }
    except GraphUnavailable as exc:
        return {
            "status": "unavailable",
            "reason": str(exc.details.get("reason", "error")),
            "patterns": {},
        }
    return {"status": "ok", "reason": "ok", "patterns": patterns}
