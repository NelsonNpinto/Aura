"""Phase 1 acceptance (fake provider mode, in-process ERP over the gateway):
five demo outcomes, approval resume, server-side SoD, call-back, single decision under a race,
idempotent replay of a resume, audit chain verification."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parents[3] / "evals" / "datasets"
CASES = {
    json.loads(line)["demo_key"]: json.loads(line)
    for line in (ROOT / "demo" / "cases.jsonl").read_text().splitlines()
}


@pytest.fixture(scope="module", autouse=True)
def _env():
    os.environ["ERP_SERVICE_TOKEN"] = "test-erp"
    os.environ["APPROVAL_TOKEN_SECRET"] = "test-approval-secret"
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def org():
    o = f"wf-{uuid.uuid4().hex[:8]}"
    from erp_mock.seed import bootstrap, seed

    async def go():
        await bootstrap()
        await seed(o, ROOT / "world")

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        go()
    ) if False else asyncio.run(go())
    return o


async def _run(org: str, key: str, user: str = "persona:rahul"):
    from app.agents.invoice_to_pay.runner import execute
    from app.services.runs import create_document, create_run

    c = CASES[key]
    data = (ROOT / "demo" / "files" / c["file"]["name"]).read_bytes()
    doc = await create_document(org, user, c["file"]["name"], data, synthetic=True, demo_key=key)
    rid = await create_run(org, user, doc["document_id"], mode="fake")
    res = await execute(rid, org, user, document_id=doc["document_id"], fake=True)
    return rid, res


@pytest.mark.parametrize("key", list("abcde"))
async def test_demo_invoice_outcomes(org, key):
    _, res = await _run(org, key)
    exp = CASES[key]["expected"]
    assert (res["status"], res["route"]) == (exp["status"], exp["route"])


async def test_demo_runs_repeat_identically(org):
    a1 = await _run(org, "a")
    a2 = await _run(org, "a")
    assert a1[1] == a2[1] == {"status": "posted", "route": "auto"}


def _actor(key: str):
    from app.services.approvals import PERSONAS, Actor

    p = PERSONAS[key]
    return Actor(p["id"], p["roles"], p["name"], p["limit_minor"])


async def test_bank_change_needs_controller_callback_and_sod(org):
    from app.core.errors import AppError, Forbidden
    from app.services.approvals import decide

    rid, res = await _run(org, "c")
    assert res["status"] == "awaiting_approval"
    # preparer cannot approve own invoice (and is not a controller)
    with pytest.raises(Forbidden) as e:
        await decide(
            org,
            rid,
            _actor("rahul"),
            decision="approve",
            comment="ok",
            callback_verified=True,
            packet_hash=None,
        )
    assert {v["code"] for v in e.value.details["violations"]} >= {"SOD_PREPARER"}
    # approver role is not enough for a HIGH flag
    with pytest.raises(Forbidden):
        await decide(
            org,
            rid,
            _actor("priya"),
            decision="approve",
            comment="ok",
            callback_verified=True,
            packet_hash=None,
        )
    # controller must document the call-back
    with pytest.raises(AppError, match="call-back"):
        await decide(
            org,
            rid,
            _actor("meera"),
            decision="approve",
            comment="called vendor",
            callback_verified=False,
            packet_hash=None,
        )


async def test_approval_resume_posts_once_and_replay_is_idempotent(org):
    from app.agents.invoice_to_pay.runner import execute
    from app.core.db import tenant_tx
    from app.services.approvals import decide

    rid, _ = await _run(org, "c")
    out = await decide(
        org,
        rid,
        _actor("meera"),
        decision="approve",
        comment="Called vendor on file number",
        callback_verified=True,
        packet_hash=None,
    )
    resume = {
        k: out[k] for k in ("decision", "approver_id", "comment", "callback_verified", "step")
    }
    res = await execute(
        rid, org, "persona:meera", resume=resume, approval_token=out["token"], fake=True
    )
    assert res == {"status": "posted", "route": "approval"}
    # replaying the same resume does not double-post
    await execute(rid, org, "persona:meera", resume=resume, approval_token=out["token"], fake=True)
    from app.core.db import system_tx

    async with tenant_tx(org) as s:
        n = (
            await s.execute(text("SELECT count(*) FROM ap.postings WHERE run_id=:r"), {"r": rid})
        ).scalar_one()
    async with system_tx() as s:  # the app role cannot read schema erp (data boundary, §B5)
        erp_n = (
            await s.execute(
                text("SELECT count(*) FROM erp.payments WHERE org_id=:o AND idempotency_key=:k"),
                {"o": org, "k": f"{rid}:pay"},
            )
        ).scalar_one()
    assert n == 1 and erp_n == 1


async def test_two_simultaneous_approvals_one_decision(org):
    from app.core.errors import AppError
    from app.services.approvals import decide

    rid, _ = await _run(org, "e")  # scan → approver level
    results = await asyncio.gather(
        decide(
            org,
            rid,
            _actor("priya"),
            decision="approve",
            comment="looks right",
            callback_verified=False,
            packet_hash=None,
        ),
        decide(
            org,
            rid,
            _actor("meera"),
            decision="approve",
            comment="looks right",
            callback_verified=False,
            packet_hash=None,
        ),
        return_exceptions=True,
    )
    ok = [r for r in results if isinstance(r, dict)]
    errs = [r for r in results if isinstance(r, AppError)]
    assert len(ok) == 1 and len(errs) == 1 and errs[0].code == "already_decided"


async def test_payment_without_token_refused_by_gateway(org):
    from app.tools.gateway import ToolContext, ToolDenied, call_tool

    ctx = ToolContext(
        org_id=org,
        actor_id="t",
        roles=frozenset({"system"}),
        agent="invoice_to_pay",
        route="approval",
    )
    with pytest.raises(ToolDenied):
        await call_tool(
            "schedule_payment",
            {
                "idempotency_key": "x",
                "erp_ref": "AP-1",
                "amount_minor": 100,
                "currency": "USD",
                "due_date": "2026-12-01",
                "route": "approval",
            },
            ctx,
        )


async def test_gateway_rejects_wrong_agent_and_bad_args(org):
    from app.tools.gateway import ToolContext, ToolDenied, call_tool

    ctx = ToolContext(org_id=org, actor_id="t", roles=frozenset({"guest"}), agent="copilot")
    with pytest.raises(ToolDenied, match="may not call"):
        await call_tool(
            "post_invoice",
            {
                "idempotency_key": "x",
                "invoice_number": "1",
                "amount_minor": 1,
                "currency": "USD",
                "route": "auto",
            },
            ctx,
        )
    with pytest.raises(ToolDenied, match="Invalid arguments"):
        await call_tool("get_vendor", {"vendor_id": "bad id!"}, ctx)


async def test_audit_chain_verifies_for_demo_runs(org):
    from app.audit.chain import verify
    from app.core.db import tenant_tx

    rid, _ = await _run(org, "a")
    async with tenant_tx(org) as s:
        v = await verify(s, org, rid)
    assert v.verified and v.run_event_count and v.run_event_count >= 10


async def test_duplicate_upload_restores_a_missing_blob(org):
    """A row that outlived its blob must not hand back a document intake cannot read."""
    from app.services.blob import get_blob_store
    from app.services.runs import create_document

    data = (ROOT / "demo" / "files" / CASES["a"]["file"]["name"]).read_bytes()
    first = await create_document(org, "persona:rahul", "a.pdf", data, synthetic=True)
    key = f"ap/{org}/{first['sha256']}"
    store = get_blob_store()
    await store.delete(key)
    with pytest.raises(FileNotFoundError):
        await store.get(key)

    again = await create_document(org, "persona:rahul", "a.pdf", data, synthetic=True)
    assert again["duplicate_upload"] is True
    assert again["document_id"] == first["document_id"]
    assert await store.get(key) == data


async def test_optional_filters_bind_as_typed_nulls(org):
    """`(:x IS NULL OR col = :x)` with a None parameter is ambiguous to Postgres under psycopg;
    every optional filter must cast its parameter so an unfiltered call works."""
    from app.agents.copilot import tools
    from app.api.v1.guardrails import events
    from app.api.v1.models import list_versions
    from app.core.auth import Principal

    await _run(org, "a")
    listed = await tools._list_invoices(org, {})
    assert listed["invoices"]
    spend = await tools._sql_query(org, {"template": "spend_by_vendor", "params": {}})
    assert spend["template"] == "spend_by_vendor"
    p = Principal(user_id="persona:meera", org_id=org, roles=frozenset({"admin"}))
    assert "versions" in await list_versions(p, task=None)
    assert "events" in await events(p, surface=None, verdict=None, limit=10)
