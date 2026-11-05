"""HTTP-level tests: middleware, auth, limits, playground fallback, knowledge RAG, API keys."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import system_tx
from app.llm import router as router_mod
from app.llm.providers import ProviderError, ProviderRequest, ProviderResponse, Transports
from app.llm.router import ModelRouter
from app.llm.telemetry import DbSink
from app.main import create_app
from app.rag import embeddings
from app.rag.embeddings import HashEmbedder, OverlapReranker


@pytest.fixture
async def client():
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def auth(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


async def test_health_has_request_id_and_security_headers(client):
    r = await client.get("/api/v1/health", headers={"x-request-id": "abc12345-req"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["x-request-id"] == "abc12345-req"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    bad = await client.get("/api/v1/health", headers={"x-request-id": "bad id with spaces"})
    assert bad.headers["x-request-id"] != "bad id with spaces"


async def test_unauthenticated_gets_uniform_error(client):
    r = await client.get("/api/v1/me")
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "unauthorized" and body["request_id"] == r.headers["x-request-id"]


async def test_bad_signature_and_wrong_audience_rejected(client, mint, org_id):
    tok = mint(org_id, ["clerk"], aud="someone-else")
    assert (await client.get("/api/v1/me", headers=auth(tok))).status_code == 401
    assert (await client.get("/api/v1/me", headers=auth(tok[:-4] + "AAAA"))).status_code == 401


async def test_jwt_principal(client, mint, org_id):
    r = await client.get(
        "/api/v1/me", headers=auth(mint(org_id, ["approver", "bogus"], user_id="u-1"))
    )
    assert r.json() == {"user_id": "u-1", "org_id": org_id, "roles": ["approver"], "kind": "jwt"}


async def test_body_limit_413(client, monkeypatch):
    app = create_app()
    app.user_middleware.clear()
    from app.core.middleware import BodyLimitMiddleware

    small = BodyLimitMiddleware(app, max_bytes=10)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=small), base_url="http://t"
    ) as c:
        r = await c.post("/api/v1/playground/run", content=b"x" * 100)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"


@pytest.mark.db
async def test_rate_limit_429_with_retry_after(client, mint, org_id, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 3)
    tok = mint(org_id, ["clerk"])
    codes = [(await client.get("/api/v1/me", headers=auth(tok))).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    r = await client.get("/api/v1/me", headers=auth(tok))
    assert int(r.headers["retry-after"]) >= 1 and r.json()["error"]["code"] == "rate_limited"


class Scripted:
    def __init__(self, script):
        self.script = script

    async def __call__(self, req: ProviderRequest) -> ProviderResponse:
        item = self.script[req.model].pop(0)
        if isinstance(item, Exception):
            raise item
        return ProviderResponse(item, 12, 7, req.model)


@pytest.fixture
def scripted_router(monkeypatch):
    def install(script):
        r = ModelRouter(transports=Transports(default=Scripted(script)), sink=DbSink(), faults="")
        monkeypatch.setattr(router_mod, "_router", r)
        return r

    return install


@pytest.mark.db
async def test_playground_fallback_reason_stored(client, mint, org_id, scripted_router):
    scripted_router(
        {
            "groq/openai/gpt-oss-20b": [ProviderError("rate_limited", "429")],
            "gemini/gemini-3.5-flash-lite": ["hello from gemini"],
        }
    )
    tok = mint(org_id, ["admin"])
    r = await client.post(
        "/api/v1/playground/run",
        json={"task": "playground", "variables": {"input": "hi"}},
        headers=auth(tok) | {"x-vercel-ip-country": "US"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "gemini/gemini-3.5-flash-lite"
    assert body["fallback_reason"] == "groq/openai/gpt-oss-20b:rate_limited"
    async with system_tx() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT model, status, fallback_reason, error_type, prompt_version FROM ai.llm_calls"
                    " WHERE org_id=:o ORDER BY attempt"
                ),
                {"o": org_id},
            )
        ).all()
        trace = (
            await s.execute(
                text("SELECT name, status FROM ai.traces WHERE org_id=:o"), {"o": org_id}
            )
        ).one()
    assert [(r.model, r.status) for r in rows] == [
        ("groq/openai/gpt-oss-20b", "error"),
        ("gemini/gemini-3.5-flash-lite", "ok"),
    ]
    assert rows[1].fallback_reason == "groq/openai/gpt-oss-20b:rate_limited"
    assert rows[0].prompt_version >= 1
    assert trace.name == "playground:playground" and trace.status == "ok"


@pytest.mark.db
async def test_playground_requires_admin(client, mint, org_id):
    r = await client.post(
        "/api/v1/playground/run",
        json={"task": "playground", "variables": {}},
        headers=auth(mint(org_id, ["guest"])),
    )
    assert r.status_code == 403


@pytest.mark.db
async def test_budget_exhaustion_returns_budget_exhausted(
    client, mint, org_id, monkeypatch, scripted_router
):
    scripted_router({"groq/openai/gpt-oss-20b": ["a", "b", "c"]})
    monkeypatch.setattr(get_settings(), "org_daily_runs", 2)
    tok = mint(org_id, ["admin"])
    payload = {"task": "playground", "variables": {"input": "x"}}
    codes = [
        (await client.post("/api/v1/playground/run", json=payload, headers=auth(tok))).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    r = await client.post("/api/v1/playground/run", json=payload, headers=auth(tok))
    assert r.json()["error"]["code"] == "budget_exhausted" and "retry-after" in r.headers


POLICY_MD = b"""# AP Policy Manual

