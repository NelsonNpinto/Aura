"""Create documents and runs (shared by the Runs API, the demo seeder and the eval CLI)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from app.core.db import tenant_tx
from app.core.errors import AppError
from app.services.blob import get_blob_store

ALLOWED = {b"%PDF-": "application/pdf", b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg"}


def sniff(data: bytes) -> str:
    for magic, mime in ALLOWED.items():
        if data.startswith(magic):
            return mime
    raise AppError(
        "Only PDF, PNG and JPEG invoices are accepted (checked by magic bytes)",
        code="unsupported_document",
        status_code=415,
    )


async def create_document(
    org_id: str,
    user_id: str,
    filename: str,
    data: bytes,
    *,
    source: str = "upload",
    synthetic: bool = False,
    demo_key: str | None = None,
    guest: bool = False,
) -> dict[str, Any]:
    mime = sniff(data)
    sha = hashlib.sha256(data).hexdigest()
    async with tenant_tx(org_id, user_id) as s:
        row = (
            (
                await s.execute(
                    text(
                        "SELECT id, filename, mime FROM ap.documents WHERE org_id=:o AND sha256=:h"
                    ),
                    {"o": org_id, "h": sha},
                )
            )
            .mappings()
            .first()
        )
    if row:
        return {
            "document_id": str(row["id"]),
            "sha256": sha,
            "mime": row["mime"],
            "duplicate_upload": True,
        }
    key = f"ap/{org_id}/{sha}"
    await get_blob_store().put(key, data, mime)
    did = uuid.uuid4()
    async with tenant_tx(org_id, user_id) as s:
        await s.execute(
            text(
                "INSERT INTO ap.documents (id, org_id, filename, blob_key, sha256, mime, size_bytes, source, synthetic, demo_key, uploaded_by, expires_at)"
                " VALUES (:id,:o,:f,:k,:h,:m,:sz,:src,:syn,:dk,:u,:exp) ON CONFLICT (org_id, sha256) DO NOTHING"
            ),
            {
                "id": did,
                "o": org_id,
                "f": filename[:200],
                "k": key,
                "h": sha,
                "m": mime,
                "sz": len(data),
                "src": source,
                "syn": synthetic,
                "dk": demo_key,
                "u": user_id,
                "exp": datetime.now(UTC) + timedelta(hours=72) if guest else None,
            },
        )
    return {"document_id": str(did), "sha256": sha, "mime": mime, "duplicate_upload": False}


async def create_run(
    org_id: str,
    user_id: str,
    document_id: str,
    *,
    mode: str = "live",
    config: dict[str, Any] | None = None,
    git_sha: str | None = None,
) -> str:
    rid = uuid.uuid4()
    async with tenant_tx(org_id, user_id) as s:
        await s.execute(
            text(
                "INSERT INTO ap.runs (id, org_id, thread_id, document_id, status, mode, started_by, git_sha, config)"
                " VALUES (:id,:o,:t,:d,'queued',:m,:u,:g,CAST(:c AS jsonb))"
            ),
            {
                "id": rid,
                "o": org_id,
                "t": str(rid),
                "d": document_id,
                "m": mode,
                "u": user_id,
                "g": git_sha,
                "c": json.dumps(config or {}),
            },
        )
    return str(rid)
