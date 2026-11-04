from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path
from sqlalchemy import text

from app.core.auth import CurrentPrincipal, Principal, require_roles
from app.core.db import tenant_tx
from app.core.errors import NotFound
from app.llm.router import get_router
from app.prompts.registry import DbPromptSource, create_version, fetch_version, set_label
from app.schemas.api import LabelSet, PromptCreate

router = APIRouter(tags=["prompts"])
NAME = Path(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")


@router.get("/prompts")
async def list_prompts(p: CurrentPrincipal) -> list[dict[str, Any]]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            await s.execute(
                text(
                    "SELECT p.name, MAX(p.version) AS latest,"
                    " COALESCE(jsonb_object_agg(l.label, l.version) FILTER (WHERE l.label IS NOT NULL), '{}') AS labels"
                    " FROM ai.prompts p LEFT JOIN ai.prompt_labels l ON l.name = p.name AND l.version = p.version"
                    " GROUP BY p.name ORDER BY p.name"
                )
            )
        ).all()
    return [{"name": r.name, "latest": r.latest, "labels": r.labels} for r in rows]


@router.get("/prompts/{name}")
async def get_prompt(p: CurrentPrincipal, name: str = NAME) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        versions = (
            await s.execute(
                text(
                    "SELECT version, system, template, config, created_by, created_at FROM ai.prompts"
                    " WHERE name = :n ORDER BY version DESC"
                ),
                {"n": name},
            )
        ).all()
        labels = (
            await s.execute(
                text(
                    "SELECT label, version, updated_by, updated_at FROM ai.prompt_labels WHERE name = :n"
                ),
                {"n": name},
            )
        ).all()
    if not versions:
        raise NotFound(f"prompt {name} not found")
    return {
        "name": name,
        "versions": [dict(v._mapping) for v in versions],
        "labels": [dict(lb._mapping) for lb in labels],
    }


@router.post("/prompts/{name}/versions", status_code=201)
async def new_version(
    body: PromptCreate, name: str = NAME, p: Principal = require_roles("admin")
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        v = await create_version(
            s,
            name=name,
            template=body.template,
            system=body.system,
            variables_schema=body.variables_schema,
            config=body.config,
            created_by=p.user_id,
        )
    return {"name": name, "version": v}


@router.put("/prompts/{name}/labels/{label}")
async def put_label(
    body: LabelSet,
    name: str = NAME,
    label: str = Path(pattern=r"^(production|staging|canary)$"),
    p: Principal = require_roles("admin"),
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        await fetch_version(s, name, body.version)
        old = await set_label(s, name=name, label=label, version=body.version, changed_by=p.user_id)
    src = get_router().prompts
    if isinstance(src, DbPromptSource):
        src.invalidate()
    return {"name": name, "label": label, "version": body.version, "previous": old}
