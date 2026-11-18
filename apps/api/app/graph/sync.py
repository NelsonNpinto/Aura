"""Postgres to Neo4j projection through the transactional outbox (§B8.2).

Writes never call Neo4j inline: the owning transaction appends to `ops.outbox`, and this
consumer applies idempotent MERGEs. A failed batch leaves `processed_at` NULL, so the nightly
reconcile retries it; nothing is lost when AuraDB is paused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_tx
from app.core.logging import get_logger
from app.graph.client import GraphUnavailable, write_many
from app.models.tables import ops_outbox

log = get_logger("graph.sync")

TOPIC_PREFIX = "graph."
MAX_ATTEMPTS = 5


async def enqueue(session: AsyncSession, org_id: str, topic: str, payload: dict[str, Any]) -> None:
    """Append one projection message inside the caller's transaction."""
    await session.execute(
        insert(ops_outbox).values(org_id=org_id, topic=TOPIC_PREFIX + topic, payload=payload)
    )


def _merge_vendor(org: str, p: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = [
        (
            """
            MERGE (v:Vendor {org_id: $org_id, id: $id})
            SET v.name = $name, v.tax_id = $tax_id, v.created_by = $created_by,
                v.created_at = $created_at
            """,
            {
                "org_id": org,
                "id": p["id"],
                "name": p.get("name"),
                "tax_id": p.get("tax_id"),
                "created_by": p.get("created_by"),
                "created_at": p.get("created_at"),
            },
        )
    ]
    for bank in p.get("bank_accounts", []):
        out.append(
            (
                """
                MERGE (b:BankAccount {org_id: $org_id, id: $hash})
                SET b.account_hash = $hash, b.last4 = $last4
                WITH b
                MATCH (v:Vendor {org_id: $org_id, id: $vendor_id})
                MERGE (v)-[:HAS_BANK_ACCOUNT]->(b)
                """,
                {
                    "org_id": org,
                    "hash": bank["account_hash"],
                    "last4": bank.get("last4"),
                    "vendor_id": p["id"],
                },
            )
        )
    for contract in p.get("contracts", []):
        out.append(
            (
                """
                MERGE (c:Contract {org_id: $org_id, id: $id}) SET c.title = $title
                WITH c MATCH (v:Vendor {org_id: $org_id, id: $vendor_id})
                MERGE (v)-[:UNDER_CONTRACT]->(c)
                """,
                {
                    "org_id": org,
                    "id": contract["id"],
                    "title": contract.get("title"),
                    "vendor_id": p["id"],
                },
            )
        )
    return out


def _merge_employee(org: str, p: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = [
        (
            "MERGE (e:Employee {org_id: $org_id, id: $id}) SET e.name = $name",
            {"org_id": org, "id": p["id"], "name": p.get("name")},
        )
    ]
    for bank in p.get("bank_accounts", []):
        out.append(
            (
                """
                MERGE (b:BankAccount {org_id: $org_id, id: $hash})
                SET b.account_hash = $hash, b.last4 = $last4
                WITH b MATCH (e:Employee {org_id: $org_id, id: $employee_id})
                MERGE (e)-[:HAS_BANK_ACCOUNT]->(b)
                """,
                {
                    "org_id": org,
                    "hash": bank["account_hash"],
                    "last4": bank.get("last4"),
                    "employee_id": p["id"],
                },
            )
        )
    return out


def _merge_invoice(org: str, p: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = [
        (
            """
            MERGE (i:Invoice {org_id: $org_id, id: $id})
            SET i.normalized_number = $normalized_number, i.amount_minor = $amount_minor,
                i.currency = $currency, i.invoice_date = $invoice_date, i.route = $route,
                i.status = $status, i.run_id = $run_id
            WITH i
            MATCH (v:Vendor {org_id: $org_id, id: $vendor_id})
            MERGE (i)-[:BILLED_BY]->(v)
            """,
            {
                "org_id": org,
                "id": p["id"],
                "normalized_number": p.get("normalized_number"),
                "amount_minor": p.get("amount_minor"),
                "currency": p.get("currency"),
                "invoice_date": p.get("invoice_date"),
                "route": p.get("route"),
                "status": p.get("status"),
                "run_id": p.get("run_id"),
                "vendor_id": p.get("vendor_id") or "UNKNOWN",
            },
        )
    ]
    if po := p.get("po_number"):
        out.append(
            (
                """
                MERGE (po:PurchaseOrder {org_id: $org_id, id: $po})
                WITH po MATCH (i:Invoice {org_id: $org_id, id: $id})
                MERGE (i)-[:REFERENCES]->(po)
                """,
                {"org_id": org, "po": po, "id": p["id"]},
            )
        )
    for approver in p.get("approved_by", []):
        out.append(
            (
                """
                MERGE (u:User {org_id: $org_id, id: $user_id})
                WITH u MATCH (i:Invoice {org_id: $org_id, id: $id})
                MERGE (i)-[:APPROVED_BY]->(u)
                """,
                {"org_id": org, "user_id": approver, "id": p["id"]},
            )
        )
    return out


def _merge_decision(org: str, p: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out = [
        (
            """
            MERGE (d:Decision {org_id: $org_id, id: $id})
            SET d.action = $action, d.decision = $decision, d.ts = $ts, d.run_id = $run_id
            """,
            {
                "org_id": org,
                "id": p["id"],
                "action": p.get("action"),
                "decision": p.get("decision"),
                "ts": p.get("ts"),
                "run_id": p.get("run_id"),
            },
        )
    ]
    for ev in p.get("evidence", []):
        out.append(
            (
                """
                MERGE (e:Evidence {org_id: $org_id, id: $id}) SET e.kind = $kind, e.ref = $ref
                WITH e MATCH (d:Decision {org_id: $org_id, id: $decision_id})
                MERGE (d)-[:BASED_ON]->(e)
                """,
                {
                    "org_id": org,
                    "id": f"{ev.get('kind')}:{ev.get('ref')}",
                    "kind": ev.get("kind"),
                    "ref": ev.get("ref"),
                    "decision_id": p["id"],
                },
            )
        )
    if invoice_id := p.get("invoice_id"):
        out.append(
            (
                """
                MATCH (d:Decision {org_id: $org_id, id: $id})
                MATCH (i:Invoice {org_id: $org_id, id: $invoice_id})
                MERGE (d)-[:ABOUT]->(i)
                """,
                {"org_id": org, "id": p["id"], "invoice_id": invoice_id},
            )
        )
    return out


PLANNERS = {
    "vendor": _merge_vendor,
    "employee": _merge_employee,
    "invoice": _merge_invoice,
    "decision": _merge_decision,
}


def plan(topic: str, org_id: str, payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Translate one outbox message into idempotent MERGE statements."""
    kind = topic.removeprefix(TOPIC_PREFIX)
    planner = PLANNERS.get(kind)
    if planner is None:
        return []
    return [(" ".join(c.split()), p) for c, p in planner(org_id, payload)]


async def drain(limit: int = 200) -> dict[str, Any]:
    """Apply pending projections. Returns a summary; never raises on an unavailable graph."""
    async with system_tx() as session:
        rows = (
            (
                await session.execute(
                    select(ops_outbox)
                    .where(
                        ops_outbox.c.processed_at.is_(None),
                        ops_outbox.c.attempts < MAX_ATTEMPTS,
                        ops_outbox.c.topic.like(TOPIC_PREFIX + "%"),
                    )
                    .order_by(ops_outbox.c.id)
                    .limit(limit)
                )
            )
            .mappings()
            .all()
        )
    if not rows:
        return {"status": "ok", "pending": 0, "applied": 0}

    statements: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        statements.extend(plan(row["topic"], row["org_id"], dict(row["payload"])))
    ids = [int(r["id"]) for r in rows]
    try:
        await write_many(statements)
    except GraphUnavailable as exc:
        async with system_tx() as session:
            await session.execute(
                update(ops_outbox)
                .where(ops_outbox.c.id.in_(ids))
                .values(attempts=ops_outbox.c.attempts + 1)
            )
        log.warning("graph.sync.deferred", pending=len(ids), reason=str(exc.details.get("reason")))
        return {"status": "unavailable", "pending": len(ids), "applied": 0}

    async with system_tx() as session:
        await session.execute(
            update(ops_outbox)
            .where(ops_outbox.c.id.in_(ids))
            .values(processed_at=datetime.now(UTC))
        )
    return {"status": "ok", "pending": 0, "applied": len(ids), "statements": len(statements)}
