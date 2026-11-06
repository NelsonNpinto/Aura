import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text

from app.core.auth import Principal, get_principal
from app.core.db import tenant_tx
from app.llm.router import CallContext, RouterError
from app.main import create_app
from app.rag import service


@pytest.mark.parametrize("configured", [True, False])
async def test_policy_answer_returns_passages_when_models_are_unavailable(monkeypatch, configured):
    hit = service.Hit(
        "chunk",
        "doc",
        "policy.md",
        "Bank changes",
        "A controller reviews bank changes.",
        None,
        "policy",
        1.0,
        1,
        1,
    )

    async def search(*args, **kwargs):
        assert (kwargs["embedder"] is not None) == configured
        return [hit]

    async def charge_run(_principal):
        assert configured, "Policy search must work after the AI run quota is exhausted"

    class Router:
        config = SimpleNamespace(
            tasks={"rag_answer": SimpleNamespace(chain=["test/model"], variants=[])}
        )

        async def run(self, *args):
            assert configured, "Unconfigured providers must be skipped"
            raise RouterError("All models failed for task rag_answer")

    monkeypatch.setattr(service, "search", search)
    monkeypatch.setattr(service, "charge_run", charge_run)
    monkeypatch.setattr(service, "provider_configured", lambda model: configured)
    monkeypatch.setattr(service, "get_embedder", object)
    monkeypatch.setattr(service, "get_reranker", object)
    result = await service.answer(
        Principal("guest", "demo", frozenset({"guest"}), "api_key"),
        "Who reviews bank changes?",
        router=Router(),
        ctx=CallContext(org_id="demo"),
    )
    assert result.source_only
    assert result.sources == [hit]
    assert result.llm is None
    assert not result.citations["valid"]


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
                    answer="Waiting for L1 [status]"
                    if valid is True
                    else "Waiting for L1"
                    if valid == "plain"
                    else "Paid [invented]",
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
        valid = "plain"
        response = await client.post("/api/v1/procurement/copilot/ask", json=body)
        assert response.json()["citation_valid"] is True
        assert "[status]" in response.json()["answer"]
        valid = False
        response = await client.post("/api/v1/procurement/copilot/ask", json=body)
        assert response.json()["citation_valid"] is False and not response.json()["sources"]
