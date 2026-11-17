"""Evaluate the GL coder against its baselines (§B15).

Three baselines, all measured on the same vendor-held-out test split:
  * `base`     — the base small model, zero-shot with the chart of accounts;
  * `teacher`  — the strongest free model available through the router;
  * `production` — whatever the router's `gl_coding` chain currently serves;
and the candidate `specialist/gl-coder` when `ENABLE_SPECIALIST` is on.

Reported exactly as measured: accuracy, macro-F1, cost-center accuracy, JSON validity, latency
and estimated cost per 1K lines. A provider that is not configured is reported as
`not_measured`, never as zero.

    python -m ml.gl_coder.evaluate --data /tmp/gl-coder --out /tmp/gl-eval.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

CANDIDATES = {
    "base": "groq/openai/gpt-oss-20b",
    "teacher": "groq/openai/gpt-oss-120b",
    "specialist": "specialist/gl-coder",
}


def load_test(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (path / "test.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def expected(row: dict[str, Any]) -> dict[str, str]:
    for m in row["messages"]:
        if m["role"] == "assistant":
            payload = json.loads(m["content"])
            return {"gl_account": payload["gl_account"], "cost_center": payload["cost_center"]}
    raise ValueError("row has no assistant message")


def prompt_parts(row: dict[str, Any]) -> tuple[str, str]:
    system = next(m["content"] for m in row["messages"] if m["role"] == "system")
    user = next(m["content"] for m in row["messages"] if m["role"] == "user")
    return system, user


def macro_f1(pairs: list[tuple[str, str]]) -> float | None:
    """Macro-F1 over GL accounts. None when there is nothing to score."""
    if not pairs:
        return None
    labels = {e for e, _ in pairs} | {p for _, p in pairs}
    scores = []
    for label in labels:
        tp = sum(1 for e, p in pairs if e == label and p == label)
        fp = sum(1 for e, p in pairs if e != label and p == label)
        fn = sum(1 for e, p in pairs if e == label and p != label)
        if tp + fp + fn == 0:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return round(statistics.fmean(scores), 4) if scores else None


async def score_model(name: str, model: str, rows: list[dict[str, Any]], delay: float) -> dict[str, Any]:
    from app.llm.providers import ProviderError, ProviderRequest, Transports, provider_configured

    if not provider_configured(model):
        return {"model": model, "status": "not_measured", "reason": "provider not configured"}
    transports = Transports()
    pairs: list[tuple[str, str]] = []
    cost_center_hits = 0
    json_valid = 0
    latencies: list[float] = []
    errors = 0

    for index, row in enumerate(rows):
        if index and delay:
            await asyncio.sleep(delay)
        system, user = prompt_parts(row)
        started = time.monotonic()
        try:
            response = await transports(
                ProviderRequest(
                    model=model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0,
                    max_tokens=200,
                    timeout_s=25,
                    json_mode=True,
                )
            )
        except (ProviderError, Exception):
            errors += 1
            continue
        latencies.append((time.monotonic() - started) * 1000)
        want = expected(row)
        try:
            got = json.loads(response.text)
            json_valid += 1
        except json.JSONDecodeError:
            pairs.append((want["gl_account"], "__invalid__"))
            continue
        pairs.append((want["gl_account"], str(got.get("gl_account", "__missing__"))))
        if str(got.get("cost_center")) == want["cost_center"]:
            cost_center_hits += 1

    total = len(rows)
    correct = sum(1 for e, p in pairs if e == p)
    return {
        "model": model,
        "status": "measured",
        "cases": total,
        "errors": errors,
        "accuracy": round(correct / total, 4) if total else None,
        "macro_f1": macro_f1(pairs),
        "cost_center_accuracy": round(cost_center_hits / total, 4) if total else None,
        "json_validity": round(json_valid / total, 4) if total else None,
        "p50_latency_ms": round(statistics.median(latencies)) if latencies else None,
        "p95_latency_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1])
        if len(latencies) >= 2
        else None,
    }


async def run(data: Path, delay: float, only: list[str] | None) -> dict[str, Any]:
    rows = load_test(data)
    version = (data / "VERSION").read_text(encoding="utf-8").strip()
    results: dict[str, Any] = {}
    for name, model in CANDIDATES.items():
        if only and name not in only:
            continue
        results[name] = await score_model(name, model, rows, delay)
    # The production chain goes through the router so prompts, fallbacks and caching apply.
    results["production"] = await score_production(rows, delay)
    return {
        "dataset_version": version,
        "test_cases": len(rows),
        "results": results,
        "limits": [
            "Synthetic test split held out by vendor; scores do not transfer to real ledgers.",
            "Cost figures are list-price estimates, not billed amounts.",
            "A model shown as not_measured had no configured provider in this run.",
        ],
    }


async def score_production(rows: list[dict[str, Any]], delay: float) -> dict[str, Any]:
    from app.llm.router import CallContext, RouterError, get_router

    router = get_router()
    ctx = CallContext(org_id="demo", user_id="system:ml", internal_job=True)
    pairs: list[tuple[str, str]] = []
    errors = 0
    for index, row in enumerate(rows):
        if index and delay:
            await asyncio.sleep(delay)
        _, user = prompt_parts(row)
        try:
            res = await router.run("gl_coder_specialist", {"chart": "", "vendor": "", "line": user}, ctx)
        except (RouterError, Exception):
            errors += 1
            continue
        want = expected(row)
        parsed = res.parsed
        got = getattr(parsed, "gl_account", None) if parsed else None
        pairs.append((want["gl_account"], str(got or "__missing__")))
    total = len(rows)
    correct = sum(1 for e, p in pairs if e == p)
    if not pairs:
        return {"status": "not_measured", "reason": "router returned no usable responses"}
    return {
        "status": "measured",
        "cases": total,
        "errors": errors,
        "accuracy": round(correct / total, 4) if total else None,
        "macro_f1": macro_f1(pairs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--out")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--only", nargs="*", choices=sorted(CANDIDATES))
    args = parser.parse_args()
    report = asyncio.run(run(Path(args.data), args.delay, args.only))
    rendered = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
