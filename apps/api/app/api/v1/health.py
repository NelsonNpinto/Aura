from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.core.store import get_store

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness. No dependencies."""
    s = get_settings()
    return {"status": "ok", "env": s.app_env, "git_sha": s.git_sha}


async def _check(coro: Any, limit_s: float = 4.0) -> dict[str, Any]:
    try:
        await asyncio.wait_for(coro, limit_s)
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "down", "error": type(exc).__name__}


async def _db() -> None:
    async with get_engine().connect() as c:
        await c.execute(text("SELECT 1"))


async def _redis() -> None:
    if not await get_store().ping():
        raise RuntimeError("ping failed")


@router.get("/ready")
async def ready() -> JSONResponse:
    """Readiness with degrade info. 503 only when Postgres (required) is down."""
    s = get_settings()
    db, redis = await asyncio.gather(_check(_db()), _check(_redis()))
    providers = {
        "groq": "configured" if s.groq_api_key else "not_configured",
        "gemini": "configured" if s.gemini_api_key else "not_configured",
        "bedrock": "enabled" if s.enable_bedrock else "disabled",
    }
    neo4j = {"status": "not_configured" if not s.neo4j_uri else "unchecked_phase0"}
    degraded = [k for k, v in {"redis": redis}.items() if v["status"] != "ok"]
    if not (s.groq_api_key or s.gemini_api_key):
        degraded.append("llm_providers")
    status = "down" if db["status"] != "ok" else ("degraded" if degraded else "ok")
    body = {
        "status": status,
        "checks": {"postgres": db, "redis": redis, "neo4j": neo4j, "providers": providers},
        "degraded": degraded,
        "git_sha": s.git_sha,
    }
    return JSONResponse(body, status_code=503 if status == "down" else 200)
