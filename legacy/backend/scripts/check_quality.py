"""Deterministic release gate: exit nonzero on an inadequate fixture score."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.evaluation.deterministic import evaluate
from app.schemas.requests import Check


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--threshold", type=float, default=float(os.getenv("AURA_MIN_SCORE", "1")))
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        parser.error("Threshold must be 0..1")
    cases = json.loads(args.dataset.read_text())
    if not cases:
        parser.error("Dataset must not be empty")
    results = []
    for case in cases:
        checks = evaluate(case["response"], [Check.model_validate(c) for c in case["checks"]])
        results.append(
            {"id": case["id"], "passed": all(c["passed"] for c in checks), "results": checks}
        )
    score = sum(r["passed"] for r in results) / len(results)
    print(json.dumps({"score": score, "threshold": args.threshold, "cases": results}, indent=2))
    return 0 if score >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
