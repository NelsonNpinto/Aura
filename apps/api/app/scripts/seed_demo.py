"""Seed the demo org: ERP master data (via erp_mock.seed) and the synthetic policy corpus in kb.
Idempotent (kb dedups by sha256). Never makes LLM calls.

    python -m app.scripts.seed_demo
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.core.auth import DEMO_ORG_ID, Principal
from app.core.config import get_settings
from app.rag.embeddings import get_embedder
from app.rag.service import ingest
from app.services.blob import get_blob_store


async def ingest_policies(org: str) -> list[dict[str, object]]:
    root = Path(get_settings().datasets_dir) / "policies"
    p = Principal(user_id="seed", org_id=org, roles=frozenset({"admin"}))
    done = []
    types = {
        "ap_policy_manual.md": "policy",
        "approval_matrix.md": "approval_matrix",
        "tax_guide.md": "tax_guide",
        "chart_of_accounts_guide.md": "chart_of_accounts",
        "vendor_contracts.md": "contract",
        "faq.md": "faq",
    }
    for f in sorted(root.glob("*.md")):
        if f.name.startswith("._"):
            continue
        r = await ingest(
            p,
            filename=f.name,
            data=f.read_bytes(),
            doc_type=types.get(f.name, "general"),
            version="synthetic-v1",
            effective_from=None,
            effective_to=None,
            max_pages=50,
            blob=get_blob_store(),
            embedder=get_embedder(),
            synthetic=True,
        )
        done.append({"file": f.name, "chunks": r.chunk_count, "duplicate": r.duplicate})
    return done


async def run(orgs: tuple[str, ...] = (DEMO_ORG_ID,)) -> dict[str, object]:
    root = Path(get_settings().datasets_dir)
    out: dict[str, object] = {}
    try:
        from erp_mock.seed import bootstrap, seed
    except ImportError:
        bootstrap = seed = None
    if bootstrap and seed:
        await bootstrap()
        for o in orgs:
            out[f"erp:{o}"] = await seed(o, root / "world")
    for o in orgs:
        out[f"policies:{o}"] = await ingest_policies(o)
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), default=str))
