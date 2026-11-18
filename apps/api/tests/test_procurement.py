from __future__ import annotations

import asyncio
import copy
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.auth import Principal, get_principal
from app.core.config import datasets_root
from app.core.db import tenant_tx
from app.core.errors import Conflict, Forbidden
from app.domain.procurement import EvidenceDocument, compare, transition
from app.main import create_app


def document(qty="2", price=5000000):
    return {
        "number": "DOC-1",
        "po_number": "PO-1",
        "currency": "INR",
        "tax_minor": 0,
        "total_minor": int(qty) * price,
        "lines": [
            {"sku": "LAPTOP", "description": "Laptop", "quantity": qty, "unit_price_minor": price}
        ],
    }


def test_receipt_shortfall_and_currency_are_not_approved():
    docs = {"po": document(), "invoice": document(), "receipt": document("1")}
    assert compare(docs)["findings"][0]["code"] == "QUANTITY_SHORTFALL"
    docs["receipt"] = document()
    assert compare(docs)["matched"]
    docs["invoice"]["currency"] = "USD"
    assert not compare(docs)["matched"]


def test_mandatory_order_and_distinct_reviewers():
    state = {
        "status": "awaiting_l1",
        "revision": 3,
        "documents": {k: document() for k in ("po", "invoice", "receipt")},
        "evidence": {"po": {"actor": "buyer"}},
        "approvals": [],
    }
    with pytest.raises(Conflict):
        transition(copy.deepcopy(state), "finance", "finance", frozenset({"finance"}), "checked")
    with pytest.raises(Forbidden):
        transition(copy.deepcopy(state), "l1", "buyer", frozenset({"approver"}), "checked")
    transition(state, "l1", "l1", frozenset({"approver"}), "checked")
    with pytest.raises(Forbidden):
        transition(state, "finance", "l1", frozenset({"finance"}), "checked")
    transition(state, "finance", "finance", frozenset({"finance"}), "checked")
    assert state["status"] == "approved_for_payment"
    assert [a["revision"] for a in state["approvals"]] == [3, 3]


def test_reviewer_correction_preserves_reason_and_reopens_approval():
    state = {
        "status": "awaiting_finance",
        "revision": 3,
        "documents": {k: document() for k in ("po", "invoice", "receipt")},
        "evidence": {"po": {"actor": "buyer"}},
        "approvals": [{"stage": "l1", "actor": "l1", "revision": 3}],
    }
    with pytest.raises(Forbidden):
        transition(copy.deepcopy(state), "reject", "l1", frozenset({"finance"}), "fix receipt")
    transition(state, "reject", "finance", frozenset({"finance"}), "fix receipt")
    assert state["status"] == "needs_correction"
    assert state["approvals"] == []
    assert state["correction"]["comment"] == "fix receipt"


