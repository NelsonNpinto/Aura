"""Finance copilot (§B7): a bounded tool loop on the shared router and tool gateway.

Middleware, in the order it runs:
  * PII redaction on the question before any provider call, log or trace;
  * injection screening of the question and of every tool result that re-enters a prompt
    (second-order injection, §B18) — untrusted text is always spotlighted as data;
  * model-call and tool-call limits (MAX_STEPS, MAX_TOOL_CALLS);
  * thread summarisation so long conversations stay inside the context budget;
  * human-in-the-loop: write tools return `confirmation_required` instead of acting.

Answers cite collected evidence by id. A citation that does not resolve fails the answer rather
than being quietly dropped — a citation is a pointer, not proof.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.agents.copilot.tools import register_copilot_tools, sql_catalog
from app.core.auth import Principal
from app.core.logging import get_logger
from app.graph.queries import catalog as graph_catalog
from app.guardrails.pii import redact, redact_any
from app.llm.router import CallContext, ModelRouter, get_router
from app.memory import store as memory_store
from app.schemas.llm_outputs import CopilotStep
from app.tools.gateway import ToolContext, ToolDenied, ToolFailed, call_tool

log = get_logger("copilot")

MAX_STEPS = 5
MAX_TOOL_CALLS = 6
COPILOT_TOOLS = (
    "search_policies",
    "graph_query",
    "sql_query",
    "list_invoices",
    "get_invoice",
    "explain_decision",
    "start_invoice_run",
)
NOT_IN_DATA = "The answer is not in the data I can see."

Emit = Callable[[dict[str, Any]], Awaitable[None]]

_registered = False


def _ensure_tools() -> None:
    global _registered
    if not _registered:
        register_copilot_tools()
        _registered = True


@dataclass
class Evidence:
    """One citable piece of evidence gathered during the loop."""

    id: str
    kind: str
    tool: str
    summary: str
    payload: Any

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "tool": self.tool, "summary": self.summary}


@dataclass
class CopilotRun:
    answer: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    citation_valid: bool = True
    invalid_citations: list[str] = field(default_factory=list)
    steps: int = 0
    llm: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "sources": [e.public() for e in self.evidence],
            "tool_events": self.tool_events,
            "citation_valid": self.citation_valid,
            "invalid_citations": self.invalid_citations,
            "steps": self.steps,
            "llm": self.llm,
        }


def tool_catalog() -> str:
    graph_templates = ", ".join(t["name"] for t in graph_catalog())
    sql_templates = ", ".join(t["name"] for t in sql_catalog())
    return "\n".join(
        [
            "search_policies(query, doc_types?) - hybrid search over AP policy documents.",
            f"graph_query(template, params) - knowledge graph. Templates: {graph_templates}.",
            f"sql_query(template, params) - read-only SQL templates: {sql_templates}.",
            "list_invoices(status?, vendor_id?, limit?) - recent invoices.",
            "get_invoice(invoice) - one invoice by id or number, with flags and lines.",
            "explain_decision(run_id) - audit lineage for a run, with chain verification.",
            "start_invoice_run(document_id, confirm) - WRITE. Needs the user's explicit"
            " confirmation; call it first without confirm to ask.",
        ]
    )


def _evidence_summary(tool: str, args: dict[str, Any], result: dict[str, Any]) -> str:
    if tool == "search_policies":
        hits = result.get("passages", [])
        return f"{len(hits)} policy passage(s) for {args.get('query', '')[:80]}"
    if tool == "graph_query":
        return f"graph template {args.get('template')}: {len(result.get('rows', []))} row(s)"
    if tool == "sql_query":
        return f"sql template {args.get('template')}: {len(result.get('rows', []))} row(s)"
    if tool == "list_invoices":
        return f"{len(result.get('invoices', []))} invoice(s)"
    if tool == "get_invoice":
        inv = result.get("invoice") or {}
        return f"invoice {inv.get('invoice_number')} ({inv.get('status')})"
    if tool == "explain_decision":
        return f"{len(result.get('events', []))} audit event(s)"
    return tool


def _render_evidence(items: list[Evidence]) -> str:
    if not items:
        return "(no evidence gathered yet)"
    blocks = []
    for e in items:
        body = json.dumps(e.payload, default=str)[:2500]
        blocks.append(f"[{e.id}] {e.summary}\n{body}")
    return "\n\n".join(blocks)


def check_citations(answer: str, evidence: list[Evidence], claimed: list[str]) -> list[str]:
    """Return the citation ids that do not resolve to gathered evidence."""
    known = {e.id for e in evidence if not e.payload.get("error") or e.tool == "start_invoice_run"}
    used = set(re.findall(r"\[([A-Za-z0-9_.:-]{1,40})\]", answer)) | set(claimed)
    return sorted(c for c in used if c not in known)


async def _memories(principal: Principal, question: str) -> list[Any]:
    from app.core.db import tenant_tx

    try:
        async with tenant_tx(principal.org_id, principal.user_id) as s:
            return await memory_store.recall(
                s,
                principal.org_id,
                kind="user",
                subject_id=principal.user_id,
                query=question,
                limit=3,
            )
    except Exception as exc:
        log.warning("copilot.memory_failed", error=type(exc).__name__)
        return []


async def run_copilot(
    principal: Principal,
    question: str,
    ctx: CallContext,
    *,
    thread_summary: str = "",
    history: list[dict[str, str]] | None = None,
    emit: Emit | None = None,
    model_router: ModelRouter | None = None,
) -> dict[str, Any]:
    """Run the copilot loop and return a cited answer."""
    _ensure_tools()
    router = model_router or get_router()
    run = CopilotRun()
    safe_question = redact(question)
    evidence: list[Evidence] = []
    tool_calls = 0
    notes = await _memories(principal, safe_question)
    notes_txt = (
        "\n".join(f"- {n.fact}" for n in notes) if notes else "(no confirmed notes for this user)"
    )
    transcript: list[str] = []
    if history:
        for m in history[-6:]:
            transcript.append(f"{m['role']}: {redact(m['content'])[:800]}")

    async def send(event: dict[str, Any]) -> None:
        if emit:
            await emit(event)

    for step in range(MAX_STEPS):
        run.steps = step + 1
        result = await router.run(
            "copilot_step",
            {
                "question": safe_question,
                "tools": tool_catalog(),
                "evidence": _render_evidence(evidence),
                "history": "\n".join(transcript) or "(new conversation)",
                "summary": thread_summary or "(none)",
                "notes": notes_txt,
            },
            ctx,
        )
        run.llm = result.public()
        parsed: CopilotStep | None = result.parsed  # type: ignore[assignment]
        if parsed is None:
            try:
                parsed = CopilotStep.model_validate_json(result.text)
            except Exception:
                run.answer = NOT_IN_DATA
                run.citation_valid = False
                return run.public()
        await send({"type": "copilot.step", "step": run.steps, "action": parsed.action})

        if parsed.action == "answer" or not parsed.tool:
            answer = (parsed.answer or "").strip() or NOT_IN_DATA
            invalid = check_citations(answer, evidence, parsed.citations)
            run.answer = answer
            run.evidence = evidence
            run.invalid_citations = invalid
            run.citation_valid = not invalid and (
                answer == NOT_IN_DATA or bool(re.search(r"\[[A-Za-z0-9_.:-]{1,40}\]", answer))
            )
            if invalid:
                run.answer = (
                    "I could not verify every citation in that answer, so I am not showing it. "
                    f"Unresolved reference(s): {', '.join(invalid)}. Ask a narrower question."
                )
            elif not run.citation_valid:
                run.answer = NOT_IN_DATA
            return run.public()

        if parsed.tool not in COPILOT_TOOLS:
            transcript.append(f"system: tool {parsed.tool} is not available")
            continue
        if tool_calls >= MAX_TOOL_CALLS:
            transcript.append("system: tool-call budget exhausted; answer from what you have")
            continue
        tool_calls += 1
        args = dict(parsed.arguments or {})
        args.pop("_user_id", None)
        if parsed.tool in ("search_policies", "start_invoice_run"):
            args["_user_id"] = principal.user_id
        tctx = ToolContext(
            org_id=principal.org_id,
            actor_id=principal.user_id,
            roles=principal.roles or frozenset({"guest"}),
            agent="copilot",
        )
        await send({"type": "tool.called", "tool": parsed.tool, "arguments": redact_args(args)})
        try:
            out = await call_tool(parsed.tool, args, tctx)
        except (ToolDenied, ToolFailed) as exc:
            out = {"error": {"code": exc.code, "message": exc.message}}
        run.tool_events.extend(tctx.events)
        ev = Evidence(
            id=f"{parsed.tool}:{uuid.uuid4().hex[:6]}",
            kind=parsed.tool,
            tool=parsed.tool,
            summary=_evidence_summary(parsed.tool, args, out),
            # Tool output is untrusted once it re-enters a prompt (§B18 second-order injection).
            payload=out,
        )
        evidence.append(ev)
        await send({"type": "tool.result", "tool": parsed.tool, "evidence_id": ev.id})
        transcript.append(f"tool {parsed.tool} -> {ev.id}: {ev.summary}")

    run.answer = "I ran out of steps before I could answer with evidence. Try a narrower question."
    run.evidence = evidence
    run.citation_valid = False
    return run.public()


def redact_args(args: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in args.items() if not k.startswith("_")}
    red: dict[str, Any] = redact_any(out)
    return red
