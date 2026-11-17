"""Parameterised Cypher templates (§B8.2).

Tenant data is reachable only through these templates: `$org_id` is a bound parameter, never
interpolated, and the copilot's `graph_query` tool picks a template by name before it is ever
allowed to fall back to guarded generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.errors import AppError


class UnknownTemplate(AppError):
    status_code = 400
    code = "unknown_graph_template"


@dataclass(frozen=True)
class Template:
    name: str
    description: str
    cypher: str
    params: tuple[str, ...] = ()


def _t(name: str, description: str, cypher: str, *params: str) -> Template:
    return Template(name, description, " ".join(cypher.split()), params)


TEMPLATES: dict[str, Template] = {
    t.name: t
    for t in (
        _t(
            "vendor_neighborhood",
            "Vendor with its bank accounts, contracts, purchase orders and recent invoices.",
            """
            MATCH (v:Vendor {org_id: $org_id, id: $vendor_id})
            OPTIONAL MATCH (v)-[:HAS_BANK_ACCOUNT]->(b:BankAccount)
            OPTIONAL MATCH (v)-[:UNDER_CONTRACT]->(c:Contract)
            OPTIONAL MATCH (po:PurchaseOrder {org_id: $org_id})-[:ISSUED_TO]->(v)
            OPTIONAL MATCH (i:Invoice {org_id: $org_id})-[:BILLED_BY]->(v)
            RETURN v {.id, .name, .tax_id, .org_id, .created_by, .created_at} AS vendor,
                   collect(DISTINCT b {.id, .last4, .org_id}) AS bank_accounts,
                   collect(DISTINCT c {.id, .title, .org_id}) AS contracts,
                   collect(DISTINCT po {.id, .org_id}) AS purchase_orders,
                   collect(DISTINCT i {.id, .amount_minor, .currency, .invoice_date, .org_id})[0..25]
                       AS invoices
            LIMIT 1
            """,
            "vendor_id",
        ),
        _t(
            "shared_bank_accounts",
            "Bank accounts shared by two or more vendors.",
            """
            MATCH (v:Vendor {org_id: $org_id})-[:HAS_BANK_ACCOUNT]->(b:BankAccount {org_id: $org_id})
            WITH b, collect(DISTINCT v {.id, .name, .org_id}) AS vendors
            WHERE size(vendors) > 1
            RETURN b {.id, .last4, .org_id} AS bank_account, vendors
            LIMIT 50
            """,
        ),
        _t(
            "vendor_bank_shared_with",
            "Other vendors and employees that share this vendor's bank accounts.",
            """
            MATCH (v:Vendor {org_id: $org_id, id: $vendor_id})-[:HAS_BANK_ACCOUNT]->(b:BankAccount)
            OPTIONAL MATCH (other:Vendor {org_id: $org_id})-[:HAS_BANK_ACCOUNT]->(b)
            WHERE other.id <> v.id
            OPTIONAL MATCH (e:Employee {org_id: $org_id})-[:HAS_BANK_ACCOUNT]->(b)
            WITH b, collect(DISTINCT other {.id, .name, .org_id}) AS vendors,
                 collect(DISTINCT e {.id, .name, .org_id}) AS employees
            WHERE size(vendors) > 0 OR size(employees) > 0
            RETURN b {.id, .last4, .org_id} AS bank_account, vendors, employees
            LIMIT 20
            """,
            "vendor_id",
        ),
        _t(
            "employee_vendor_conflicts",
            "Employees sharing a bank account with a vendor.",
            """
            MATCH (e:Employee {org_id: $org_id})-[:HAS_BANK_ACCOUNT]->(b:BankAccount)
                  <-[:HAS_BANK_ACCOUNT]-(v:Vendor {org_id: $org_id})
            RETURN e {.id, .name, .org_id} AS employee, v {.id, .name, .org_id} AS vendor,
                   b {.id, .last4, .org_id} AS bank_account
            LIMIT 50
            """,
        ),
        _t(
            "split_invoices",
            "Invoices from one vendor inside a short window that each sit under the approval "
            "limit but exceed it together.",
            """
            MATCH (i:Invoice {org_id: $org_id})-[:BILLED_BY]->(v:Vendor {org_id: $org_id, id: $vendor_id})
            WHERE i.invoice_date >= $since AND i.amount_minor < $limit_minor
            WITH v, collect(i {.id, .amount_minor, .currency, .invoice_date, .org_id}) AS invoices,
                 sum(i.amount_minor) AS total_minor
            WHERE size(invoices) > 1 AND total_minor >= $limit_minor
            RETURN v {.id, .name, .org_id} AS vendor, invoices, total_minor
            LIMIT 20
            """,
            "vendor_id",
            "since",
            "limit_minor",
        ),
        _t(
            "new_vendor_fast_approval",
            "First invoice of a recently created vendor approved by the user who created it.",
            """
            MATCH (v:Vendor {org_id: $org_id})<-[:BILLED_BY]-(i:Invoice {org_id: $org_id})
            MATCH (i)-[:APPROVED_BY]->(u:User {org_id: $org_id})
            WHERE v.created_by IS NOT NULL AND u.id = v.created_by
            RETURN v {.id, .name, .created_by, .org_id} AS vendor,
                   i {.id, .amount_minor, .currency, .invoice_date, .org_id} AS invoice,
                   u {.id, .name, .org_id} AS approver
            LIMIT 20
            """,
        ),
        _t(
            "duplicate_across_aliases",
            "Same invoice number billed by vendors that share a tax ID (alias duplicates).",
            """
            MATCH (a:Vendor {org_id: $org_id})<-[:BILLED_BY]-(i1:Invoice {org_id: $org_id}),
                  (b:Vendor {org_id: $org_id})<-[:BILLED_BY]-(i2:Invoice {org_id: $org_id})
            WHERE a.id < b.id AND a.tax_id IS NOT NULL AND a.tax_id = b.tax_id
                  AND i1.normalized_number = i2.normalized_number
            RETURN a {.id, .name, .org_id} AS vendor_a, b {.id, .name, .org_id} AS vendor_b,
                   i1 {.id, .amount_minor, .org_id} AS invoice_a,
                   i2 {.id, .amount_minor, .org_id} AS invoice_b
            LIMIT 20
            """,
        ),
        _t(
            "decision_evidence",
            "Decision lineage mirrored from the audit chain.",
            """
            MATCH (d:Decision {org_id: $org_id, id: $decision_id})
            OPTIONAL MATCH (d)-[:BASED_ON]->(e:Evidence)
            OPTIONAL MATCH (d)-[:ABOUT]->(t)
            RETURN d {.id, .action, .decision, .ts, .org_id} AS decision,
                   collect(DISTINCT e {.id, .kind, .ref, .org_id}) AS evidence,
                   collect(DISTINCT labels(t)[0]) AS about
            LIMIT 1
            """,
            "decision_id",
        ),
    )
}


def resolve(
    name: str, org_id: str, params: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """Return (cypher, params) for a named template. Unknown names are rejected, not generated."""
    tpl = TEMPLATES.get(name)
    if tpl is None:
        raise UnknownTemplate(
            f"Unknown graph template '{name}'", details={"known": sorted(TEMPLATES)}
        )
    given = dict(params or {})
    missing = [p for p in tpl.params if given.get(p) in (None, "")]
    if missing:
        raise UnknownTemplate(
            f"Template '{name}' needs {', '.join(missing)}", details={"missing": missing}
        )
    bound = {p: given[p] for p in tpl.params}
    bound["org_id"] = org_id
    return tpl.cypher, bound


def catalog() -> list[dict[str, Any]]:
    return [
        {"name": t.name, "description": t.description, "params": list(t.params)}
        for t in TEMPLATES.values()
    ]
