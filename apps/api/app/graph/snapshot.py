"""Static graph snapshot for the synthetic demo workspace, used only while Neo4j is unreachable.

The demo tenant's graph is projected from the bundled synthetic ERP world (`datasets/world`).
When AuraDB is paused or gone, the explorer and the copilot answer the bank-account templates
from that same file instead of showing an error. Results are labelled `static`.

Only templates that depend on master data alone are served. Templates that need live invoices
or decisions (split invoices, fast approvals, alias duplicates, decision history) stay
unavailable rather than return an empty list that would read as "nothing found". The invoice
workflow never uses this module: its relationship checks still fail closed to human review.
"""

from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache
from typing import Any

from app.core.auth import DEMO_ORG_ID
from app.core.config import datasets_root

TEMPLATES = frozenset(
    {
        "vendor_neighborhood",
        "shared_bank_accounts",
        "vendor_bank_shared_with",
        "employee_vendor_conflicts",
    }
)
NOTE = "Static snapshot of the synthetic demo data; the live knowledge graph is offline."


@lru_cache
def _world() -> dict[str, Any] | None:
    path = datasets_root() / "world" / "world.json"
    if not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def supports(org_id: str, name: str) -> bool:
    return org_id == DEMO_ORG_ID and name in TEMPLATES and _world() is not None


def _ref(item: dict[str, Any], org_id: str) -> dict[str, Any]:
    return {"id": item["id"], "name": item["name"], "org_id": org_id}


def _bank(digest: str, last4: str | None, org_id: str) -> dict[str, Any]:
    return {"id": digest, "last4": last4, "org_id": org_id}


def _accounts(org_id: str) -> dict[str, dict[str, Any]]:
    """Bank account hash -> {bank, vendors, employees}."""
    world = _world() or {}
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"bank": None, "vendors": [], "employees": []}
    )
    for v in world.get("vendors", []):
        bank = v.get("bank") or {}
        if bank.get("hash"):
            entry = out[bank["hash"]]
            entry["bank"] = _bank(bank["hash"], bank.get("last4"), org_id)
            entry["vendors"].append(_ref(v, org_id))
    for e in world.get("employees", []):
        if e.get("bank_hash"):
            entry = out[e["bank_hash"]]
            entry["bank"] = entry["bank"] or _bank(e["bank_hash"], e.get("bank_last4"), org_id)
            entry["employees"].append(_ref(e, org_id))
    return out


def run(org_id: str, name: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Rows shaped like the matching Cypher template's RETURN clause."""
    if not supports(org_id, name):
        raise KeyError(name)
    params = params or {}
    world = _world() or {}
    accounts = _accounts(org_id)
    if name == "shared_bank_accounts":
        return [
            {"bank_account": a["bank"], "vendors": a["vendors"]}
            for a in accounts.values()
            if len(a["vendors"]) > 1
        ]
    if name == "employee_vendor_conflicts":
        return [
            {"employee": e, "vendor": v, "bank_account": a["bank"]}
            for a in accounts.values()
            for e in a["employees"]
            for v in a["vendors"]
        ]
    vendor_id = str(params.get("vendor_id", ""))
    vendor = next((v for v in world.get("vendors", []) if v["id"] == vendor_id), None)
    if vendor is None:
        return []
    digest = (vendor.get("bank") or {}).get("hash")
    if name == "vendor_bank_shared_with":
        if not digest:
            return []
        a = accounts[digest]
        others = [v for v in a["vendors"] if v["id"] != vendor_id]
        if not others and not a["employees"]:
            return []
        return [{"bank_account": a["bank"], "vendors": others, "employees": a["employees"]}]
    # vendor_neighborhood
    return [
        {
            "vendor": {
                "id": vendor["id"],
                "name": vendor["name"],
                "tax_id": vendor.get("tax_id"),
                "org_id": org_id,
                "created_by": vendor.get("created_by"),
                "created_at": (vendor.get("bank") or {}).get("effective_from"),
            },
            "bank_accounts": [accounts[digest]["bank"]] if digest else [],
            "contracts": [
                {"id": c["id"], "title": c.get("description"), "org_id": org_id}
                for c in world.get("contracts", [])
                if c.get("vendor_id") == vendor_id
            ],
            "purchase_orders": [
                {"id": po["po_number"], "org_id": org_id}
                for po in world.get("purchase_orders", [])
                if po.get("vendor_id") == vendor_id
            ],
            "invoices": [],
        }
    ]


def findings(org_id: str, vendor_id: str) -> list[dict[str, Any]]:
    """The master-data findings `vendor_checks` would raise (bank sharing only)."""
    out: list[dict[str, Any]] = []
    for row in run(org_id, "vendor_bank_shared_with", {"vendor_id": vendor_id}):
        bank = row["bank_account"] or {}
        employees = [e["id"] for e in row["employees"]]
        others = [v["id"] for v in row["vendors"]]
        if employees:
            out.append(
                {
                    "code": "VENDOR_EMPLOYEE_CONFLICT",
                    "severity": "HIGH",
                    "message": f"Bank account ending {bank.get('last4')} is also held by "
                    f"employee(s) {', '.join(employees)}.",
                    "evidence": {"bank_last4": bank.get("last4"), "employees": employees},
                }
            )
        if others:
            out.append(
                {
                    "code": "SHARED_BANK_ACCOUNT",
                    "severity": "HIGH",
                    "message": f"Bank account ending {bank.get('last4')} is shared with "
                    f"vendor(s) {', '.join(others)}.",
                    "evidence": {"bank_last4": bank.get("last4"), "vendors": others},
                }
            )
    return out
