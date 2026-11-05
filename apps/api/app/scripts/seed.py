"""Idempotent base seed: system/demo orgs and v1 of every default prompt (label: production)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import yaml
from sqlalchemy import text

from app.core.auth import DEMO_ORG_ID
from app.core.db import system_tx
from app.prompts.registry import create_version, set_label

DEFAULTS = Path(__file__).resolve().parents[1] / "prompts" / "defaults.yaml"
ORGS = {"system": "AURA system jobs", DEMO_ORG_ID: "AURA public demo (synthetic data)"}


async def seed() -> dict[str, list[str]]:
    created: list[str] = []
    async with system_tx() as s:
        for org_id, name in ORGS.items():
            await s.execute(
                text(
                    "INSERT INTO core.org_settings (org_id, display_name, settings) VALUES (:o,:n,CAST(:st AS jsonb))"
                    " ON CONFLICT (org_id) DO NOTHING"
                ),
                {"o": org_id, "n": name, "st": json.dumps({"synthetic_only": True})},
            )
        prompts = yaml.safe_load(DEFAULTS.read_text())
        for pname, spec in prompts.items():
            current = (
                await s.execute(
                    text(
                        "SELECT p.system, p.template FROM ai.prompt_labels l JOIN ai.prompts p"
                        " ON p.name = l.name AND p.version = l.version"
                        " WHERE l.name=:n AND l.label='production'"
                    ),
                    {"n": pname},
                )
            ).first()
            if current and current.system == spec.get("system", "") and current.template == spec["template"]:
                continue
            # Changed defaults become a NEW immutable version; the label move is audited.
            v = await create_version(
                s,
                name=pname,
                template=spec["template"],
                system=spec.get("system", ""),
                config=spec.get("config", {}),
                created_by="seed",
            )
            await set_label(s, name=pname, label="production", version=v, changed_by="seed")
            created.append(pname)
    return {"created_prompts": created}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(seed())))
