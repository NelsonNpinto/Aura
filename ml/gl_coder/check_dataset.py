"""Leakage, duplication and balance checks for the GL-coder dataset (§B15).

Fails non-zero when:
  * a vendor appears in both the test split and train/val (the test split is vendor-held-out);
  * the same normalised line text appears in more than one split;
  * a split is empty, or the training set has fewer rows than `--min-train`;
  * a label in test never appears in train (the model could not have learned it).

Warnings (not failures) are printed for class imbalance, so the model card can state it.

    python -m ml.gl_coder.check_dataset --path /tmp/gl-coder
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any

SPLITS = ("train", "val", "test")


def load(path: Path, name: str) -> list[dict[str, Any]]:
    file = path / f"{name}.jsonl"
    if not file.exists():
        raise SystemExit(f"missing split: {file}")
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def user_text(row: dict[str, Any]) -> str:
    for m in row["messages"]:
        if m["role"] == "user":
            return str(m["content"])
    return ""


def label(row: dict[str, Any]) -> str:
    for m in row["messages"]:
        if m["role"] == "assistant":
            return str(json.loads(m["content"])["gl_account"])
    return ""


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--min-train", type=int, default=20)
    args = parser.parse_args()
    path = Path(args.path)
    data = {name: load(path, name) for name in SPLITS}

    failures: list[str] = []
    warnings: list[str] = []

    for name, rows in data.items():
        if not rows:
            failures.append(f"{name} split is empty")
    if len(data["train"]) < args.min_train:
        failures.append(f"train has {len(data['train'])} rows, below --min-train {args.min_train}")

    vendors = {name: {r.get("vendor_id") for r in rows} for name, rows in data.items()}
    overlap = vendors["test"] & (vendors["train"] | vendors["val"])
    if overlap:
        failures.append(f"vendor leakage between test and train/val: {sorted(overlap)}")

    texts = {name: {norm(user_text(r)) for r in rows} for name, rows in data.items()}
    for a, b in (("train", "test"), ("train", "val"), ("val", "test")):
        shared = texts[a] & texts[b]
        if shared:
            failures.append(f"{len(shared)} identical line(s) in both {a} and {b}")

    train_labels = {label(r) for r in data["train"]}
    unseen = {label(r) for r in data["test"]} - train_labels
    if unseen:
        failures.append(f"test labels never seen in train: {sorted(unseen)}")

    counts = collections.Counter(label(r) for r in data["train"])
    if counts:
        most, least = counts.most_common(1)[0][1], min(counts.values())
        if most > 5 * max(least, 1):
            warnings.append(f"class imbalance in train: max {most}, min {least}")

    report = {
        "splits": {k: len(v) for k, v in data.items()},
        "vendors": {k: len(v) for k, v in vendors.items()},
        "train_labels": len(train_labels),
        "failures": failures,
        "warnings": warnings,
    }
    print(json.dumps(report, indent=2))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
