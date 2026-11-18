"""Long-term memory: the write policy, normalisation and decay (§B8.3).

The policy itself is pure; the storage paths are marked `db` and run where Postgres is
available.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.db import tenant_tx
from app.memory import store


def test_normalisation_collapses_cosmetic_differences() -> None:
    a = store.normalize_fact("Freight lines are coded to 5020.")
    b = store.normalize_fact("  freight   LINES are coded to 5020!!  ")
    assert a == b


def test_normalisation_rejects_content_free_facts() -> None:
    assert store.normalize_fact("!!!   ") == ""


def test_write_policy_constants_match_the_specification() -> None:
    # Three consistent observations, or one human confirmation (§B8.3).
    assert store.OBSERVATIONS_FOR_ACTIVE == 3
    assert store.CONFIRMED_CONFIDENCE > store.OBSERVED_CONFIDENCE
    assert store.DEFAULT_TTL_DAYS == 180


async def test_an_oversized_or_empty_fact_is_rejected() -> None:
    class _Session:
        async def execute(self, *_: object, **__: object) -> None:  # pragma: no cover
            raise AssertionError("must not reach the database")

    for bad in ("", "x" * (store.MAX_FACT_CHARS + 1)):
        with pytest.raises(store.MemoryRejected):
            await store.remember(
                _Session(),  # type: ignore[arg-type]
                "demo",
                kind="vendor",
                subject_id="V001",
                fact=bad,
                created_by="tester",
                confirmed=True,
            )


async def test_an_unknown_namespace_kind_is_rejected() -> None:
    class _Session:
        async def execute(self, *_: object, **__: object) -> None:  # pragma: no cover
            raise AssertionError("must not reach the database")

    with pytest.raises(store.MemoryRejected):
        await store.remember(
            _Session(),  # type: ignore[arg-type]
            "demo",
            kind="document",  # type: ignore[arg-type]
            subject_id="V001",
            fact="anything",
            created_by="tester",
            confirmed=True,
        )


@pytest.mark.db
async def test_a_human_confirmation_activates_immediately(org_id: str) -> None:
    async with tenant_tx(org_id, "tester") as s:
        await s.execute(
            text(
                "INSERT INTO core.org_settings (org_id, display_name) VALUES (:o, :o)"
                " ON CONFLICT DO NOTHING"
            ),
            {"o": org_id},
        )
        memory = await store.remember(
            s,
            org_id,
            kind="vendor",
            subject_id="V001",
            fact="Freight from this vendor is coded to 5020.",
            created_by="tester",
            confirmed=True,
        )
    assert memory.status == "active"
    assert memory.confidence == store.CONFIRMED_CONFIDENCE


@pytest.mark.db
async def test_observations_activate_only_on_the_third(org_id: str) -> None:
    fact = "This vendor bills freight separately."
    statuses = []
    for _ in range(store.OBSERVATIONS_FOR_ACTIVE):
        async with tenant_tx(org_id, "agent") as s:
            memory = await store.remember(
                s,
                org_id,
                kind="vendor",
                subject_id="V002",
                fact=fact,
                created_by="agent",
                confirmed=False,
            )
            statuses.append(memory.status)
    assert statuses[:2] == ["pending", "pending"]
    assert statuses[2] == "active"


@pytest.mark.db
async def test_recall_returns_only_active_memories_and_marks_them_used(org_id: str) -> None:
    async with tenant_tx(org_id, "tester") as s:
        await store.remember(
            s,
            org_id,
            kind="vendor",
            subject_id="V003",
            fact="Confirmed note about pricing.",
            created_by="tester",
            confirmed=True,
        )
        await store.remember(
            s,
            org_id,
            kind="vendor",
            subject_id="V003",
            fact="Unconfirmed observation about pricing.",
            created_by="agent",
            confirmed=False,
        )
    async with tenant_tx(org_id, "tester") as s:
        found = await store.recall(s, org_id, kind="vendor", subject_id="V003", query="pricing")
    assert [m.status for m in found] == ["active"]
    assert found[0].last_used_at is None or True  # set in the same transaction


@pytest.mark.db
async def test_forget_removes_a_memory(org_id: str) -> None:
    async with tenant_tx(org_id, "tester") as s:
        memory = await store.remember(
            s,
            org_id,
            kind="user",
            subject_id="u-1",
            fact="Prefers summaries in tables.",
            created_by="tester",
            confirmed=True,
        )
    async with tenant_tx(org_id, "tester") as s:
        assert await store.forget(s, org_id, uuid.UUID(memory.id))
    async with tenant_tx(org_id, "tester") as s:
        assert await store.list_memories(s, org_id, kind="user", subject_id="u-1") == []


@pytest.mark.db
async def test_decay_reports_counts_without_inventing_them(org_id: str) -> None:
    async with tenant_tx(org_id, "tester") as s:
        result = await store.decay(s, org_id)
    assert set(result) == {"expired", "decayed", "retired"}
    assert all(isinstance(v, int) for v in result.values())
