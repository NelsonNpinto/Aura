"""Knowledge graph: the Cypher guard, query templates and the outbox projection (§B8.2).

These run without a Neo4j instance: the guard and the planner are pure functions, and the
availability path is exactly what a missing instance produces.
"""

from __future__ import annotations

import pytest

from app.graph import guard, queries, sync
from app.graph.client import availability


# ---------------------------------------------------------------- guard
@pytest.mark.parametrize(
    "cypher",
    [
        "CREATE (v:Vendor {id: 'x'})",
        "MATCH (n) DETACH DELETE n",
        "MATCH (v:Vendor) SET v.name = 'x' RETURN v",
        "MERGE (v:Vendor {id: 'x'}) RETURN v",
        "MATCH (v:Vendor) REMOVE v.name RETURN v",
        "DROP CONSTRAINT vendor_org_key",
        "LOAD CSV FROM 'http://evil/x.csv' AS row RETURN row",
        "MATCH (v:Vendor) FOREACH (x IN [1] | SET v.n = x) RETURN v",
        "CALL apoc.cypher.runWrite('CREATE (n)') YIELD value RETURN value",
        "CALL db.awaitIndexes() RETURN 1",
    ],
)
def test_guard_rejects_every_write_or_procedure_attempt(cypher: str) -> None:
    with pytest.raises(guard.CypherRejected):
        guard.validate(cypher)


def test_guard_rejects_keyword_hidden_in_a_second_statement() -> None:
    with pytest.raises(guard.CypherRejected):
        guard.validate("MATCH (v:Vendor) RETURN v; CREATE (x:Vendor)")


def test_guard_allows_a_read_and_caps_the_limit() -> None:
    out = guard.validate("MATCH (v:Vendor {org_id: $org_id}) RETURN v")
    assert out.endswith(f"LIMIT {guard.MAX_LIMIT}")


def test_guard_rejects_a_limit_above_the_cap() -> None:
    with pytest.raises(guard.CypherRejected):
        guard.validate("MATCH (v:Vendor) RETURN v LIMIT 5000")


def test_guard_does_not_trip_on_a_keyword_inside_a_string_literal() -> None:
    out = guard.validate("MATCH (v:Vendor) WHERE v.name = 'Create Ltd' RETURN v LIMIT 5")
    assert "Create Ltd" in out


def test_guard_requires_a_read_clause_first() -> None:
    with pytest.raises(guard.CypherRejected):
        guard.validate("RETURNS 1")


def test_free_form_cypher_is_confined_to_the_demo_org() -> None:
    assert guard.free_form_allowed("demo")
    assert not guard.free_form_allowed("acme")


def test_rows_from_another_tenant_are_dropped() -> None:
    rows = [
        {"vendor": {"id": "V1", "org_id": "demo"}},
        {"vendor": {"id": "V2", "org_id": "acme"}},
        {"vendor": {"id": "V3"}},  # no org_id: kept, nothing to contradict
    ]
    kept = guard.drop_foreign_rows(rows, "demo")
    assert [r["vendor"]["id"] for r in kept] == ["V1", "V3"]


def test_nested_foreign_org_is_dropped() -> None:
    rows = [{"vendors": [{"id": "V1", "org_id": "demo"}, {"id": "V2", "org_id": "other"}]}]
    assert guard.drop_foreign_rows(rows, "demo") == []


# ---------------------------------------------------------------- templates
def test_every_template_binds_org_id_as_a_parameter() -> None:
    for name, template in queries.TEMPLATES.items():
        assert "$org_id" in template.cypher, name
        # org_id must never be interpolated into the string
        assert "org_id: '" not in template.cypher, name


def test_resolve_binds_parameters_and_rejects_unknown_templates() -> None:
    cypher, params = queries.resolve("vendor_neighborhood", "demo", {"vendor_id": "V001"})
    assert params == {"vendor_id": "V001", "org_id": "demo"}
    assert "$vendor_id" in cypher
    with pytest.raises(queries.UnknownTemplate):
        queries.resolve("definitely_not_a_template", "demo", {})


def test_resolve_requires_every_declared_parameter() -> None:
    with pytest.raises(queries.UnknownTemplate):
        queries.resolve("vendor_neighborhood", "demo", {})


def test_catalog_lists_templates_for_the_copilot() -> None:
    names = {t["name"] for t in queries.catalog()}
    assert {"vendor_neighborhood", "shared_bank_accounts", "split_invoices"} <= names


# ---------------------------------------------------------------- projection
def test_invoice_projection_merges_vendor_and_approvers() -> None:
    statements = sync.plan(
        "graph.invoice",
        "demo",
        {
            "id": "inv-1",
            "vendor_id": "V001",
            "amount_minor": 125000,
            "currency": "USD",
            "po_number": "PO-1001",
            "approved_by": ["u-7"],
        },
    )
    assert len(statements) == 3  # invoice + PO reference + approver
    assert all(params.get("org_id") == "demo" for _, params in statements)
    assert any("APPROVED_BY" in cypher for cypher, _ in statements)


def test_vendor_projection_includes_bank_accounts() -> None:
    statements = sync.plan(
        "graph.vendor",
        "demo",
        {
            "id": "V001",
            "name": "Acme",
            "bank_accounts": [{"account_hash": "a" * 64, "last4": "1234"}],
        },
    )
    assert any("HAS_BANK_ACCOUNT" in cypher for cypher, _ in statements)


def test_unknown_topic_plans_nothing() -> None:
    assert sync.plan("graph.unknown", "demo", {"id": "x"}) == []


# ---------------------------------------------------------------- availability
def test_availability_reports_a_reason_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("NEO4J_URI", "")
    monkeypatch.setenv("NEO4J_USERNAME", "")
    monkeypatch.setenv("NEO4J_PASSWORD", "")
    get_settings.cache_clear()
    usable, reason = availability()
    assert not usable
    assert reason in ("not_configured", "driver_not_installed")
    get_settings.cache_clear()


@pytest.fixture
def graph_offline(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import get_settings

    for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.setenv(k, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_explorer_serves_static_snapshot_for_demo_when_graph_is_offline(
    graph_offline,
) -> None:
    from app.core.auth import DEMO_ORG_ID
    from app.graph import service

    overview = await service.org_fraud_overview(DEMO_ORG_ID)
    assert overview["status"] == "static"
    shared = overview["patterns"]["shared_bank_accounts"]
    assert any({v["id"] for v in row["vendors"]} == {"V017", "V018"} for row in shared)

    hood = await service.neighborhood(DEMO_ORG_ID, "V017")
    assert hood["status"] == "static" and hood["vendor"]["vendor"]["id"] == "V017"
    assert any(f["code"] == "SHARED_BANK_ACCOUNT" for f in hood["findings"])

    rows = await service.explore_template(DEMO_ORG_ID, "shared_bank_accounts")
    assert rows["status"] == "static" and rows["rows"]


async def test_static_snapshot_never_covers_invoice_patterns_or_other_tenants(
    graph_offline,
) -> None:
    from app.core.auth import DEMO_ORG_ID
    from app.graph import service

    split = await service.explore_template(
        DEMO_ORG_ID,
        "split_invoices",
        {"vendor_id": "V001", "since": "2026-01-01", "limit_minor": 1},
    )
    assert split["status"] == "unavailable" and split["rows"] == []
    other = await service.org_fraud_overview("acme-real-tenant")
    assert other["status"] == "unavailable"
    # The invoice workflow still fails closed.
    checks = await service.vendor_checks(DEMO_ORG_ID, "V017")
    assert checks.status == "unavailable"