@pytest.mark.db
async def test_case_isolation_approval_edit_and_payment_idempotency(monkeypatch):
    from app.api.v1 import procurement

    org = "proc-" + uuid.uuid4().hex[:10]
    app = create_app()
    principal = Principal("buyer", org, frozenset({"clerk"}), "api_key")

    async def current():
        return principal

    sent: list[tuple[str, uuid.UUID]] = []
    blocker = "Gmail is not configured."

    async def dispatch(org_id, case_id):
        sent.append((org_id, case_id))
        return {"status": "accepted"}

    app.dependency_overrides[get_principal] = current
    monkeypatch.setattr(procurement, "dispatch", dispatch)
    monkeypatch.setattr(procurement, "delivery_blocker", lambda _org: blocker)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/procurement/cases", json={"vendor_id": "acme", "po_number": "PO-1"}
        )
        assert response.status_code == 201, response.text
        cid = response.json()["id"]
        path = f"/api/v1/procurement/cases/{cid}"
        for kind in ("po", "invoice", "receipt"):
            response = await client.put(path + "/documents/" + kind, json=document())
            assert response.status_code == 200, response.text
        summary = (await client.get("/api/v1/procurement/cases?view=summary")).json()["cases"][0]
        assert summary["id"] == cid
        assert summary["status"] == "awaiting_l1"
        assert "state" not in summary
        assert (await client.get(path)).json()["state"]["revision"] == 3
        stale_save = await client.put(path + "/documents/receipt?revision=2", json=document())
        assert stale_save.status_code == 409
        principal = Principal("l1", org, frozenset({"approver"}), "api_key")
        assert (
            await client.post(
                path + "/review", json={"revision": 3, "action": "l1", "comment": "reviewed"}
            )
        ).status_code == 200
        principal = Principal("buyer", org, frozenset({"clerk"}), "api_key")
        revised = await client.put(path + "/documents/receipt", json=document())
        assert revised.json()["approvals"] == []
        assert revised.json()["status"] == "awaiting_l1"
        principal = Principal("l1", org, frozenset({"approver"}), "api_key")
        assert (
            await client.post(
                path + "/review", json={"revision": 3, "action": "l1", "comment": "stale"}
            )
        ).status_code == 409
        await client.post(
            path + "/review", json={"revision": 4, "action": "l1", "comment": "reviewed"}
        )
        principal = Principal("finance", org, frozenset({"finance"}), "api_key")
        approval = await client.post(
            path + "/review", json={"revision": 4, "action": "finance", "comment": "cleared"}
        )
        assert approval.status_code == 200, approval.text
        email_path = path + "/notification/send"
        assert (await client.post(email_path)).status_code == 409
        async with tenant_tx(org) as s:
            await s.execute(
                text(
                    "INSERT INTO ap.procurement_members (org_id,user_id,role,vendor_id) VALUES (:o,'vendor','vendor','acme'),(:o,'other','vendor','other')"
                ),
                {"o": org},
            )
        payment = {
            "revision": 4,
            "reference": "DEMO-123",
            "date": "2026-11-01",
            "amount_minor": 10000000,
        }
        for _ in range(2):
            response = await client.post(path + "/paid", json=payment)
            assert response.status_code == 200, response.text
        assert response.json()["notification"]["status"] == "preview"
        assert (await client.get(path)).json()["email_send_blocker"] == blocker
        assert not sent
        unavailable = await client.post(email_path)
        assert unavailable.status_code == 409
        assert unavailable.json()["error"]["code"] == "gmail_unavailable"
        assert not sent
        blocker = None
        assert (await client.post(email_path)).json()["status"] == "accepted"
        assert sent == [(org, uuid.UUID(cid))]
        async with tenant_tx(org) as s:
            count = (
                await s.execute(
                    text("SELECT count(*) FROM ops.outbox WHERE topic='procurement.payment_email'")
                )
            ).scalar_one()
            assert count == 1
        principal = Principal("other", org, frozenset({"vendor"}), "api_key")
        assert (await client.get("/api/v1/procurement/cases")).json()["cases"] == []
        assert (await client.get(path)).status_code == 404
        assert (await client.put(path + "/documents/invoice", json=document())).status_code == 404
        principal = Principal("vendor", org, frozenset({"vendor"}), "api_key")
        assert len((await client.get("/api/v1/procurement/cases")).json()["cases"]) == 1
        assert (await client.post(path + "/paid", json=payment)).status_code == 403
        assert (await client.post(email_path)).status_code == 403
        principal = Principal("buyer", org, frozenset({"clerk"}), "api_key")
        assert (await client.delete(path + "?revision=4")).status_code == 409
        principal = Principal("buyer", "other-" + org, frozenset({"clerk"}), "api_key")
        assert (await client.put(path + "/documents/po", json=document())).status_code == 404


def test_document_arithmetic_rejects_wrong_total():
    from pydantic import ValidationError

    value = document()
    value["total_minor"] += 1
    with pytest.raises(ValidationError):
        EvidenceDocument.model_validate(value)


