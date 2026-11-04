import json

from jsonschema import Draft202012Validator

from app.schemas.requests import Check


def reject_non_json_number(value):
    raise ValueError(f"Non-JSON numeric constant: {value}")


def evaluate(response: str, checks: list[Check]) -> list[dict]:
    """Checks measure explicit output rules, never truthfulness or hallucination."""
    results = []
    for check in checks:
        passed = False
        detail = ""
        if check.kind == "non_empty":
            passed = bool(response.strip())
            detail = "Response contains text" if passed else "Response is empty"
        elif check.kind in ("valid_json", "json_schema"):
            try:
                value = json.loads(response, parse_constant=reject_non_json_number)
                if check.kind == "json_schema":
                    errors = list(Draft202012Validator(check.schema_definition).iter_errors(value))
                    passed = not errors
                    detail = "; ".join(e.message for e in errors[:3]) or "JSON matches schema"
                else:
                    passed, detail = True, "Response is valid JSON"
            except (ValueError, RecursionError):
                detail = "Response is not valid JSON"
        elif check.kind == "required_keywords":
            missing = [v for v in check.values if v.casefold() not in response.casefold()]
            passed = not missing
            detail = f"Missing: {', '.join(missing)}" if missing else "All keywords present"
        elif check.kind == "forbidden_phrases":
            found = [v for v in check.values if v.casefold() in response.casefold()]
            passed = not found
            detail = f"Found: {', '.join(found)}" if found else "No forbidden phrases found"
        elif check.kind == "exact_match":
            passed = response.strip() == check.expected.strip()
            detail = "Matches expected answer" if passed else "Answer differs from expected"
        results.append(
            {"kind": check.kind, "passed": passed, "detail": detail, "method": "deterministic"}
        )
    return results
