"""Release gate using a real local Ollama model; no paid evaluator."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.evaluation.deterministic import evaluate
from app.schemas.requests import Check, GenerateRequest
from app.services.ollama import OllamaUnavailable, generate


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--threshold", type=float, default=1)
    parser.add_argument("--max-latency-ms", type=float, default=180000)
    parser.add_argument("--output", type=Path, default=Path("quality-result.json"))
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1 or args.max_latency_ms <= 0:
        parser.error("Invalid score or latency threshold")
    cases = json.loads(args.dataset.read_text())
    if not cases:
        parser.error("Dataset must not be empty")
    results = []
    for case in cases:
        start = time.perf_counter()
        try:
            response = await generate(
                GenerateRequest(
                    model=args.model,
                    prompt=case["question"],
                    system=case.get("system", "Follow the requested output format exactly."),
                    temperature=0,
                    max_tokens=128,
                )
            )
            checks = evaluate(
                response["response"], [Check.model_validate(c) for c in case["checks"]]
            )
            latency = (time.perf_counter() - start) * 1000
            results.append(
                {
                    "id": case["id"],
                    "response": response["response"],
                    "checks": checks,
                    "latency_ms": latency,
                    "passed": all(c["passed"] for c in checks) and latency <= args.max_latency_ms,
                }
            )
        except OllamaUnavailable as exc:
            results.append({"id": case["id"], "passed": False, "error": str(exc)})
    score = sum(r["passed"] for r in results) / len(results)
    report = {"model": args.model, "score": score, "threshold": args.threshold, "results": results}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Quality score: {score:.3f}; required: {args.threshold:.3f}; report: {args.output}")
    return 0 if score >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
