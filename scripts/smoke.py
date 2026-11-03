#!/usr/bin/env python3
"""Exercise AURA over HTTP against its real local services. Writes clearly named smoke records."""

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:5273")
parser.add_argument("--model", default="qwen2.5:0.5b")
parser.add_argument("--ragas", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
config = dict(
    line.split("=", 1)
    for line in (root / ".env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
results = []
stamp = str(int(time.time()))


def call(method, path, data=None, headers=None, raw=None):
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if config.get("API_KEY") and "Authorization" not in request_headers:
        request_headers["Authorization"] = "Bearer " + config["API_KEY"]
    request = urllib.request.Request(
        args.base_url + "/api/v1" + path,
        data=raw
        if raw is not None
        else json.dumps(data).encode()
        if data is not None
        else None,
        headers=request_headers,
        method=method,
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            content = response.read()
            value = json.loads(content) if content else None
            results.append(
                {
                    "method": method,
                    "path": path,
                    "status": response.status,
                    "elapsed_seconds": round(time.perf_counter() - start, 2),
                }
            )
            print(f"{method} {path}: {response.status}", flush=True)
            return value
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:1000]
        results.append(
            {"method": method, "path": path, "status": exc.code, "error": detail}
        )
        raise RuntimeError(f"{method} {path}: {exc.code}: {detail}") from exc


try:
    assert call("GET", "/health")["database_engine"] == "postgresql"
    assert call("GET", "/models")["available"]
    prompt = call(
        "POST",
        "/prompts",
        {
            "name": "Smoke prompt " + stamp,
            "template": "{question}",
            "system": "Follow the requested output format exactly.",
            "configuration": {"model": args.model, "temperature": 0},
        },
    )
    trace = call(
        "POST",
        "/playground/generate",
        {
            "model": args.model,
            "prompt": "What is 19 multiplied by 7? Reply with only the number.",
            "temperature": 0,
            "max_tokens": 32,
        },
    )
    call(
        "POST",
        "/evaluations",
        {
            "name": "Smoke actual model response",
            "trace_id": trace["id"],
            "response": trace["response"],
            "checks": [{"kind": "exact_match", "expected": "133"}],
        },
    )
    dataset = call(
        "POST",
        "/datasets",
        {
            "name": "Smoke dataset " + stamp,
            "description": "Automated integration smoke test: output contract only.",
        },
    )
    call(
        "POST",
        f"/datasets/{dataset['id']}/cases",
        {
            "question": "Reply exactly with AURA_SMOKE_OK",
            "expected": "AURA_SMOKE_OK",
            "response": "AURA_SMOKE_OK",
            "checks": [{"kind": "exact_match", "expected": "AURA_SMOKE_OK"}],
        },
    )
    baseline = call("POST", f"/datasets/{dataset['id']}/run", {"mode": "stored"})
    call(
        "PUT",
        f"/datasets/{dataset['id']}/baseline",
        {"baseline_id": baseline["id"], "min_score": 1, "max_score_drop": 0},
    )
    gate = call("POST", f"/datasets/{dataset['id']}/run", {"mode": "stored"})
    assert gate["gate"]["passed"]
    experiment = call(
        "POST",
        "/experiments",
        {
            "name": "Smoke model contract " + stamp,
            "dataset_id": dataset["id"],
            "configurations": [
                {
                    "mode": "generate",
                    "model": args.model,
                    "prompt_id": prompt["id"],
                    "temperature": 0,
                    "max_tokens": 32,
                },
                {
                    "mode": "generate",
                    "model": args.model,
                    "prompt_id": prompt["id"],
                    "temperature": 0.5,
                    "max_tokens": 32,
                },
            ],
        },
    )
    boundary = "aura-smoke-" + stamp
    text = "AURA integration test policy. Customers can request a refund within 30 days of purchase. Refund requests need a receipt."
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="smoke-policy.txt"\r\nContent-Type: text/plain\r\n\r\n{text}\r\n--{boundary}--\r\n'
    ).encode()
    doc = call(
        "POST",
        "/documents?index=true",
        raw=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
    )
    assert doc["embedding_model"]
    call("GET", f"/documents/{doc['id']}/chunks")
    for strategy in ["bm25", "vector", "hybrid"]:
        sources = call(
            "POST",
            "/knowledge/search",
            {
                "question": "What is the refund window?",
                "strategy": strategy,
                "document_ids": [doc["id"]],
            },
        )
        assert sources
    answer = call(
        "POST",
        "/knowledge/ask",
        {
            "model": args.model,
            "question": "What is the refund window?",
            "strategy": "hybrid",
            "document_ids": [doc["id"]],
            "max_tokens": 96,
        },
    )
    judgment = call(
        "POST",
        "/judge/reviews",
        {
            "model": args.model,
            "question": "What is the refund window?",
            "response": answer["trace"]["response"],
            "expected": "Within 30 days of purchase.",
            "contexts": [text],
        },
    )
    print(
        "Local judge valid:",
        not judgment["error"],
        "score:",
        judgment["score"],
        flush=True,
    )
    call(
        "GET", "/judge/reliability"
    )  # No automated record is misrepresented as a human rating.
    if args.ragas:
        ragas = call(
            "POST",
            "/judge/reviews",
            {
                "model": args.model,
                "question": "What is the refund window?",
                "response": "Within 30 days of purchase.",
                "expected": "Within 30 days of purchase.",
                "contexts": [text],
                "engine": "ragas",
            },
        )
        print("RAGAS metrics:", ragas["verdict"], "error:", ragas["error"], flush=True)
    agent = call(
        "POST",
        "/agents/runs",
        {
            "model": args.model,
            "task": "Calculate 19 * 7 with the calculator, then give only the number.",
            "expected_tools": ["calculator"],
            "checks": [{"kind": "exact_match", "expected": "133"}],
        },
    )
    print("Agent check result:", agent["passed"], flush=True)
    security = call("POST", "/security/runs", {"model": args.model})
    print("Security pack score:", security["score"], flush=True)
    review = call(
        "POST",
        "/marketing/reviews",
        {
            "content": "Aura helps developers evaluate local models.",
            "brand_keywords": ["Aura"],
            "audience_keywords": ["developers"],
            "forbidden_claims": ["guaranteed"],
            "allowed_discounts": [],
        },
    )
    assert review["score"] == 1 and review["decision"] == "pending"
    failure = {
        "event_id": "smoke-event-" + stamp,
        "source": "automated-smoke-test",
        "question": "How long is the refund window?",
        "response": "No refunds",
        "error": "Synthetic policy regression fixture",
        "metadata": {"synthetic_test": True},
    }
    auth = {"Authorization": "Bearer " + config["WEBHOOK_SECRET"]}
    incoming = call("POST", "/webhooks/ai-failure", failure, headers=auth)
    duplicate = call("POST", "/webhooks/ai-failure", failure, headers=auth)
    assert incoming["id"] == duplicate["id"] and duplicate["duplicate"]
    call("GET", "/failures")
    call("GET", "/traces/" + trace["id"])
    call("GET", "/monitoring")
    call("GET", "/overview")
    print(
        "All HTTP smoke steps finished. Model quality results are recorded, not assumed.",
        flush=True,
    )
finally:
    (root / "docs/SMOKE_RESULTS.json").write_text(json.dumps(results, indent=2) + "\n")