## Approval thresholds
Invoices up to 1,000 USD with no flags are auto-approved. Invoices up to 10,000 USD need an approver.
Invoices above 10,000 USD need a controller.

## Bank detail changes
Any change to a vendor bank account requires controller approval and a documented call-back.

| Amount | Approval |
|---|---|
| <= 1000 | Auto |
| <= 10000 | Approver |
"""


@pytest.mark.db
async def test_knowledge_upload_dedup_search_and_cited_answer(
    client, mint, org_id, monkeypatch, scripted_router
):
    monkeypatch.setattr(embeddings, "get_embedder", lambda: HashEmbedder())
    monkeypatch.setattr(embeddings, "get_reranker", lambda: OverlapReranker())
    import app.api.v1.knowledge as kn

    monkeypatch.setattr(kn, "get_embedder", lambda: HashEmbedder())
    monkeypatch.setattr(kn, "get_reranker", lambda: OverlapReranker())
    tok = mint(org_id, ["clerk"])
    files = {"file": ("ap-policy.md", POLICY_MD, "text/markdown")}
    r1 = await client.post(
        "/api/v1/knowledge/documents", files=files, data={"doc_type": "policy"}, headers=auth(tok)
    )
    assert r1.status_code == 201, r1.text
    r2 = await client.post(
        "/api/v1/knowledge/documents", files=files, data={"doc_type": "policy"}, headers=auth(tok)
    )
    assert r2.json()["duplicate"] is True and r2.json()["document_id"] == r1.json()["document_id"]
    assert r1.json()["chunk_count"] >= 2

    s = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "bank account change call-back"},
        headers=auth(tok),
    )
    hits = s.json()["hits"]
    assert hits and "Bank detail changes" in hits[0]["heading"]
    assert hits[0]["keyword_rank"] is not None and hits[0]["vector_rank"] is not None

    scripted_router(
        {
            "groq/openai/gpt-oss-120b": [
                "Controller approval and a call-back are required [1]. See also [9]."
            ]
        }
    )
    a = await client.post(
        "/api/v1/knowledge/ask",
        json={"question": "What is needed for a bank change?"},
        headers=auth(tok),
    )
    body = a.json()
    assert a.status_code == 200, a.text
    assert body["citations"]["used"] == [1] and body["citations"]["invalid"] == [9]
    assert body["citations"]["valid"] is False

    other = mint(f"other-{uuid.uuid4().hex[:6]}", ["clerk"])
    s2 = await client.post(
        "/api/v1/knowledge/search", json={"query": "bank account change"}, headers=auth(other)
    )
    assert s2.json()["hits"] == []


@pytest.mark.db
async def test_upload_rejects_binaries_and_guests(client, mint, org_id):
    tok = mint(org_id, ["clerk"])
    r = await client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("x.zip", b"PK\x03\x04junk", "application/zip")},
        headers=auth(tok),
    )
    assert r.status_code == 415
    g = await client.post(
        "/api/v1/knowledge/documents",
        files={"file": ("a.md", b"# hi", "text/markdown")},
        headers=auth(mint(org_id, ["guest"])),
    )
    assert g.status_code == 403


@pytest.mark.db
async def test_api_key_lifecycle(client, mint, org_id):
    admin = mint(org_id, ["admin"], user_id="admin-1")
    created = (
        await client.post(
            "/api/v1/api-keys", json={"name": "ci", "roles": ["auditor"]}, headers=auth(admin)
        )
    ).json()
    key = created["key"]
    me = await client.get("/api/v1/me", headers={"x-api-key": key})
    assert me.json() == {
        "user_id": "admin-1",
        "org_id": org_id,
        "roles": ["auditor"],
        "kind": "api_key",
    }
    listed = (await client.get("/api/v1/api-keys", headers=auth(admin))).json()
    assert "key_hash" not in listed[0] and listed[0]["prefix"] == created["prefix"]
    assert (
        await client.delete(f"/api/v1/api-keys/{created['id']}", headers=auth(admin))
    ).status_code == 204
    assert (await client.get("/api/v1/me", headers={"x-api-key": key})).status_code == 401
    assert (
        await client.get("/api/v1/me", headers={"x-api-key": key[:-2] + "zz"})
    ).status_code == 401


def test_pdf_text_strips_nul_bytes():
    from fpdf import FPDF

    from app.services.pdf import extract_text

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, "Invoice number Z7X39XKJ 0003")
    data = bytes(pdf.output()).replace(b"Z7X39XKJ 0003", b"Z7X39XKJ\x000003")
    text = extract_text(data).pages[0]
    assert "\x00" not in text
