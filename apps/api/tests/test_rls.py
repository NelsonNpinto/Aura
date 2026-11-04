"""Tenancy (§B5): RLS blocks cross-org reads, including under concurrency through one pool."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import get_engine, system_tx, tenant_tx

pytestmark = pytest.mark.db


async def _insert_doc(org: str) -> str:
    did = uuid.uuid4()
    async with tenant_tx(org, "u1") as s:
        await s.execute(text(
            "INSERT INTO kb.documents (id, org_id, filename, mime, size_bytes, sha256, blob_key, created_by)"
            " VALUES (:id, :o, 'f.md', 'text/markdown', 1, :h, 'k', 'u1')"),
            {"id": did, "o": org, "h": uuid.uuid4().hex + uuid.uuid4().hex})
    return str(did)


async def _visible(org: str) -> set[str]:
    async with tenant_tx(org) as s:
        rows = (await s.execute(text("SELECT id, org_id FROM kb.documents"))).all()
    assert all(r.org_id == org for r in rows), "RLS leaked another org's row"
    return {str(r.id) for r in rows}


async def test_cross_org_reads_blocked_concurrently():
    a, b = f"rls-a-{uuid.uuid4().hex[:6]}", f"rls-b-{uuid.uuid4().hex[:6]}"
    da, db_ = await _insert_doc(a), await _insert_doc(b)
    results = await asyncio.gather(*[_visible(a if i % 2 else b) for i in range(40)])
    for i, seen in enumerate(results):
        org_doc, other = (da, db_) if i % 2 else (db_, da)
        assert org_doc in seen and other not in seen


async def test_with_check_blocks_writing_into_another_org():
    with pytest.raises(DBAPIError):
        async with tenant_tx("org-x") as s:
            await s.execute(text(
                "INSERT INTO core.org_settings (org_id, display_name) VALUES ('org-y', 'nope')"))


async def test_no_tenant_set_means_no_rows():
    await _insert_doc(f"rls-c-{uuid.uuid4().hex[:6]}")
    async with get_engine().connect() as c, c.begin():
        await c.execute(text("SET LOCAL ROLE aura_app"))
        n = (await c.execute(text("SELECT count(*) FROM kb.documents"))).scalar_one()
    assert n == 0


async def test_org_setting_does_not_leak_to_next_transaction_on_same_connection():
    org = f"rls-d-{uuid.uuid4().hex[:6]}"
    await _insert_doc(org)
    async with get_engine().connect() as c:
        async with c.begin():
            await c.execute(text("SET LOCAL ROLE aura_app"))
            await c.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": org})
            assert (await c.execute(text("SELECT count(*) FROM kb.documents"))).scalar_one() == 1
        async with c.begin():
            await c.execute(text("SET LOCAL ROLE aura_app"))
            assert (await c.execute(text("SELECT count(*) FROM kb.documents"))).scalar_one() == 0


async def test_system_tx_bypasses_rls_for_jobs():
    org = f"rls-e-{uuid.uuid4().hex[:6]}"
    did = await _insert_doc(org)
    async with system_tx() as s:
        assert (await s.execute(text("SELECT 1 FROM kb.documents WHERE id = :i"), {"i": did})).first()
