"""Deterministic checks library (§B13).

Every check takes the case's `expected` block and the actual output and returns a Result. No
model is involved, so these are reproducible and cheap: they are what the PR-tier gate runs.
A case score is the equal-weight fraction of passed checks unless weights are configured.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

JSON_FENCE = re.compile(r"^\s*```(?:json)?|```\s*$", re.M)
NON_FINITE = re.compile(r"\b(NaN|Infinity|-Infinity)\b")


@dataclass(frozen=True)
class Result:
    check: str
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return asdict(self)


def _text(actual: Any) -> str:
    if isinstance(actual, str):
        return actual
    if isinstance(actual, dict):
        for key in ("answer", "text", "output", "content"):
            value = actual.get(key)
            if isinstance(value, str):
                return value
    return json.dumps(actual, default=str)


def _normalize(value: Any) -> str:
    folded: str = re.sub(r"\s+", " ", str(value)).strip().casefold()
    return folded


# ---------------------------------------------------------------- individual checks
def non_empty(expected: Any, actual: Any) -> Result:
    body = _text(actual).strip()
    return Result("non_empty", bool(body), "" if body else "empty response")


def valid_json(expected: Any, actual: Any) -> Result:
    body = _text(actual).strip()
    if JSON_FENCE.search(body):
        return Result("valid_json", False, "response is fenced, not raw JSON")
    if NON_FINITE.search(body):
        return Result("valid_json", False, "NaN/Infinity is not valid JSON")
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        return Result("valid_json", False, f"invalid JSON: {exc.msg}")
    return Result("valid_json", True)


def json_schema(expected: Any, actual: Any) -> Result:
    from jsonschema import Draft202012Validator

    schema = expected if isinstance(expected, dict) else {}
    if any("$ref" in json.dumps(v) and "http" in json.dumps(v) for v in [schema]):
        return Result("json_schema", False, "remote $ref is not allowed")
    body = _text(actual).strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return Result("json_schema", False, "response is not JSON")
    errors = sorted(Draft202012Validator(schema).iter_errors(parsed), key=str)
    if errors:
        return Result("json_schema", False, errors[0].message[:200])
    return Result("json_schema", True)


def required_keywords(expected: Any, actual: Any) -> Result:
    body = _text(actual).casefold()
    missing = [k for k in (expected or []) if str(k).casefold() not in body]
    return Result(
        "required_keywords",
        not missing,
        f"missing: {', '.join(missing)}" if missing else "",
        {"missing": missing},
    )


def forbidden_phrases(expected: Any, actual: Any) -> Result:
    body = _text(actual).casefold()
    present = [k for k in (expected or []) if str(k).casefold() in body]
    return Result(
        "forbidden_phrases",
        not present,
        f"present: {', '.join(present)}" if present else "",
        {"present": present},
    )


def exact_match(expected: Any, actual: Any) -> Result:
    ok = _normalize(expected) == _normalize(_text(actual))
    return Result("exact_match", ok, "" if ok else "values differ")


def numeric_tolerance(expected: Any, actual: Any) -> Result:
    """expected: {"value": <number>, "tolerance": <absolute>} or {"value", "relative"}."""
    spec = expected if isinstance(expected, dict) else {"value": expected, "tolerance": 0}
    try:
        got = float(re.sub(r"[^0-9eE+.-]", "", _text(actual)) or "nan")
        want = float(spec["value"])
    except (TypeError, ValueError, KeyError):
        return Result("numeric_tolerance", False, "value is not numeric")
    if math.isnan(got):
        return Result("numeric_tolerance", False, "value is not numeric")
    tol = float(spec.get("tolerance", 0)) + abs(want) * float(spec.get("relative", 0))
    ok = abs(got - want) <= tol
    return Result("numeric_tolerance", ok, "", {"expected": want, "actual": got, "tolerance": tol})


def route_equals(expected: Any, actual: Any) -> Result:
    got = actual.get("route") if isinstance(actual, dict) else None
    ok = got == expected
    return Result("route_equals", ok, "", {"expected": expected, "actual": got})


def flags_superset(expected: Any, actual: Any) -> Result:
    wanted = set(expected or [])
    found = {f["code"] if isinstance(f, dict) else f for f in (actual or {}).get("flags", [])}
    missing = sorted(wanted - found)
    return Result("flags_superset", not missing, "", {"missing": missing})


def field_f1(expected: Any, actual: Any) -> Result:
    """Micro-F1 over normalised field values. `expected` and `actual` are flat dicts."""
    want = {k: _normalize(v) for k, v in (expected or {}).items() if v not in (None, "")}
    got = {k: _normalize(v) for k, v in (actual or {}).items() if v not in (None, "")}
    if not want:
        return Result("field_f1", False, "no expected fields")
    tp = sum(1 for k, v in want.items() if got.get(k) == v)
    precision = tp / len(got) if got else 0.0
    recall = tp / len(want)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return Result(
        "field_f1",
        f1 >= 0.999,
        f"f1={f1:.3f}",
        {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)},
    )


def tool_sequence(expected: Any, actual: Any) -> Result:
    """Expected ordered tool names; counts unnecessary calls (§B13 trajectory)."""
    wanted = [str(t) for t in (expected or [])]
    events = (actual or {}).get("tool_events") if isinstance(actual, dict) else actual
    called = [e["tool"] if isinstance(e, dict) else str(e) for e in (events or [])]
    i = 0
    for name in called:
        if i < len(wanted) and name == wanted[i]:
            i += 1
    in_order = i == len(wanted)
    unnecessary = max(0, len(called) - len(wanted))
    return Result(
        "tool_sequence",
        in_order,
        "" if in_order else f"expected {wanted}, got {called}",
        {"matched": i, "expected": wanted, "called": called, "unnecessary_calls": unnecessary},
    )


def citation_valid(expected: Any, actual: Any) -> Result:
    """Every citation in the answer must resolve to a supplied source id."""
    body = _text(actual)
    known = {str(s) for s in (expected or [])}
    if isinstance(actual, dict) and actual.get("sources"):
        known |= {str(s.get("id") if isinstance(s, dict) else s) for s in actual["sources"]}
    used = set(re.findall(r"\[([A-Za-z0-9_.:-]{1,40})\]", body))
    invalid = sorted(used - known)
    return Result(
        "citation_valid",
        not invalid and bool(used),
        "no citations" if not used else (f"invalid: {', '.join(invalid)}" if invalid else ""),
        {"used": sorted(used), "invalid": invalid},
    )


CHECKS: dict[str, Callable[[Any, Any], Result]] = {
    "non_empty": non_empty,
    "valid_json": valid_json,
    "json_schema": json_schema,
    "required_keywords": required_keywords,
    "forbidden_phrases": forbidden_phrases,
    "exact_match": exact_match,
    "numeric_tolerance": numeric_tolerance,
    "route_equals": route_equals,
    "flags_superset": flags_superset,
    "field_f1": field_f1,
    "tool_sequence": tool_sequence,
    "citation_valid": citation_valid,
}


@dataclass(frozen=True)
class CaseScore:
    score: float
    results: tuple[Result, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def public(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 4),
            "passed": self.passed,
            "checks": [r.public() for r in self.results],
        }


def run_checks(
    specs: Sequence[dict[str, Any]], actual: Any, weights: dict[str, float] | None = None
) -> CaseScore:
    """Run the case's checks. An unknown check name fails loudly rather than being skipped."""
    results: list[Result] = []
    for spec in specs:
        name = str(spec.get("check", ""))
        fn = CHECKS.get(name)
        if fn is None:
            results.append(Result(name or "unknown", False, "unknown check"))
            continue
        try:
            results.append(fn(spec.get("expected"), actual))
        except Exception as exc:  # a broken check is a failure, never a silent pass
            results.append(Result(name, False, f"check raised {type(exc).__name__}"))
    if not results:
        return CaseScore(0.0, ())
    if weights:
        total = sum(weights.get(r.check, 1.0) for r in results) or 1.0
        score = sum(weights.get(r.check, 1.0) for r in results if r.passed) / total
    else:
        score = sum(1 for r in results if r.passed) / len(results)
    return CaseScore(score, tuple(results))
