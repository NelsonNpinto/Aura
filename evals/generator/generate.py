"""Generate the synthetic AURA world, demo invoices, golden_invoices v1, policy corpus and
gl_coding raw data. Deterministic for a given --seed.

    cd apps/api && uv run python ../../evals/generator/generate.py --out ../../evals/datasets
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from invoices import demo_cases, golden_cases  # noqa: E402
from policies import corpus  # noqa: E402
from render import render_pdf, render_scan_png  # noqa: E402
from world import CATALOGUE, build_world  # noqa: E402


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _write(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha(data)


def _emit_cases(cases, root: Path, seed_base: int) -> list[dict]:
    rows = []
    for i, c in enumerate(cases):
        pdf = render_pdf(c)
        if c.scan:
            data, name, mime = render_scan_png(pdf, seed_base + i), f"{c.case_id}.png", "image/png"
        else:
            data, name, mime = pdf, f"{c.case_id}.pdf", "application/pdf"
        sha = _write(root / "files" / name, data)
        gt = c.ground_truth()
        gt["file"] = {"name": name, "sha256": sha, "mime": mime}
        rows.append(gt)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evals/datasets")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    out = Path(a.out)
    w = build_world(a.seed)
    world = w.to_json()
    (out / "world").mkdir(parents=True, exist_ok=True)
    (out / "world" / "world.json").write_text(json.dumps(world, indent=1))
    # Bank account numbers stay out of world.json (hash + last4 only); the ERP mock seeds the
    # full synthetic numbers from this file so it can compare invoice details by hash.
    (out / "world" / "bank_accounts.json").write_text(json.dumps(
        {v.id: {"account_number": v.bank.account_number, "routing": v.bank.routing} for v in w.vendors}, indent=1))

    demo_rows = _emit_cases(demo_cases(w), out / "demo", 500)
    with (out / "demo" / "cases.jsonl").open("w") as f:
        for r in demo_rows:
            f.write(json.dumps(r) + "\n")

    golden = golden_cases(w)
    rows = _emit_cases(golden, out / "golden_invoices" / "v1", 1000)
    with (out / "golden_invoices" / "v1" / "cases.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    pol_dir = out / "policies"
    pol_dir.mkdir(parents=True, exist_ok=True)
    pol_manifest = []
    for name, (doc_type, md) in corpus(w).items():
        sha = _write(pol_dir / name, md.encode())
        pol_manifest.append({"file": name, "doc_type": doc_type, "sha256": sha})

    gl_rows = []
    for po in w.purchase_orders:
        v = w.vendor(po.vendor_id)
        for ln in po.lines:
            gl_rows.append({"vendor_id": v.id, "vendor_name": v.name, "category": v.category,
                            "description": ln.description, "unit_price_minor": ln.unit_price_minor,
                            "currency": v.currency, "gl_account": ln.gl_account, "cost_center": ln.cost_center})
    (out / "gl_coding").mkdir(parents=True, exist_ok=True)
    with (out / "gl_coding" / "raw.jsonl").open("w") as f:
        for r in gl_rows:
            f.write(json.dumps(r) + "\n")

    manifest = {
        "synthetic": True,
        "generator": "evals/generator",
        "seed": a.seed,
        "files": {},
    }
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "manifest.json" and not p.name.startswith("._"):
            manifest["files"][str(p.relative_to(out))] = _sha(p.read_bytes())
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    counts = {}
    for r in rows:
        counts[r["anomaly"]] = counts.get(r["anomaly"], 0) + 1
    print(json.dumps({"vendors": len(w.vendors), "pos": len(w.purchase_orders), "grns": len(w.goods_receipts),
                      "demo": len(demo_rows), "golden": len(rows), "golden_mix": counts,
                      "policies": len(pol_manifest), "gl_rows": len(gl_rows), "categories": len(CATALOGUE)}))


if __name__ == "__main__":
    main()
