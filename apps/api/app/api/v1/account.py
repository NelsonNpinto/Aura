from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from app.core.auth import CurrentPrincipal, Principal, generate_api_key, require_roles
from app.core.db import tenant_tx
from app.core.errors import NotFound
from app.core.limits import usage_snapshot
from app.core.store import day_bucket, get_store
from app.llm.config import load_config
from app.schemas.api import ApiKeyCreate

router = APIRouter(tags=["account"])


@router.get("/me")
async def me(p: CurrentPrincipal) -> dict[str, Any]:
    return {"user_id": p.user_id, "org_id": p.org_id, "roles": sorted(p.roles), "kind": p.kind}


@router.get("/usage")
async def usage(p: CurrentPrincipal) -> dict[str, Any]:
    snap = await usage_snapshot(p)
    cfg = load_config()
    models = [m for m in cfg.models if not m.startswith(("fake/", "ollama/"))]
    used = await get_store().peek([f"tb:{m}:rpd:{day_bucket()}" for m in models])
    snap["providers"] = {
        m: {"requests_today": u, "rpd_limit": cfg.models[m].rpd}
        for m, u in zip(models, used, strict=True)
    }
    snap["source"] = "redis counters (Upstash)"
    return snap


@router.post("/api-keys", status_code=201)
async def create_api_key(
    body: ApiKeyCreate, p: Principal = require_roles("admin")
) -> dict[str, Any]:
    full, prefix, hashed = generate_api_key()
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = (
            await s.execute(
                text(
                    "INSERT INTO core.api_keys (org_id, user_id, name, prefix, key_hash, roles)"
                    " VALUES (:o,:u,:n,:p,:h,:r) RETURNING id, created_at"
                ),
                {
                    "o": p.org_id,
                    "u": p.user_id,
                    "n": body.name,
                    "p": prefix,
                    "h": hashed,
                    "r": body.roles,
                },
            )
        ).one()
    # The full key is shown exactly once.
    return {"id": str(row.id), "key": full, "prefix": prefix, "roles": body.roles}


@router.get("/api-keys")
async def list_api_keys(p: Principal = require_roles("admin")) -> list[dict[str, Any]]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            await s.execute(
                text(
                    "SELECT id, name, prefix, roles, created_at, last_used_at, revoked_at"
                    " FROM core.api_keys ORDER BY created_at DESC"
                )
            )
        ).all()
    return [dict(r._mapping) | {"id": str(r.id)} for r in rows]


@router.delete("/api-keys/{key_id}", status_code=204)
async def revoke_api_key(key_id: uuid.UUID, p: Principal = require_roles("admin")) -> None:
    async with tenant_tx(p.org_id, p.user_id) as s:
        res = await s.execute(
            text(
                "UPDATE core.api_keys SET revoked_at = now() WHERE id = :id AND revoked_at IS NULL"
            ),
            {"id": key_id},
        )
    if res.rowcount == 0:  # type: ignore[attr-defined]
        raise NotFound("API key not found")
