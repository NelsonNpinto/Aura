import httpx
import pytest
from pydantic import SecretStr

from app.core.config import get_settings
from app.services.payment_email import send

PAYLOAD = {
    "case_id": "case-1",
    "invoice_number": "INV-1",
    "po_number": "PO-1",
    "payment": {"amount_minor": 10000, "date": "2026-11-05", "reference": "DEMO-1"},
}


async def test_preview_never_calls_a_provider(monkeypatch):
    monkeypatch.setattr(get_settings(), "mail_mode", "preview")
    result = await send(PAYLOAD, [])
    assert result["status"] == "preview"
    assert "no funds were transferred" in result["body"]


@pytest.mark.parametrize("mode", ["accepted", "ambiguous", "unauthorized"])
async def test_gmail_transport_and_no_blind_retry(monkeypatch, mode):
    from app.services import payment_email

    settings = get_settings()
    for name, value in {
        "mail_mode": "gmail",
        "mail_from": "sender@example.com",
        "mail_allowed_recipients": "vendor@example.com",
        "gmail_client_id": "test-client",
        "gmail_client_secret": SecretStr("test-secret"),
        "gmail_refresh_token": SecretStr("test-refresh"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                401 if mode == "unauthorized" else 200, json={"access_token": "test-token"}
            )
        if mode == "ambiguous":
            raise httpx.ReadTimeout("unknown send status")
        return httpx.Response(200, json={"id": "gmail-message"})

    client = httpx.AsyncClient
    monkeypatch.setattr(
        payment_email.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await send(PAYLOAD, ["vendor@example.com"])
    assert (
        result["status"]
        == {"accepted": "accepted", "ambiguous": "delivery_unknown", "unauthorized": "failed"}[mode]
    )
    assert len(calls) == (1 if mode == "unauthorized" else 2)
    assert (await send(PAYLOAD, ["unapproved@example.com"]))["error"] == "recipient_not_allowlisted"
