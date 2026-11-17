"""Graph constraints and indexes (§B8.2). Applied by `python -m app.scripts.graph_sync --schema`.

Every node carries `org_id`; uniqueness is on (org_id, id) so two tenants can hold the same
business identifier without colliding.
"""

from __future__ import annotations

from typing import Any

from app.graph.client import write_many

NODE_LABELS = (
    "Vendor",
    "BankAccount",
    "Employee",
    "PurchaseOrder",
    "POLine",
    "GoodsReceipt",
    "Invoice",
    "InvoiceLine",
    "GLAccount",
    "CostCenter",
    "Contract",
    "User",
    "Decision",
    "Evidence",
)

CONSTRAINTS = tuple(
    f"CREATE CONSTRAINT {label.lower()}_org_key IF NOT EXISTS "
    f"FOR (n:{label}) REQUIRE (n.org_id, n.id) IS UNIQUE"
    for label in NODE_LABELS
)

INDEXES = (
    "CREATE INDEX vendor_org IF NOT EXISTS FOR (n:Vendor) ON (n.org_id)",
    "CREATE INDEX invoice_org_date IF NOT EXISTS FOR (n:Invoice) ON (n.org_id, n.invoice_date)",
    "CREATE INDEX bank_hash IF NOT EXISTS FOR (n:BankAccount) ON (n.org_id, n.account_hash)",
)


async def apply_schema() -> int:
    """Create every constraint and index. Idempotent."""
    statements: list[tuple[str, dict[str, Any]]] = [(c, {}) for c in (*CONSTRAINTS, *INDEXES)]
    return await write_many(statements)
