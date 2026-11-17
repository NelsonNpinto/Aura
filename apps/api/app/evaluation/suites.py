"""Dataset suites for policy QA and copilot trajectories (§B13).

Both run through the normal product path — the same RAG service and the same copilot loop the
web app uses — and are scored with the deterministic checks library. Offline RAGAS-style
metrics (faithfulness, answer relevancy, context precision and recall) are computed from the
retrieved contexts without calling a judge; where a reference is missing the metric is `null`,
not guessed.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.auth import Principal
from app.core.config import datasets_root, get_settings
from app.evaluation.checks import run_checks
from app.llm.router import CallContext, get_router

WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(WORD.findall(text.casefold()))


def load_cases(dataset: str) -> tuple[list[dict[str, Any]], str]:
    path = datasets_root() / dataset / "v1" / "cases.jsonl"
    body = path.read_bytes()
    cases = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    if not all(c.get("synthetic") is True for c in cases):
        raise ValueError(f"{dataset}: every case must be marked synthetic")
    return cases, hashlib.sha256(body).hexdigest()


# ---------------------------------------------------------------- RAGAS-style offline metrics
def faithfulness(answer: str, contexts: list[str]) -> float | None:
    """Share of the answer's content words that appear in the retrieved contexts."""
    answer_tokens = _tokens(answer) - _tokens(" ".join(contexts[:0]))
    if not answer_tokens:
        return None
    context_tokens = _tokens(" ".join(contexts))
    if not context_tokens:
        return None
    supported = len(answer_tokens & context_tokens)
    return round(supported / len(answer_tokens), 4)


def answer_relevancy(answer: str, question: str) -> float | None:
    q, a = _tokens(question), _tokens(answer)
    if not q or not a:
        return None
    return round(len(q & a) / len(q), 4)


def context_precision(contexts: list[str], reference_docs: list[str]) -> float | None:
    if not contexts or not reference_docs:
        return None
    wanted = _tokens(" ".join(reference_docs))
    relevant = sum(1 for c in contexts if _tokens(c) & wanted)
    return round(relevant / len(contexts), 4)


def context_recall(contexts: list[str], reference_docs: list[str]) -> float | None:
    if not reference_docs:
        return None
    joined = _tokens(" ".join(contexts))
    hit = sum(1 for d in reference_docs if _tokens(d) & joined)
    return round(hit / len(reference_docs), 4)


def _mean(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return round(sum(present) / len(present), 4) if present else None


# ---------------------------------------------------------------- policy QA
async def run_policy_qa(
    *, org_id: str = "demo", limit: int = 100, delay: float = 1.5, live: bool = True
) -> dict[str, Any]:
    from app.rag.service import answer as rag_answer

    cases, version = load_cases("policy_qa")
    cases = cases[:limit]
    principal = Principal("system:eval", org_id, frozenset({"auditor"}))
    ctx = CallContext(org_id=org_id, user_id="system:eval", internal_job=True)
    router = get_router()
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    ragas: dict[str, list[float | None]] = {
        "faithfulness": [],
        "answer_relevancy": [],
        "context_precision": [],
        "context_recall": [],
    }

    for index, case in enumerate(cases):
        if index and delay:
            await __import__("asyncio").sleep(delay)
        question = case["input"]["question"]
        try:
            out = await rag_answer(principal, question, router=router, ctx=ctx)
        except Exception as exc:
            results.append(
                {"case_id": case["case_id"], "passed": False, "error": type(exc).__name__}
            )
            continue
        contexts = [h.text for h in out.sources]
        actual = {
            "answer": out.text,
            "sources": [str(i) for i, _ in enumerate(out.sources, start=1)],
        }
        score = run_checks(case.get("checks", []), actual)
        ragas["faithfulness"].append(faithfulness(out.text, contexts))
        ragas["answer_relevancy"].append(answer_relevancy(out.text, question))
        ragas["context_precision"].append(
            context_precision(contexts, case.get("reference_docs", []))
        )
        ragas["context_recall"].append(context_recall(contexts, case.get("reference_docs", [])))
        results.append(
            {
                "case_id": case["case_id"],
                "citation_valid": out.citations.get("valid"),
                "source_only": out.source_only,
                **score.public(),
            }
        )

    return _summary(
        dataset="policy_qa",
        version=version,
        cases=cases,
        results=results,
        started=started,
        live=live,
        extra={k: _mean(v) for k, v in ragas.items()},
    )


# ---------------------------------------------------------------- copilot trajectories
async def run_copilot_tasks(
    *, org_id: str = "demo", limit: int = 100, delay: float = 1.5, live: bool = True
) -> dict[str, Any]:
    from app.agents.copilot.agent import run_copilot

    cases, version = load_cases("copilot_tasks")
    cases = cases[:limit]
    principal = Principal("system:eval", org_id, frozenset({"auditor"}))
    ctx = CallContext(org_id=org_id, user_id="system:eval", internal_job=True)
    results: list[dict[str, Any]] = []
    started = time.monotonic()
    unnecessary = 0

    for index, case in enumerate(cases):
        if index and delay:
            await __import__("asyncio").sleep(delay)
        try:
            out = await run_copilot(principal, case["input"]["question"], ctx)
        except Exception as exc:
            results.append(
                {"case_id": case["case_id"], "passed": False, "error": type(exc).__name__}
            )
            continue
        actual = {
            "answer": out["answer"],
            "sources": [s["id"] for s in out.get("sources", [])],
            "tool_events": out.get("tool_events", []),
        }
        score = run_checks(case.get("checks", []), actual)
        for check in score.results:
            if check.check == "tool_sequence":
                unnecessary += int(check.evidence.get("unnecessary_calls", 0) or 0)
        results.append(
            {
                "case_id": case["case_id"],
                "citation_valid": out.get("citation_valid"),
                "steps": out.get("steps"),
                **score.public(),
            }
        )

    passed = sum(1 for r in results if r.get("passed"))
    return _summary(
        dataset="copilot_tasks",
        version=version,
        cases=cases,
        results=results,
        started=started,
        live=live,
        extra={
            "trajectory_accuracy": round(passed / len(results), 4) if results else None,
            "unnecessary_tool_calls": unnecessary,
        },
    )


def _summary(
    *,
    dataset: str,
    version: str,
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    started: float,
    live: bool,
    extra: dict[str, Any],
) -> dict[str, Any]:
    count = len(results)
    errors = sum(1 for r in results if r.get("error"))
    passed = sum(1 for r in results if r.get("passed"))
    scores: list[float] = [
        float(r["score"]) for r in results if isinstance(r.get("score"), int | float)
    ]
    return {
        "dataset": dataset,
        "dataset_version": version,
        "case_snapshot": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
        "mode": "generate",
        "provider_mode": "live" if live else "fake",
        "created_at": datetime.now(UTC).isoformat(),
        "git_sha": get_settings().git_sha,
        "case_count": count,
        "metrics": {
            "pass_rate": round(passed / count, 4) if count else None,
            "mean_score": round(sum(scores) / len(scores), 4) if scores else None,
            "errors": errors,
            "duration_ms": round((time.monotonic() - started) * 1000),
            **extra,
        },
        "results": results,
        "gate_passed": count > 0 and errors == 0 and passed == count,
        "limits": (
            "Offline RAGAS-style metrics are lexical overlap, not an LLM judge; they are "
            "comparable across runs of this dataset but are not RAGAS reference scores."
        ),
    }


def dataset_path(dataset: str) -> Path:
    return datasets_root() / dataset / "v1" / "cases.jsonl"
