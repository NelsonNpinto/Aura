"""Text-to-Cypher guard (§B8.2) — the second layer behind the server-side READ transaction.

Tenant isolation never depends on the model. A generated `$org_id` predicate can be bypassed
(`OR true`), so:
  * tenant data is reachable only through the parameterised templates in `queries.py`;
  * free-form generated Cypher runs only against the synthetic `demo` org;
  * every returned row whose `org_id` differs from the caller's is dropped (`drop_foreign_rows`).
"""

from __future__ import annotations

import re
from typing import Any

from app.core.errors import AppError

MAX_LIMIT = 100
DEMO_ORG_ID = "demo"

# Write and side-effecting clauses. Checked on a comment-free, string-free copy of the query.
FORBIDDEN = (
    "create",
    "merge",
    "delete",
    "detach",
    "set",
    "remove",
    "drop",
    "load csv",
    "foreach",
    "periodic",
    "use ",
    "terminate",
)
ALLOWED_PROCEDURES = frozenset({"db.labels", "db.relationshiptypes", "db.propertykeys"})

# Single- or double-quoted literals, backslash escapes included. Stripping these first means a
# keyword inside a string (a vendor called "Create Ltd") neither trips a check nor hides one.
STRING_LITERAL = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")


class CypherRejected(AppError):
    status_code = 400
    code = "cypher_rejected"


def _strip(cypher: str) -> str:
    """Remove comments and string literals so keywords inside them can't trip or hide a check."""
    no_block = re.sub(r"/\*.*?\*/", " ", cypher, flags=re.S)
    no_line = re.sub(r"//[^\n]*", " ", no_block)
    no_str = STRING_LITERAL.sub(" '' ", no_line)
    return re.sub(r"\s+", " ", no_str).strip()


def validate(cypher: str) -> str:
    """Return the query to execute, or raise CypherRejected. Never executes anything."""
    if not cypher or not cypher.strip():
        raise CypherRejected("Empty query", details={"reason": "empty"})
    if len(cypher) > 2000:
        raise CypherRejected("Query too long", details={"reason": "too_long"})
    # Checks run on a comment-free, literal-free copy; the query that executes is the original,
    # because blanking its string literals would change what it means.
    stripped = _strip(cypher)
    if ";" in stripped.rstrip(";"):
        raise CypherRejected("Multiple statements are not allowed", details={"reason": "multi"})
    stripped = stripped.rstrip(";").strip()
    body = " ".join(cypher.split()).rstrip(";").strip()
    lowered = f" {stripped.lower()} "
    for word in FORBIDDEN:
        token = word if word.endswith(" ") else rf"\b{re.escape(word)}\b"
        if re.search(token, lowered):
            raise CypherRejected(
                f"Clause '{word.strip()}' is not allowed in a generated query",
                details={"reason": "forbidden_clause", "clause": word.strip()},
            )
    for proc in re.findall(r"\bcall\s+([a-zA-Z0-9_.]+)", lowered):
        if proc not in ALLOWED_PROCEDURES:
            raise CypherRejected(
                f"Procedure {proc} is not allow-listed",
                details={"reason": "procedure", "procedure": proc},
            )
    if not re.match(r"^(match|optional match|with|unwind|return|call)\b", lowered.strip()):
        raise CypherRejected("Query must start with a read clause", details={"reason": "not_read"})
    limits = [int(n) for n in re.findall(r"\blimit\s+(\d+)\b", lowered)]
    if not limits:
        return f"{body} LIMIT {MAX_LIMIT}"
    if max(limits) > MAX_LIMIT:
        raise CypherRejected(
            f"LIMIT must be {MAX_LIMIT} or less", details={"reason": "limit", "limit": max(limits)}
        )
    return body


def free_form_allowed(org_id: str) -> bool:
    """Free-form generated Cypher is confined to the synthetic demo tenant."""
    return org_id == DEMO_ORG_ID


def drop_foreign_rows(rows: list[dict[str, Any]], org_id: str) -> list[dict[str, Any]]:
    """Drop any row that carries an org_id other than the caller's (defence in depth)."""
    kept = []
    for row in rows:
        found = _org_ids(row)
        if found and found - {org_id}:
            continue
        kept.append(row)
    return kept


def _org_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        out: set[str] = set()
        for k, v in value.items():
            if k == "org_id" and isinstance(v, str):
                out.add(v)
            else:
                out |= _org_ids(v)
        return out
    if isinstance(value, (list, tuple)):
        out = set()
        for item in value:
            out |= _org_ids(item)
        return out
    return set()
