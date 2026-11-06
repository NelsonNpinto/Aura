"""Bounded Gmail notification outbox. Provider acceptance is not delivery confirmation."""

from __future__ import annotations

import base64
import json
import uuid
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import system_tx, tenant_tx


def payment_message(payload: dict[str, Any]) -> tuple[str, str]:
    invoice_number = str(payload["invoice_number"]).replace("\r", " ").replace("\n", " ")
    subject = f"Payment confirmation for invoice {invoice_number}"
    payment = payload["payment"]
    body = (
        f"Hello,\n\n"
        f"We have recorded payment for invoice {invoice_number}.\n\n"
        f"Purchase order: {payload['po_number']}\n"
        f"Amount: {payment.get('currency', '')} {payment['amount_minor'] // 100}.{payment['amount_minor'] % 100:02d}\n"
        f"Payment date: {payment['date']}\n"
        f"Payment reference: {payment['reference']}\n\n"
        f"Thank you,\nAccounts Payable\n"
    )
    return subject, body


async def send(payload: dict[str, Any], recipients: list[str]) -> dict[str, Any]:
    settings = get_settings()
    subject, body = payment_message(payload)
    if settings.mail_mode == "preview":
        return {
            "status": "preview",
            "subject": subject,
            "body": body,
            "notice": "Sender not enabled; no email sent",
        }
    allowed = {x.strip().lower() for x in settings.mail_allowed_recipients.split(",") if x.strip()}
    if not recipients or any(x.lower() not in allowed for x in recipients):
        return {"status": "failed", "error": "recipient_not_allowlisted"}
    if not all(
        (
            settings.mail_from,
            settings.gmail_client_id,
            settings.gmail_client_secret,
            settings.gmail_refresh_token,
        )
    ):
        return {"status": "failed", "error": "sender_not_configured"}
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            token = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": settings.gmail_client_id,
                    "client_secret": settings.gmail_client_secret.get_secret_value()
                    if settings.gmail_client_secret
                    else "",
                    "refresh_token": settings.gmail_refresh_token.get_secret_value()
                    if settings.gmail_refresh_token
                    else "",
                    "grant_type": "refresh_token",
                },
            )
            token.raise_for_status()
            access = token.json()["access_token"]
        except (httpx.HTTPError, KeyError, ValueError):
            return {"status": "failed", "error": "sender_authorization_failed"}
        message = EmailMessage()
        message["From"] = settings.mail_from
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message["Message-ID"] = f"<procurement-{payload['case_id']}@aura.demo>"
        message.set_content(body)
        try:
            response = await client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {access}"},
                json={"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()},
            )
            if response.status_code >= 500:
                return {"status": "delivery_unknown", "error": "provider_response_ambiguous"}
            if response.status_code >= 400:
                return {"status": "failed", "error": "provider_rejected"}
            return {"status": "accepted", "provider_id": response.json().get("id")}
        except (httpx.HTTPError, ValueError):
            return {"status": "delivery_unknown", "error": "provider_response_ambiguous"}


async def dispatch(org_id: str, case_id: uuid.UUID) -> dict[str, Any]:
    async with tenant_tx(org_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT id,payload FROM ops.outbox WHERE topic='procurement.payment_email' AND payload->>'case_id'=:c AND processed_at IS NULL ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED"
                ),
                {"c": str(case_id)},
            )
        ).first()
        if not row:
            return {"status": "already_processed_or_busy"}
        if row.payload.get("delivery_unknown"):
            return {"status": "delivery_unknown", "notice": "Verify sender mailbox before retrying"}
        payload = row.payload
        event_id = row.id
        # Commit uncertainty before external I/O: a crash cannot trigger an automatic resend.
        await session.execute(
            text("UPDATE ops.outbox SET payload=payload || CAST(:claim AS jsonb) WHERE id=:i"),
            {"claim": json.dumps({"delivery_unknown": True}), "i": event_id},
        )
    async with system_tx() as owner:
        users = (
            await owner.execute(
                text('SELECT email FROM auth."user" WHERE id = ANY(:ids)'),
                {"ids": payload["recipients"]},
            )
        ).all()
    outcome = await send(payload, [u.email for u in users])
    async with tenant_tx(org_id) as session:
        # Lock the case only after sending; paid/edit paths never acquire the outbox lock.
        case = (
            await session.execute(
                text("SELECT state FROM ap.procurement_cases WHERE id=:c FOR UPDATE"),
                {"c": case_id},
            )
        ).first()
        if not case:
            return {"status": "delivery_unknown", "error": "case_unavailable"}
        state = case.state
        state["notification"] = {**state.get("notification", {}), **outcome}
        await session.execute(
            text("UPDATE ap.procurement_cases SET state=CAST(:s AS jsonb) WHERE id=:c"),
            {"s": json.dumps(state), "c": case_id},
        )
        await session.execute(
            text(
                "UPDATE ops.outbox SET attempts=attempts+1, processed_at=CASE WHEN :accepted THEN now() ELSE processed_at END, payload=payload || CAST(:extra AS jsonb) WHERE id=:i"
            ),
            {
                "accepted": outcome["status"] == "accepted",
                "extra": json.dumps({"delivery_unknown": outcome["status"] == "delivery_unknown"}),
                "i": event_id,
            },
        )
        return outcome
