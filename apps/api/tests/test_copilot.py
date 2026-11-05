import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from app.core.auth import Principal, get_principal
from app.core.db import tenant_tx
from app.main import create_app


@pytest.mark.db
async def test_case_copilot_enforces_vendor_scope_and_rejects_invented_citations(
    org_id, monkeypatch
):
    from app.api.v1 import copilot

    cid = uuid.uuid4()
    async with tenant_tx(org_id) as session:
        await session.execute(
            text(
                "INSERT INTO ap.procurement_cases (id,org_id,vendor_id,po_number,state) VALUES (:i,:o,'acme','PO-COPILOT',CAST(:s AS jsonb))"
            ),
            {
                "i": cid,
                "o": org_id,
                "s": json.dumps({"status": "awaiting_l1", "revision": 1, "documents": {}}),
            },
        )
        await session.execute(
            text(
                "INSERT INTO ap.procurement_members (org_id,user_id,role,vendor_id) VALUES (:o,'vendor-acme','vendor','acme'),(:o,'vendor-other','vendor','other')"
            ),
            {"o": org_id},
        )
    valid = True

    class Router:
        async def run(self, *args):
            return SimpleNamespace(
                parsed=copilot.CaseAnswer(
                    answer="Waiting for L1 [status]" if valid else "Paid [invented]",
                    evidence_ids=["status"],
                    needs_more_evidence=False,
                ),
                public=lambda: {"model": "test"},
            )

    monkeypatch.setattr(copilot, "get_router", lambda: Router())
    principal = Principal("vendor-other", org_id, frozenset({"vendor"}), "api_key")
    app = create_app()

    async def current():
        return principal

    app.dependency_overrides[get_principal] = current
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = {"question": "What is the status?", "case_id": str(cid)}
        assert (await client.post("/api/v1/procurement/copilot/ask", json=body)).status_code == 404
        principal = Principal("vendor-acme", org_id, frozenset({"vendor"}), "api_key")
        response = await client.post("/api/v1/procurement/copilot/ask", json=body)
        assert response.json()["citation_valid"] is True
        valid = False
        response = await client.post("/api/v1/procurement/copilot/ask", json=body)
        assert response.json()["citation_valid"] is False and not response.json()["sources"]
