"""Prompt registry (§B13): immutable versions, advisory-locked allocation, audited labels."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import system_tx, tenant_tx
from app.prompts.registry import DbPromptSource, create_version, set_label

pytestmark = pytest.mark.db


def _name() -> str:
    return f"t-{uuid.uuid4().hex[:10]}"


async def test_versions_are_immutable_for_app_role_and_owner():
    name = _name()
    async with tenant_tx("org-p") as s:
        await create_version(s, name=name, template="v1 {{x}}", created_by="u")
    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_tx("org-p") as s:
            await s.execute(text("UPDATE ai.prompts SET template='hacked' WHERE name=:n"), {"n": name})
    with pytest.raises(DBAPIError, match="immutable"):
        async with system_tx() as s:
            await s.execute(text("UPDATE ai.prompts SET template='hacked' WHERE name=:n"), {"n": name})
    with pytest.raises(DBAPIError, match="immutable"):
        async with system_tx() as s:
            await s.execute(text("DELETE FROM ai.prompts WHERE name=:n"), {"n": name})


async def test_concurrent_saves_allocate_distinct_versions():
    name = _name()

    async def save(i: int) -> int:
        async with tenant_tx("org-p") as s:
            return await create_version(s, name=name, template=f"t{i}", created_by="u")

    versions = await asyncio.gather(*[save(i) for i in range(8)])
    assert sorted(versions) == list(range(1, 9))


async def test_labels_move_and_are_audited():
    name = _name()
    async with tenant_tx("org-p") as s:
        v1 = await create_version(s, name=name, template="a", created_by="u")
        v2 = await create_version(s, name=name, template="b", created_by="u")
        await set_label(s, name=name, label="production", version=v1, changed_by="alice")
        old = await set_label(s, name=name, label="production", version=v2, changed_by="bob")
    assert old == v1
    src = DbPromptSource(ttl_s=0)
    assert (await src.resolve(name, "production")).template == "b"
    async with system_tx() as s:
        events = (await s.execute(text(
            "SELECT old_version, new_version, changed_by FROM ai.prompt_label_events WHERE name=:n ORDER BY id"),
            {"n": name})).all()
    assert [(e.old_version, e.new_version, e.changed_by) for e in events] == [(None, 1, "alice"), (1, 2, "bob")]
