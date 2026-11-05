from __future__ import annotations

import copy
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.auth import Principal, get_principal
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


@pytest.mark.db
async def test_case_isolation_approval_edit_and_payment_idempotency(monkeypatch):
    from app.api.v1 import procurement

    org = "proc-" + uuid.uuid4().hex[:10]
    app = create_app()
    principal = Principal("buyer", org, frozenset({"clerk"}), "api_key")

    async def current():
        return principal

    async def preview(*args):
        return {"status": "preview"}

    app.dependency_overrides[get_principal] = current
    monkeypatch.setattr(procurement, "dispatch", preview)
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
        async with tenant_tx(org) as s:
            count = (
                await s.execute(
                    text("SELECT count(*) FROM ops.outbox WHERE topic='procurement.payment_email'")
                )
            ).scalar_one()
            assert count == 1
        principal = Principal("other", org, frozenset({"vendor"}), "api_key")
        assert (await client.get("/api/v1/procurement/cases")).json()["cases"] == []
        assert (await client.put(path + "/documents/invoice", json=document())).status_code == 404
        principal = Principal("vendor", org, frozenset({"vendor"}), "api_key")
        assert len((await client.get("/api/v1/procurement/cases")).json()["cases"]) == 1
        assert (await client.post(path + "/paid", json=payment)).status_code == 403
        principal = Principal("buyer", "other-" + org, frozenset({"clerk"}), "api_key")
        assert (await client.put(path + "/documents/po", json=document())).status_code == 404


def test_document_arithmetic_rejects_wrong_total():
    from pydantic import ValidationError

    value = document()
    value["total_minor"] += 1
    with pytest.raises(ValidationError):
        EvidenceDocument.model_validate(value)
