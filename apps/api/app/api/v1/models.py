"""Model registry, canary and promotion (§B15.7).

Lineage is explicit: dataset version → adapter revision → eval metrics → deployment → runs.
A candidate is promoted only by a human, and every promotion and rollback is audited. Metrics
stored here come from an eval run; nothing is written here that was not measured.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.audit.chain import AuditEvent, append
from app.core.auth import CurrentPrincipal, Principal, require_roles
from app.core.config import get_settings
from app.core.db import tenant_tx
from app.core.errors import AppError, NotFound

router = APIRouter(prefix="/models", tags=["models"])


class ModelVersionIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    task: str = Field(min_length=1, max_length=60)
    base_model: str = Field(min_length=1, max_length=120)
    adapter_repo: str = Field(default="", max_length=200)
    adapter_revision: str = Field(default="", max_length=120)
    dataset_version: str = Field(default="", max_length=120)
    metrics: dict[str, Any] = Field(default_factory=dict)


class Promotion(BaseModel):
    status: Literal["candidate", "canary", "production", "retired"]
    canary_percent: int = Field(default=0, ge=0, le=100)
    justification: str = Field(min_length=3, max_length=1000)


@router.get("")
async def list_versions(
    p: CurrentPrincipal, task: str | None = Query(default=None, max_length=60)
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT * FROM ai.model_versions WHERE (CAST(:t AS text) IS NULL OR task = :t)"
                        " ORDER BY created_at DESC LIMIT 100"
                    ),
                    {"t": task},
                )
            )
            .mappings()
            .all()
        )
    s_ = get_settings()
    return {
        "versions": [
            {
                **{
                    k: v
                    for k, v in r.items()
                    if k not in ("id", "created_at", "promoted_at", "org_id")
                },
                "id": str(r["id"]),
                "created_at": r["created_at"].isoformat(),
                "promoted_at": r["promoted_at"].isoformat() if r["promoted_at"] else None,
            }
            for r in rows
        ],
        "serving": {
            "specialist_enabled": s_.enable_specialist,
            "space": s_.specialist_space_id or None,
        },
    }


@router.post("")
async def register(
    body: ModelVersionIn, p: Principal = require_roles("admin", "controller")
) -> dict[str, Any]:
    async with tenant_tx(p.org_id, p.user_id) as s:
        row = (
            (
                await s.execute(
                    text(
                        "INSERT INTO ai.model_versions (org_id, name, task, base_model,"
                        " adapter_repo, adapter_revision, dataset_version, metrics)"
                        " VALUES (:o, :n, :t, :b, :ar, :rev, :dv, CAST(:m AS jsonb))"
                        " ON CONFLICT (org_id, name, adapter_revision) DO UPDATE"
                        "   SET metrics = EXCLUDED.metrics, dataset_version = EXCLUDED.dataset_version"
                        " RETURNING id, status"
                    ),
                    {
                        "o": p.org_id,
                        "n": body.name,
                        "t": body.task,
                        "b": body.base_model,
                        "ar": body.adapter_repo,
                        "rev": body.adapter_revision,
                        "dv": body.dataset_version,
                        "m": _json(body.metrics),
                    },
                )
            )
            .mappings()
            .one()
        )
    return {"id": str(row["id"]), "status": row["status"]}


@router.post("/{version_id}/promote")
async def promote(
    version_id: UUID,
    body: Promotion,
    p: Principal = require_roles("admin", "controller"),
) -> dict[str, Any]:
    """Promote, canary or roll back. Promotion to production requires stored eval metrics."""
    async with tenant_tx(p.org_id, p.user_id) as s:
        current = (
            (
                await s.execute(
                    text("SELECT * FROM ai.model_versions WHERE id = :i"), {"i": str(version_id)}
                )
            )
            .mappings()
            .first()
        )
        if current is None:
            raise NotFound("model version not found")
        if body.status in ("canary", "production") and not current["metrics"]:
            raise AppError(
                "This version has no stored eval metrics; run the gate before promoting it",
                code="no_metrics",
            )
        if body.status == "production":
            await s.execute(
                text(
                    "UPDATE ai.model_versions SET status = 'retired', canary_percent = 0"
                    " WHERE task = :t AND status = 'production' AND id <> :i"
                ),
                {"t": current["task"], "i": str(version_id)},
            )
        await s.execute(
            text(
                "UPDATE ai.model_versions SET status = :st, canary_percent = :cp,"
                " promoted_by = :u, promoted_at = now() WHERE id = :i"
            ),
            {
                "st": body.status,
                "cp": body.canary_percent if body.status == "canary" else 0,
                "u": p.user_id,
                "i": str(version_id),
            },
        )
        await append(
            s,
            p.org_id,
            AuditEvent(
                action="model.promoted",
                actor_type="human",
                actor_id=p.user_id,
                target_type="model_version",
                target_id=str(version_id),
                decision=body.status,
                input={"from": current["status"]},
                output={"to": body.status, "canary_percent": body.canary_percent},
                details={"justification": body.justification},
            ),
        )
    return {
        "id": str(version_id),
        "status": body.status,
        "canary_percent": body.canary_percent if body.status == "canary" else 0,
    }


@router.get("/lineage/{version_id}")
async def lineage(version_id: UUID, p: CurrentPrincipal) -> dict[str, Any]:
    """dataset version → model revision → eval run → deployment → runs that used it."""
    async with tenant_tx(p.org_id, p.user_id) as s:
        mv = (
            (
                await s.execute(
                    text("SELECT * FROM ai.model_versions WHERE id = :i"), {"i": str(version_id)}
                )
            )
            .mappings()
            .first()
        )
        if mv is None:
            raise NotFound("model version not found")
        eval_runs = (
            (
                await s.execute(
                    text(
                        "SELECT id, dataset, dataset_version, metrics, created_at"
                        " FROM ai.dataset_runs WHERE dataset_version = :dv"
                        " ORDER BY created_at DESC LIMIT 10"
                    ),
                    {"dv": mv["dataset_version"]},
                )
            )
            .mappings()
            .all()
        )
        calls = (
            (
                await s.execute(
                    text(
                        "SELECT count(*) AS calls, count(DISTINCT run_id) AS runs"
                        " FROM ai.llm_calls WHERE model LIKE :m"
                    ),
                    {"m": f"specialist/{mv['name']}%"},
                )
            )
            .mappings()
            .one()
        )
    return {
        "model": {
            **{k: v for k, v in mv.items() if k not in ("id", "created_at", "promoted_at")},
            "id": str(mv["id"]),
        },
        "dataset_version": mv["dataset_version"] or None,
        "eval_runs": [
            {**dict(r), "id": str(r["id"]), "created_at": r["created_at"].isoformat()}
            for r in eval_runs
        ],
        "usage": dict(calls),
    }


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)
