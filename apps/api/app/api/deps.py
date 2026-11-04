"""Shared request dependencies."""

from __future__ import annotations

from fastapi import Request

from app.core.auth import Principal
from app.llm.router import CallContext


def call_context(request: Request, p: Principal, run_id: str | None = None) -> CallContext:
    country = request.headers.get("x-vercel-ip-country")
    return CallContext(org_id=p.org_id, user_id=p.user_id, run_id=run_id, country=country)
