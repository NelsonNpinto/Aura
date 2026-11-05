"""Audit lineage (§B12): chain verifies, tampering is detected, concurrent appends never fork,
and the app role cannot update or delete events."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.audit.chain import AuditEvent, append, canonical_json, event_hash, genesis_hash, verify
from app.core.db import system_tx, tenant_tx

pytestmark = pytest.mark.db


def _org() -> str:
    return f"audit-{uuid.uuid4().hex[:8]}"


async def _append(org: str, run: str, action: str, **kw) -> dict:
    async with tenant_tx(org, "u1") as s:
        return await append(
            s, org, AuditEvent(action=action, actor_type="agent", actor_id="test", run_id=run, **kw)
        )


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [1, {"d": 2, "c": 3}]}) == canonical_json(
        {"a": [1, {"c": 3, "d": 2}], "b": 1}
    )


def test_event_hash_changes_with_any_field():
    ev = {"org_id": "o", "seq": 1, "action": "x", "details": {"k": 1}, "prev_hash": "0" * 64}
    base = event_hash("0" * 64, ev)
    assert event_hash("0" * 64, {**ev, "details": {"k": 2}}) != base
    assert event_hash("1" * 64, ev) != base


async def test_chain_verifies_and_links():
    org, run = _org(), str(uuid.uuid4())
    a = await _append(org, run, "node.completed", input={"x": 1}, output={"y": 2})
    b = await _append(org, run, "tool.called", tool="get_vendor")
    assert a["seq"] == 1 and b["seq"] == 2
    assert a["prev_hash"] == genesis_hash(org) and b["prev_hash"] == a["hash"]
    async with tenant_tx(org) as s:
        v = await verify(s, org, run)
        full = await verify(s, org)
    assert v.verified and v.run_event_count == 2
    assert full.verified and full.head_hash == b["hash"]


async def test_tamper_is_detected_with_first_broken_link():
    org, run = _org(), str(uuid.uuid4())
    for i in range(4):
        await _append(org, run, f"step.{i}", details={"i": i})
    # Simulate a database-owner edit: disable the append-only trigger, change seq 3, re-enable.
    async with system_tx() as s:
        await s.execute(text("ALTER TABLE audit.audit_events DISABLE TRIGGER audit_events_append_only"))
        await s.execute(
            text(
                "UPDATE audit.audit_events SET decision = 'approve'"
                " WHERE org_id = :o AND seq = 3"
            ),
            {"o": org},
        )
        await s.execute(text("ALTER TABLE audit.audit_events ENABLE TRIGGER audit_events_append_only"))
    async with tenant_tx(org) as s:
        v = await verify(s, org, run)
    assert not v.verified
    assert v.first_broken == {"seq": 3, "reason": "event content does not match its hash"}


async def test_app_role_cannot_update_or_delete():
    org, run = _org(), str(uuid.uuid4())
    await _append(org, run, "x")
    for stmt in (
        "UPDATE audit.audit_events SET action = 'y' WHERE org_id = :o",
        "DELETE FROM audit.audit_events WHERE org_id = :o",
    ):
        with pytest.raises(DBAPIError):
            async with tenant_tx(org) as s:
                await s.execute(text(stmt), {"o": org})


async def test_owner_role_blocked_by_trigger():
    org, run = _org(), str(uuid.uuid4())
    await _append(org, run, "x")
    with pytest.raises(DBAPIError, match="append-only"):
        async with system_tx() as s:
            await s.execute(text("DELETE FROM audit.audit_events WHERE org_id = :o"), {"o": org})


async def test_concurrent_appends_never_fork():
    org, run = _org(), str(uuid.uuid4())
    rows = await asyncio.gather(*[_append(org, run, f"c{i}") for i in range(25)])
    assert sorted(r["seq"] for r in rows) == list(range(1, 26))
    assert len({r["prev_hash"] for r in rows}) == 25
    async with tenant_tx(org) as s:
        v = await verify(s, org)
    assert v.verified and v.events_checked == 25


async def test_other_org_cannot_see_chain():
    a, b, run = _org(), _org(), str(uuid.uuid4())
    await _append(a, run, "x")
    async with tenant_tx(b) as s:
        n = (await s.execute(text("SELECT count(*) FROM audit.audit_events"))).scalar_one()
        v = await verify(s, b, run)
    assert n == 0 and not v.verified
