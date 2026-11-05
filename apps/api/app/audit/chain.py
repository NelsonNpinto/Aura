"""Hash-chained, append-only audit log (§B12). Tamper-evident, not tamper-proof.

hash = SHA-256(prev_hash || canonical_json(event without id and hash)). One chain per org.
Appends lock the org's row in audit.chain_heads (SELECT ... FOR UPDATE) inside the caller's
transaction, so concurrent appends serialize and the chain cannot fork. Someone with
database-owner access could rewrite the whole chain consistently; the daily external anchor
(chain-head hash committed to the public repo) is what makes that detectable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

ACTOR_TYPES = frozenset({"agent", "human", "system"})
HASHED_FIELDS = (
    "org_id",
    "seq",
    "run_id",
    "ts",
    "actor_type",
    "actor_id",
    "action",
    "target_type",
    "target_id",
    "tool",
    "decision",
    "input_hash",
    "output_hash",
    "evidence_refs",
    "model",
    "prompt_version",
    "git_sha",
    "trace_id",
    "guardrail_verdicts",
    "details",
    "prev_hash",
)


def genesis_hash(org_id: str) -> str:
    return hashlib.sha256(f"aura-audit-genesis:{org_id}".encode()).hexdigest()


def _default(o: object) -> str:
    if isinstance(o, datetime):
        return _ts(o)
    return str(o)


def _ts(d: datetime) -> str:
    if d.tzinfo is None:
        raise ValueError("audit timestamps must be timezone-aware")
    return d.astimezone(UTC).isoformat(timespec="microseconds")


def canonical_json(obj: object) -> str:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_default
    )


def sha256_json(obj: object) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def event_hash(prev_hash: str, event: Mapping[str, Any]) -> str:
    body = {k: event.get(k) for k in HASHED_FIELDS}
    if isinstance(body["ts"], datetime):
        body["ts"] = _ts(body["ts"])
    return hashlib.sha256((prev_hash + canonical_json(body)).encode()).hexdigest()


@dataclass
class AuditEvent:
    action: str
    actor_type: str
    actor_id: str
    run_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    tool: str | None = None
    decision: str | None = None
    input: object = None
    output: object = None
    evidence_refs: Sequence[Mapping[str, Any]] = field(default_factory=list)
    model: str | None = None
    prompt_version: str | None = None
    trace_id: str | None = None
    guardrail_verdicts: Sequence[Mapping[str, Any]] = field(default_factory=list)
    details: Mapping[str, Any] = field(default_factory=dict)


async def append(session: AsyncSession, org_id: str, ev: AuditEvent) -> dict[str, Any]:
    """Append one event to the org's chain inside the caller's (tenant) transaction."""
    if ev.actor_type not in ACTOR_TYPES:
        raise ValueError(f"actor_type must be one of {sorted(ACTOR_TYPES)}")
    await session.execute(
        text(
            "INSERT INTO audit.chain_heads (org_id, seq, head_hash) VALUES (:o, 0, :g)"
            " ON CONFLICT (org_id) DO NOTHING"
        ),
        {"o": org_id, "g": genesis_hash(org_id)},
    )
    head = (
        await session.execute(
            text("SELECT seq, head_hash FROM audit.chain_heads WHERE org_id = :o FOR UPDATE"),
            {"o": org_id},
        )
    ).one()
    row: dict[str, Any] = {
        "org_id": org_id,
        "seq": int(head.seq) + 1,
        "run_id": ev.run_id,
        "ts": datetime.now(UTC),
        "actor_type": ev.actor_type,
        "actor_id": ev.actor_id,
        "action": ev.action,
        "target_type": ev.target_type,
        "target_id": ev.target_id,
        "tool": ev.tool,
        "decision": ev.decision,
        "input_hash": None if ev.input is None else sha256_json(ev.input),
        "output_hash": None if ev.output is None else sha256_json(ev.output),
        "evidence_refs": list(ev.evidence_refs),
        "model": ev.model,
        "prompt_version": ev.prompt_version,
        "git_sha": get_settings().git_sha,
        "trace_id": ev.trace_id,
        "guardrail_verdicts": list(ev.guardrail_verdicts),
        "details": dict(ev.details),
        "prev_hash": head.head_hash,
    }
    row["hash"] = event_hash(row["prev_hash"], row)
    await session.execute(
        text(
            "INSERT INTO audit.audit_events (org_id, seq, run_id, ts, actor_type, actor_id, action,"
            " target_type, target_id, tool, decision, input_hash, output_hash, evidence_refs, model,"
            " prompt_version, git_sha, trace_id, guardrail_verdicts, details, prev_hash, hash)"
            " VALUES (:org_id, :seq, :run_id, :ts, :actor_type, :actor_id, :action, :target_type,"
            " :target_id, :tool, :decision, :input_hash, :output_hash, CAST(:evidence_refs AS jsonb),"
            " :model, :prompt_version, :git_sha, :trace_id, CAST(:guardrail_verdicts AS jsonb),"
            " CAST(:details AS jsonb), :prev_hash, :hash)"
        ),
        {
            **row,
            "evidence_refs": canonical_json(row["evidence_refs"]),
            "guardrail_verdicts": canonical_json(row["guardrail_verdicts"]),
            "details": canonical_json(row["details"]),
        },
    )
    await session.execute(
        text(
            "UPDATE audit.chain_heads SET seq = :s, head_hash = :h, updated_at = now()"
            " WHERE org_id = :o"
        ),
        {"s": row["seq"], "h": row["hash"], "o": org_id},
    )
    return row


@dataclass
class Verification:
    verified: bool
    events_checked: int
    head_seq: int
    head_hash: str | None
    first_broken: dict[str, Any] | None
    run_event_count: int | None = None

    def public(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "events_checked": self.events_checked,
            "head_seq": self.head_seq,
            "head_hash": self.head_hash,
            "first_broken": self.first_broken,
            "run_event_count": self.run_event_count,
        }


_COLS = ", ".join(HASHED_FIELDS) + ", hash"


async def verify(session: AsyncSession, org_id: str, run_id: str | None = None) -> Verification:
    """Recompute the org chain from genesis; report the first broken link.

    With run_id, the chain is checked up to that run's last event (the chain is per org, so a
    run is only as trustworthy as everything before it)."""
    upto: int | None = None
    run_count: int | None = None
    if run_id:
        r = (
            await session.execute(
                text(
                    "SELECT max(seq) AS m, count(*) AS n FROM audit.audit_events"
                    " WHERE org_id = :o AND run_id = :r"
                ),
                {"o": org_id, "r": run_id},
            )
        ).one()
        run_count = int(r.n)
        if not r.n:
            return Verification(False, 0, 0, None, {"reason": "no audit events for run"}, 0)
        upto = int(r.m)
    q = f"SELECT {_COLS} FROM audit.audit_events WHERE org_id = :o"  # noqa: S608 constant cols
    params: dict[str, Any] = {"o": org_id}
    if upto is not None:
        q += " AND seq <= :u"
        params["u"] = upto
    rows = (await session.execute(text(q + " ORDER BY seq"), params)).mappings().all()
    prev = genesis_hash(org_id)
    expected_seq = 1
    for r in rows:
        ev = dict(r)
        if ev["seq"] != expected_seq:
            return Verification(
                False, expected_seq - 1, expected_seq - 1, prev,
                {"seq": expected_seq, "reason": f"missing event (found seq {ev['seq']})"},
                run_count,
            )
        if ev["prev_hash"] != prev:
            return Verification(
                False, expected_seq - 1, ev["seq"], prev,
                {"seq": ev["seq"], "reason": "prev_hash does not match previous event"},
                run_count,
            )
        recomputed = event_hash(prev, ev)
        if recomputed != ev["hash"]:
            return Verification(
                False, expected_seq - 1, ev["seq"], prev,
                {"seq": ev["seq"], "reason": "event content does not match its hash"},
                run_count,
            )
        prev = ev["hash"]
        expected_seq += 1
    if upto is None:
        head = (
            await session.execute(
                text("SELECT seq, head_hash FROM audit.chain_heads WHERE org_id = :o"),
                {"o": org_id},
            )
        ).first()
        if head and (int(head.seq) != expected_seq - 1 or head.head_hash != prev):
            return Verification(
                False, expected_seq - 1, int(head.seq), prev,
                {"seq": int(head.seq), "reason": "chain head does not match last event"},
                run_count,
            )
    return Verification(True, expected_seq - 1, expected_seq - 1, prev, None, run_count)


async def events_for_run(session: AsyncSession, org_id: str, run_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                f"SELECT {_COLS} FROM audit.audit_events"  # noqa: S608 constant cols
                " WHERE org_id = :o AND run_id = :r ORDER BY seq"
            ),
            {"o": org_id, "r": run_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
