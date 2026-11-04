"""Pure-ASGI middleware: request ID, body-size limit, security headers (§B11)."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_var
from app.core.errors import error_body

_RID_OK = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]


class RequestContextMiddleware:
    """Assigns X-Request-ID (accepting a well-formed inbound one) and adds security headers."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        inbound = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = inbound if _RID_OK.match(inbound) else uuid.uuid4().hex
        token = request_id_var.set(rid)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers.append((b"x-request-id", rid.encode()))
                for k, v in SECURITY_HEADERS:
                    if k not in present:
                        headers.append((k, v))
                if self.hsts:
                    headers.append((b"strict-transport-security", b"max-age=63072000"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)


class BodyLimitMiddleware:
    """Rejects bodies above max_bytes with 413, checking Content-Length and streamed size."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, send: Send) -> None:
        body = json.dumps(
            error_body("payload_too_large", f"Request body exceeds {self.max_bytes} bytes")
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > self.max_bytes:
            await self._reject(send)
            return

        seen = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)


class _TooLarge(Exception):
    pass


def client_ip(scope_or_headers: Any, fallback: str | None = None) -> str:
    """Trust only Vercel-provided client IP headers (§B18); never X-Forwarded-For from clients."""
    headers = scope_or_headers
    for name in ("x-vercel-forwarded-for", "x-real-ip"):
        value = headers.get(name)
        if value:
            return str(value).split(",")[0].strip()
    return fallback or "unknown"
