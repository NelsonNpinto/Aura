"""Build the GL-coder training dataset (§B15).

Sources, in order of trust:
  1. generator ground truth (`evals/datasets/gl_coding/raw.jsonl`) — synthetic, labelled;
  2. human corrections from `ap.feedback` (`--include-feedback`) — the learning loop;
  3. paraphrase augmentation through the router task `paraphrase_data` (`--augment`), which is
     restricted to open-weight models: the Gemini API terms forbid using its output to develop
     competing models (§B18), and `open_weight_only: true` on that task enforces it.

The test split is held out **by vendor**, so a model cannot score well by memorising a vendor's
line text. Duplicates are removed and the splits are leakage-checked by `check_dataset.py`.

    python -m ml.gl_coder.build_dataset --out /tmp/gl-coder [--include-feedback] [--augment]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "evals" / "datasets" / "gl_coding" / "raw.jsonl"
WORLD = REPO / "evals" / "datasets" / "world" / "world.json"
SEED = 20261117
TEST_VENDOR_SHARE = 0.2
VAL_SHARE = 0.1

PROMPT = (
    "Assign a general-ledger account and cost center to this invoice line.\n"
    "Vendor: {vendor}\nLine: {description}\nUnit price (minor units): {unit_price}\n"
    "Currency: {currency}\n"
)


@dataclass(frozen=True)
class Example:
    vendor_id: str
    vendor_name: str
    description: str
    unit_price_minor: int
    currency: str
    gl_account: str
    cost_center: str
    source: str

    @property
    def key(self) -> str:
        norm = re.sub(r"[^a-z0-9]+", " ", self.description.casefold()).strip()
        return f"{self.vendor_id}|{norm}"

    def record(self, chart: str) -> dict[str, Any]:
        return {
            "vendor_id": self.vendor_id,
            "source": self.source,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You assign a general-ledger account and cost center to one invoice "
                        "line. Respond with JSON only. Use codes from the chart of accounts.\n"
                        f"{chart}"
                    ),
                },
                {
                    "role": "user",
                    "content": PROMPT.format(
                        vendor=self.vendor_name,
                        description=self.description,
                        unit_price=self.unit_price_minor,
                        currency=self.currency,
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "gl_account": self.gl_account,
                            "cost_center": self.cost_center,
                            "rationale": f"{self.description} billed by {self.vendor_name}",
                        }
                    ),
                },
            ],
        }


def load_raw() -> list[Example]:
    rows = [json.loads(line) for line in RAW.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [
        Example(
            vendor_id=r["vendor_id"],
            vendor_name=r["vendor_name"],
            description=r["description"],
            unit_price_minor=int(r["unit_price_minor"]),
            currency=r["currency"],
            gl_account=str(r["gl_account"]),
            cost_center=str(r["cost_center"]),
            source="generator",
        )
        for r in rows
    ]


def chart_text() -> str:
    world = json.loads(WORLD.read_text(encoding="utf-8"))
    accounts = "\n".join(
        f"{a['code']} {a['name']}: {a.get('guidance', '')}".strip() for a in world["gl_accounts"]
    )
    centers = ", ".join(f"{c['code']} {c['name']}" for c in world["cost_centers"])
    return f"Chart of accounts:\n{accounts}\nCost centers: {centers}"


async def load_feedback() -> list[Example]:
    """Human GL overrides recorded in the app (§B15 loop step 1)."""
    from sqlalchemy import text

    from app.core.db import system_tx

    out: list[Example] = []
    async with system_tx() as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT f.before, f.after, f.field, i.vendor_id, i.vendor_name,"
                        " i.currency FROM ap.feedback f"
                        " LEFT JOIN ap.invoices i ON i.run_id = f.run_id"
                        " WHERE f.kind = 'gl_override' AND f.after IS NOT NULL"
                    )
                )
            )
            .mappings()
            .all()
        )
    for r in rows:
        after = r["after"] or {}
        if not (after.get("gl_account") and after.get("description")):
            continue
        out.append(
            Example(
                vendor_id=r["vendor_id"] or "UNKNOWN",
                vendor_name=r["vendor_name"] or "Unknown vendor",
                description=str(after["description"]),
                unit_price_minor=int(after.get("unit_price_minor") or 0),
                currency=r["currency"] or "USD",
                gl_account=str(after["gl_account"]),
                cost_center=str(after.get("cost_center") or ""),
                source="human_correction",
            )
        )
    return out


async def augment(examples: list[Example], per_example: int = 1) -> list[Example]:
    """Paraphrase line descriptions with an open-weight model only (§B18 provider terms)."""
    from app.llm.config import load_config
    from app.llm.router import CallContext, get_router

    task = load_config().tasks["paraphrase_data"]
    if not task.open_weight_only:
        raise RuntimeError("paraphrase_data must stay open_weight_only; refusing to augment")
    router = get_router()
    ctx = CallContext(org_id="demo", user_id="system:ml", internal_job=True)
    out: list[Example] = []
    for ex in examples:
        for _ in range(per_example):
            try:
                res = await router.run(
                    "paraphrase_data",
                    {"text": ex.description, "count": "1"},
                    ctx,
                )
            except Exception:
                continue
            text_out = res.text.strip().splitlines()[0].strip(" -\"'")
            if not text_out or text_out.casefold() == ex.description.casefold():
                continue
            out.append(
                Example(
                    vendor_id=ex.vendor_id,
                    vendor_name=ex.vendor_name,
                    description=text_out[:200],
                    unit_price_minor=ex.unit_price_minor,
                    currency=ex.currency,
                    gl_account=ex.gl_account,
                    cost_center=ex.cost_center,
                    source=f"paraphrase:{res.model}",
                )
            )
    return out


def split(examples: list[Example]) -> dict[str, list[Example]]:
    """Hold the test split out by vendor; validation is a random slice of the remainder.

    Vendors are chosen greedily so that every GL account in the test split still appears in
    train. Otherwise the test set would contain labels the model could not have learned, and
    the reported accuracy would understate the model for a reason that has nothing to do with it.
    """
    rng = random.Random(SEED)
    vendors = sorted({e.vendor_id for e in examples})
    rng.shuffle(vendors)
    target = max(1, round(len(vendors) * TEST_VENDOR_SHARE))
    by_vendor: dict[str, list[Example]] = {}
    for e in examples:
        by_vendor.setdefault(e.vendor_id, []).append(e)

    test_vendors: set[str] = set()
    for vendor in vendors:
        if len(test_vendors) >= target:
            break
        candidate = test_vendors | {vendor}
        remaining_labels = {
            e.gl_account for e in examples if e.vendor_id not in candidate
        }
        held_labels = {e.gl_account for e in examples if e.vendor_id in candidate}
        if held_labels <= remaining_labels:
            test_vendors = candidate
    if not test_vendors:  # tiny dataset: fall back to one vendor and say so in the card
        test_vendors = {vendors[0]}
    rest = [e for e in examples if e.vendor_id not in test_vendors]
    rng.shuffle(rest)
    n_val = max(1, round(len(rest) * VAL_SHARE))
    return {
        "test": [e for e in examples if e.vendor_id in test_vendors],
        "val": rest[:n_val],
        "train": rest[n_val:],
    }


def dedupe(examples: list[Example]) -> list[Example]:
    seen: set[str] = set()
    out = []
    for e in examples:
        if e.key in seen:
            continue
        seen.add(e.key)
        out.append(e)
    return out


def write(out_dir: Path, splits: dict[str, list[Example]], chart: str, notes: dict[str, Any]) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    for name, rows in splits.items():
        body = "\n".join(json.dumps(e.record(chart), sort_keys=True) for e in rows) + "\n"
        (out_dir / f"{name}.jsonl").write_text(body, encoding="utf-8")
        digest.update(body.encode())
    version = digest.hexdigest()[:16]
    (out_dir / "VERSION").write_text(version + "\n", encoding="utf-8")
    card = {
        "name": "gl-coder-synthetic",
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "task": "GL account and cost-center assignment for one invoice line",
        "splits": {k: len(v) for k, v in splits.items()},
        "sources": notes.get("sources"),
        "test_split": "held out by vendor",
        "synthetic": True,
        "licence": "CC-BY-4.0 (synthetic data generated for the AURA demo)",
        "caveats": [
            "Every row except human corrections is synthetic; absolute accuracy here does not "
            "transfer to real ledgers.",
            "Augmented rows come only from open-weight models (Gemini output may not be used to "
            "train competing models).",
            "The test split holds out whole vendors, so scores are not inflated by memorised "
            "vendor text.",
        ],
    }
    (out_dir / "dataset_card.json").write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README.md").write_text(_render_card(card), encoding="utf-8")
    return version


def _render_card(card: dict[str, Any]) -> str:
    lines = [
        f"# {card['name']}",
        "",
        f"Version `{card['version']}` — built {card['created_at']}.",
        "",
        f"**Task.** {card['task']}",
        "",
        "## Splits",
        "",
        "| split | rows |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in card["splits"].items()]
    lines += ["", "## Caveats", ""]
    lines += [f"- {c}" for c in card["caveats"]]
    lines += ["", f"Licence: {card['licence']}", ""]
    return "\n".join(lines)


async def _build(args: argparse.Namespace) -> dict[str, Any]:
    examples = load_raw()
    sources = {"generator": len(examples)}
    if args.include_feedback:
        feedback = await load_feedback()
        sources["human_correction"] = len(feedback)
        examples += feedback
    if args.augment:
        extra = await augment(examples[: args.augment_limit])
        sources["paraphrase"] = len(extra)
        examples += extra
    examples = dedupe(examples)
    splits = split(examples)
    version = write(Path(args.out), splits, chart_text(), {"sources": sources})
    return {"version": version, "sources": sources, "splits": {k: len(v) for k, v in splits.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--include-feedback", action="store_true")
    parser.add_argument("--augment", action="store_true")
    parser.add_argument("--augment-limit", type=int, default=40)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(_build(args)), indent=2))


if __name__ == "__main__":
    main()