@pytest.mark.db
async def test_manual_upload_deduplicates_bytes_and_scopes_confirmation(org_id):
    principal = Principal("buyer", org_id, frozenset({"clerk"}), "api_key")
    app = create_app()

    async def current():
        return principal

    app.dependency_overrides[get_principal] = current
    pdf_path = datasets_root() / "finance_copilot/v1/documents/01-purchase-order-8401.pdf"
    pdf = await asyncio.to_thread(pdf_path.read_bytes)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/procurement/cases", json={"vendor_id": "acme", "po_number": "PO-1"}
        )
        path = f"/api/v1/procurement/cases/{created.json()['id']}"

        async def upload(kind):
            response = await client.post(
                path + "/extract/" + kind,
                files={"file": ("source.pdf", pdf, "application/pdf")},
                data={"synthetic_confirmed": "true", "use_ai": "false"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["draft"] is None
            return response.json()["source_document_id"]

        source_id = await upload("po")
        async with tenant_tx(org_id) as sess:
            await sess.execute(
                text(
                    "INSERT INTO ap.procurement_members (org_id,user_id,role,vendor_id)"
                    " VALUES (:org,'vendor','vendor','acme')"
                ),
                {"org": org_id},
            )
        principal = Principal("vendor", org_id, frozenset({"vendor"}), "api_key")
        evidence = {**document(), "source_document_id": source_id}
        invoice = path + "/documents/invoice"
        assert (await client.put(invoice, json=evidence)).status_code == 403
        assert await upload("invoice") == source_id
        assert (await client.put(invoice, json=evidence)).status_code == 200
        assert (await client.get(invoice + "/file")).content == pdf


@pytest.mark.db
async def test_public_demo_roles_reach_l1_and_finance(monkeypatch):
    """The live demo path: assigned purchasing, vendor, L1 and finance logins, one case."""
    from app.api.v1 import procurement

    org = "proc-demo-" + uuid.uuid4().hex[:10]
    demo_vendor = f"{org}-vendor"
    monkeypatch.setattr(procurement, "PURCHASING_DEMO_ORG", org)
    async with tenant_tx(org) as s:
        await s.execute(
            text(
                "INSERT INTO ap.procurement_members (org_id,user_id,role,vendor_id) VALUES"
                " (:o,'demo-purchasing','purchasing',NULL),(:o,:demo_vendor,'vendor','ACME'),"
                " (:o,'demo-l1','approver',NULL),(:o,'demo-finance','finance',NULL),"
                " (:o,'unrelated-vendor','vendor','OTHER')"
            ),
            {"o": org, "demo_vendor": demo_vendor},
        )
    app = create_app()
    who = {"id": "demo-purchasing"}

    async def current():
        return Principal(who["id"], org, frozenset(), "jwt")

    async def preview(*args):
        return {"status": "preview"}

    app.dependency_overrides[get_principal] = current
    monkeypatch.setattr(procurement, "dispatch", preview)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/api/v1/procurement/cases", json={"vendor_id": "HIppas", "po_number": "PO-1"}
        )
        assert created.status_code == 201, created.text
        path = f"/api/v1/procurement/cases/{created.json()['id']}"
        who["id"] = "unrelated-vendor"
        assert (await client.get(path)).status_code == 404
        who["id"] = demo_vendor
        response = await client.get("/api/v1/procurement/cases?view=summary&include_default=true")
        assert response.json()["cases"][0]["id"] == created.json()["id"]
        assert response.json()["cases"][0]["vendor_id"] == "HIppas"
        assert response.json()["default_case"]["id"] == created.json()["id"]
        assert not response.json()["default_case"]["can_delete"]
        for actor, kind in (
            ("demo-purchasing", "po"),
            (demo_vendor, "invoice"),
            ("demo-purchasing", "receipt"),
        ):
            who["id"] = actor
            response = await client.put(f"{path}/documents/{kind}", json=document())
            assert response.status_code == 200, (actor, kind, response.text)
        assert response.json()["status"] == "awaiting_l1"

        who["id"] = "demo-l1"
        listed = (await client.get("/api/v1/procurement/cases")).json()
        assert listed["roles"] == ["approver"]
        assert listed["cases"][0]["state"]["status"] == "awaiting_l1"
        approved = await client.post(
            path + "/review", json={"revision": 3, "action": "l1", "comment": "L1 ok"}
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "awaiting_finance"

        who["id"] = "demo-finance"
        cleared = await client.post(
            path + "/review", json={"revision": 3, "action": "finance", "comment": "ok"}
        )
        assert cleared.status_code == 200, cleared.text
        paid = await client.post(
            path + "/paid",
            json={
                "revision": 3,
                "reference": "PAY-1",
                "date": "2026-11-01",
                "amount_minor": 10000000,
            },
        )
        assert paid.status_code == 200, paid.text
        assert paid.json()["status"] == "paid"


@pytest.mark.db
async def test_delete_case_requires_creator_or_admin_and_current_revision(org_id):
    principal = Principal("buyer", org_id, frozenset({"purchasing"}), "api_key")
    app = create_app()

    async def current():
        return principal

    app.dependency_overrides[get_principal] = current
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        payload = {"vendor_id": "ACME", "po_number": "PO-1"}
        response = await client.post("/api/v1/procurement/cases", json=payload)
        case_id = response.json()["id"]
        path = f"/api/v1/procurement/cases/{case_id}"
        assert (await client.get(path)).json()["can_delete"]
        principal = Principal("different-buyer", org_id, frozenset({"purchasing"}), "api_key")
        assert not (await client.get(path)).json()["can_delete"]
        assert (await client.delete(path + "?revision=0")).status_code == 403
        principal = Principal("workspace-admin", org_id, frozenset({"admin"}), "api_key")
        assert (await client.delete(path + "?revision=1")).status_code == 409
        assert (await client.delete(path + "?revision=0")).status_code == 204
        assert (await client.get(path)).status_code == 404
        assert (await client.post("/api/v1/procurement/cases", json=payload)).status_code == 201
    async with tenant_tx(org_id) as session:
        action = await session.execute(
            text(
                "SELECT action FROM audit.audit_events WHERE target_id=:id ORDER BY seq DESC LIMIT 1"
            ),
            {"id": case_id},
        )
        assert action.scalar_one() == "procurement.deleted"
