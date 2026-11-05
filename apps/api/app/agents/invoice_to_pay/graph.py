"""Invoice-to-pay workflow (§B6) on LangGraph.

intake_guard → extract → validate → vendor_verify → match → code_gl → policy_check → risk_route
→ (human_approval) → post_and_schedule → finalize. Blocked or exception runs jump to finalize.

Deterministic code decides (matching, tolerances, approval matrix, SoD, risk, routing). Models
only extract, explain, draft emails and propose GL codes for lines without a PO. Never auto-post
on error. Every node is idempotent (ERP writes use run_id-derived idempotency keys) and emits
SSE + audit events.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, TypedDict

from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import text

from app.agents.invoice_to_pay.events import Emitter
from app.agents.invoice_to_pay.extraction import ExtractedInvoice, fixture_for, normalize
from app.audit.chain import AuditEvent, append, sha256_json
from app.core.auth import Principal
from app.core.config import get_settings
from app.core.db import tenant_tx
from app.domain.approval import ApprovalMatrix, Level
from app.domain.duplicates import PriorInvoice, find_duplicates, normalize_invoice_number
from app.domain.flags import SEVERITY, Flag, Severity
from app.domain.matching import InvoiceLine, LineOutcome, POLine, Tolerances, three_way_match
from app.domain.risk import Route, decide
from app.guardrails.pii import find_pii
from app.llm.router import CallContext, get_router
from app.services.blob import get_blob_store
from app.services.pdf import extract_text as pdf_text
from app.services.pdf import find_zero_width, render_pages_png
from app.tools.gateway import ToolContext, ToolDenied, ToolFailed, call_tool

FX_TO_BASE = {"USD": Decimal("1"), "EUR": Decimal("1.08"), "INR": Decimal("0.012"), "GBP": Decimal("1.27")}
EXPECTED_TAX = {"USD": (0.0, 0.10), "EUR": (0.19, 0.19), "INR": (0.18, 0.18), "GBP": (0.20, 0.20)}
NO_PO_CATEGORIES = {"electricity", "water", "telecom", "software", "cloud", "security"}
NO_PO_LIMIT_BASE_MINOR = 500_000
EXCEPTION_FLAGS = {"ARITHMETIC_ERROR", "CURRENCY_MISMATCH", "CREDIT_NOTE", "VENDOR_UNRESOLVED"}
INJECTION_PATTERNS = re.compile(
    r"(ignore (all )?(previous|prior) (instructions|rules)|disregard (all )?(prior|previous)|"
    r"you are now|system\s*:|note to (the )?ai|skip (vendor )?verification|approve and pay|"
    r"set route\s*=|mark (this|the) invoice as verified|maintenance mode)", re.I)
PERSONAL_PII = {"EMAIL", "SSN", "CARD", "PHONE", "IBAN", "PAN"}
NODES = ["intake_guard", "extract", "validate", "vendor_verify", "match", "code_gl",
         "policy_check", "risk_route", "human_approval", "post_and_schedule", "finalize"]

for _code, _sev in {"CREDIT_NOTE": Severity.MEDIUM, "CURRENCY_MISMATCH": Severity.MEDIUM,
                    "VENDOR_UNRESOLVED": Severity.MEDIUM, "EMPTY_DOCUMENT": Severity.HIGH}.items():
    SEVERITY.setdefault(_code, _sev)


class RunState(TypedDict, total=False):
    run_id: str
    org_id: str
    document_id: str
    started_by: str
    status: str
    doc: dict[str, Any]
    invoice: dict[str, Any]
    vendor: dict[str, Any]
    match: dict[str, Any]
    gl_coding: list[dict[str, Any]]
    policy_findings: list[dict[str, Any]]
    flags: list[dict[str, Any]]
    risk: dict[str, Any]
    route: str
    approval: dict[str, Any]
    approvals: list[dict[str, Any]]
    posting: dict[str, Any]
    exception: dict[str, Any]
    memories_used: list[str]
    costs: dict[str, Any]
    timings: dict[str, int]
    errors: list[str]
    blocked: bool


@dataclass
class Deps:
    """Per-run runtime handles; not checkpointed (rebuilt on resume)."""

    run_id: str
    org_id: str
    actor_id: str
    emitter: Emitter
    country: str | None = None
    approval_token: str | None = None
    fake: bool = False  # deterministic fixtures, no provider calls (CI, replay mode)
    tool_events: list[dict[str, Any]] = field(default_factory=list)


RUNTIME: dict[str, Deps] = {}


def _deps(state: RunState) -> Deps:
    return RUNTIME[state["run_id"]]


def _fake(state: RunState) -> bool:
    return _deps(state).fake or get_settings().provider_mode == "fake"


def _flag(code: str, message: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "severity": SEVERITY.get(code, Severity.MEDIUM).value, "message": message, "evidence": evidence}


def _to_base(minor: int, currency: str | None) -> int:
    return int(Decimal(minor) * FX_TO_BASE.get(currency or "USD", Decimal("1")))


async def _tool(state: RunState, name: str, args: dict[str, Any], route: str | None = None) -> dict[str, Any]:
    d = _deps(state)
    await d.emitter.emit("tool.called", _current.get(state["run_id"]), tool=name)
    ctx = ToolContext(org_id=d.org_id, actor_id="agent:invoice_to_pay", roles=frozenset({"system"}),
                      agent="invoice_to_pay", run_id=d.run_id, route=route, approval_token=d.approval_token)
    t0 = time.monotonic()
    try:
        out = await call_tool(name, args, ctx)
    except (ToolDenied, ToolFailed) as e:
        await d.emitter.emit("tool.result", _current.get(state["run_id"]), tool=name, ok=False, error=e.code)
        raise
    ok = not (isinstance(out, dict) and "error" in out)
    await d.emitter.emit("tool.result", _current.get(state["run_id"]), tool=name, ok=ok,
                         latency_ms=int((time.monotonic() - t0) * 1000),
                         error=(out.get("error", {}).get("code") if not ok else None))
    return out


_current: dict[str, str] = {}


async def _llm(state: RunState, task: str, variables: dict[str, str], **kw: Any) -> Any:
    d = _deps(state)
    res = await get_router().run(task, variables, CallContext(org_id=d.org_id, user_id=d.actor_id, run_id=d.run_id, country=d.country), **kw)
    costs = state.setdefault("costs", {"tokens": 0, "est_usd_micros": 0})
    costs["tokens"] = costs.get("tokens", 0) + res.tokens_in + res.tokens_out
    costs["est_usd_micros"] = costs.get("est_usd_micros", 0) + res.est_cost_microusd
    await d.emitter.emit("llm.call", _current.get(state["run_id"]), task=task, model=res.model, cache_hit=res.cache_hit,
                         fallback_reason=res.fallback_reason, tokens=res.tokens_in + res.tokens_out,
                         prompt_version=res.prompt_version)
    return res


def node(name: str):  # type: ignore[no-untyped-def]
    """Wrap a node: SSE started/completed events, timing, audit event, error capture."""

    def wrap(fn):  # type: ignore[no-untyped-def]
        async def run(state: RunState) -> dict[str, Any]:
            d = _deps(state)
            _current[state["run_id"]] = name
            await d.emitter.emit("node.started", name)
            t0 = time.monotonic()
            before_tokens = state.get("costs", {}).get("tokens", 0)
            try:
                upd = await fn(state)
            except GraphInterrupt:
                raise
            except Exception as exc:  # never auto-post on error: route to exception with a reason
                upd = {"errors": [*state.get("errors", []), f"{name}: {type(exc).__name__}: {str(exc)[:200]}"]}
            ms = int((time.monotonic() - t0) * 1000)
            timings = {**state.get("timings", {}), name: ms}
            upd["timings"] = timings
            if "costs" in state and "costs" not in upd:
                upd["costs"] = state["costs"]  # _llm accumulates into state["costs"]
            summary = upd.pop("_summary", None)
            costs = upd.get("costs", state.get("costs", {}))
            await d.emitter.emit("node.completed", name, summary=summary, duration_ms=ms,
                                 tokens=costs.get("tokens", 0) - before_tokens,
                                 est_usd=round(costs.get("est_usd_micros", 0) / 1e6, 6))
            for f in upd.get("_new_flags", []):
                await d.emitter.emit("flag.raised", name, **f)
            upd.pop("_new_flags", None)
            async with tenant_tx(d.org_id) as s:
                await append(s, d.org_id, AuditEvent(
                    action=f"node.{name}", actor_type="agent", actor_id="agent:invoice_to_pay", run_id=d.run_id,
                    target_type="run", target_id=d.run_id, output={"summary": summary, "keys": sorted(upd)},
                    details={"duration_ms": ms, "summary": summary,
                             "evidence": upd.get("_evidence") or None},
                    evidence_refs=upd.pop("_evidence", []) or [],
                ))
            upd.pop("_evidence", None)
            return upd

        run.__name__ = name
        return run

    return wrap


def _add_flags(state: RunState, new: list[dict[str, Any]]) -> dict[str, Any]:
    have = {f["code"] for f in state.get("flags", [])}
    fresh = [f for f in new if f["code"] not in have]
    return {"flags": [*state.get("flags", []), *fresh], "_new_flags": fresh}


# ---------------------------------------------------------------------------- nodes
@node("intake_guard")
async def intake_guard(state: RunState) -> dict[str, Any]:
    d = _deps(state)
    async with tenant_tx(d.org_id) as s:
        doc = (await s.execute(text("SELECT id, blob_key, sha256, mime, filename, demo_key FROM ap.documents WHERE id = :i"),
                               {"i": state["document_id"]})).mappings().one()
    data = await get_blob_store().get(doc["blob_key"])
    # Scripted demo invoices are isolated: they never consume PO quantities and are never
    # compared with other demo runs, so they reach the same outcome every time (§B1).
    info: dict[str, Any] = {"sha256": doc["sha256"], "mime": doc["mime"], "filename": doc["filename"],
                            "demo_key": doc["demo_key"]}
    flags: list[dict[str, Any]] = []
    visible, hidden = "", []
    if doc["mime"] == "application/pdf":
        pt = pdf_text(data, max_pages=20)
        info["has_text_layer"] = pt.has_text_layer
        info["pages"] = len(pt.pages)
        visible = pt.visible_text
        hidden = [h.public() for h in pt.hidden if h.reason != "zero_width"]
        info["text"] = "\n\n".join(pt.pages)[:60_000]
    else:
        info["has_text_layer"] = False
        info["pages"] = 1
    info["hidden_text"] = hidden
    full = info.get("text", "")
    doc_type = "credit_note" if re.search(r"\bcredit\s+note\b", full, re.I) else "invoice"
    info["doc_type"] = doc_type
    verdicts = []
    if hidden:
        flags.append(_flag("HIDDEN_TEXT", f"{len(hidden)} hidden text span(s) found", spans=hidden[:5]))
        verdicts.append({"check": "hidden_text", "blocked": True, "count": len(hidden)})
    zw = find_zero_width(full)
    if zw:
        verdicts.append({"check": "zero_width", "count": zw})
    hits = sorted({m.group(0) for m in INJECTION_PATTERNS.finditer(full)})
    if hits:
        flags.append(_flag("INJECTION_DETECTED", "Instruction-like text addressed to an AI system", phrases=hits[:5]))
        verdicts.append({"check": "instruction_heuristic", "blocked": True, "phrases": hits[:5]})
    if full and not _fake(state) and not hits:
        # Prompt Guard 2 on 512-token-ish chunks with overlap; classifier failure never blocks alone.
        chunks = [full[i:i + 1800] for i in range(0, min(len(full), 9000), 1500)]
        for ch in chunks:
            try:
                res = await _llm(state, "injection_check", {"text": ch})
                label = res.text.strip().upper()
                malicious = "MALICIOUS" in label or "INJECTION" in label or label.startswith("1")
                verdicts.append({"check": "prompt_guard", "model": res.model, "label": label[:20]})
                if malicious:
                    flags.append(_flag("INJECTION_DETECTED", "Prompt Guard classified the document as an injection", model=res.model))
                    break
            except Exception as exc:  # noqa: BLE001
                verdicts.append({"check": "prompt_guard", "error": type(exc).__name__})
                break
    # Vendor tax IDs and remit-to bank details are expected business data on an invoice; flag
    # only personal data. Everything (including bank numbers) is still redacted before model calls.
    pii = [p for p in find_pii(full) if p.kind in PERSONAL_PII]
    if pii:
        kinds = sorted({p.kind for p in pii})
        flags.append(_flag("PII_PRESENT", f"PII found: {', '.join(kinds)} (redacted before model calls)", kinds=kinds))
    for v in verdicts:
        await d.emitter.emit("guardrail.verdict", "intake_guard", **v)
    blocked = any(f["code"] in ("INJECTION_DETECTED", "HIDDEN_TEXT") for f in flags)
    async with tenant_tx(d.org_id) as s:
        await s.execute(text("UPDATE ap.documents SET text = :t, has_text_layer = :h, pages = :p,"
                             " hidden_text_findings = CAST(:f AS jsonb) WHERE id = :i"),
                        {"t": full[:60_000] or None, "h": info["has_text_layer"], "p": info["pages"],
                         "f": json.dumps(hidden), "i": state["document_id"]})
    upd = {"doc": info, "blocked": blocked, **_add_flags(state, flags),
           "_summary": ("BLOCKED: " if blocked else "") + f"{doc_type}, text layer: {info['has_text_layer']}, "
                       f"{len(hidden)} hidden span(s), {len(hits)} instruction phrase(s)",
           "_evidence": [{"type": "document", "id": state["document_id"], "sha256": doc["sha256"]}]}
    if blocked:
        upd["route"] = Route.EXCEPTION.value
        upd["status"] = "blocked"
    return upd


@node("extract")
async def extract(state: RunState) -> dict[str, Any]:
    d = _deps(state)
    doc = state["doc"]
    fixture = fixture_for(doc["sha256"]) if _fake(state) else None
    if fixture:
        inv = normalize(fixture["extraction"], source_text=doc.get("text"), path="fixture", doc_type_hint=doc["doc_type"])
        if not doc.get("has_text_layer"):
            inv.path = "vision"  # fixture stands in for the vision model; routing treats it as a scan
    elif doc.get("has_text_layer"):
        from app.guardrails.pii import redact

        res = await _llm(state, "extract_text", {"document": redact(doc["text"])[:24_000]})
        raw = res.parsed.model_dump() if res.parsed else json.loads(res.text)
        # Bank details are redacted before the model sees them (§B11); read them from the source
        # text deterministically instead: bank details may never originate from model output.
        inv = normalize(raw, source_text=doc["text"], path="text", doc_type_hint=doc["doc_type"])
        acct = re.search(r"Bank account:\s*([0-9]{6,20})", doc["text"])
        rout = re.search(r"Routing:\s*([0-9]{6,12})", doc["text"])
        inv.bank_account = acct.group(1) if acct else None
        inv.bank_routing = rout.group(1) if rout else None
        inv.confidence["bank_account"] = 0.99 if acct else 0.0
        inv.unverified = [u for u in inv.unverified if not u.startswith("bank_")]
    else:
        async with tenant_tx(d.org_id) as s:
            key = (await s.execute(text("SELECT blob_key FROM ap.documents WHERE id = :i"), {"i": state["document_id"]})).scalar_one()
        data = await get_blob_store().get(key)
        pngs = render_pages_png(data, max_pages=3, scale=1.5) if doc["mime"] == "application/pdf" else [data]
        parts: list[dict[str, Any]] = [{"type": "text", "text": "Extract the invoice in the attached image(s)."}]
        for png in pngs[:3]:
            mime = "image/png" if png[:4] == b"\x89PNG" else "image/jpeg"
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(png).decode()}"}})
        res = await _llm(state, "extract_vision", {"note": "page images follow"}, extra_messages=[{"role": "user", "content": parts}])
        raw = res.parsed.model_dump() if res.parsed else json.loads(res.text)
        inv = normalize(raw, source_text=None, path="vision", doc_type_hint=doc["doc_type"])
    if any((ln.get("amount_minor") or 0) < 0 for ln in inv.lines) or (inv.total_minor or 0) < 0:
        inv.doc_type = "credit_note"
    flags = []
    low = [k for k, v in inv.confidence.items() if 0 < v < 0.6 and k in ("invoice_number", "total", "vendor_name", "currency")]
    if inv.path == "vision" or low:
        flags.append(_flag("LOW_EXTRACTION_CONFIDENCE", "Low-confidence fields need human review" if low else
                           "Vision extraction (scanned document) is always human-reviewed", fields=low, path=inv.path))
    if inv.unverified:
        flags.append(_flag("UNVERIFIED_FIELD", "Extracted values not found in the source text", fields=inv.unverified[:10]))
    async with tenant_tx(d.org_id) as s:
        await s.execute(text("INSERT INTO ap.extractions (org_id, run_id, path, data, confidence, evidence, model)"
                             " VALUES (:o, :r, :p, CAST(:d AS jsonb), CAST(:c AS jsonb), CAST(:e AS jsonb), :m)"),
                        {"o": d.org_id, "r": d.run_id, "p": inv.path, "d": json.dumps(inv.public()),
                         "c": json.dumps(inv.confidence), "e": json.dumps(inv.evidence), "m": None if inv.path == "fixture" else "router"})
    invd = inv.public()
    invd["bank_account"], invd["bank_routing"] = inv.bank_account, inv.bank_routing
    return {"invoice": invd, **_add_flags(state, flags),
            "_summary": f"{inv.path} path: {inv.vendor_name or '?'} #{inv.invoice_number or '?'}, "
                        f"{len(inv.lines)} line(s), total {inv.total_minor} {inv.currency}"}


@node("validate")
async def validate(state: RunState) -> dict[str, Any]:
    inv = state["invoice"]
    flags, problems = [], []
    for k in ("invoice_number", "currency", "total_minor"):
        if inv.get(k) in (None, ""):
            problems.append(f"missing {k}")
    for i, ln in enumerate(inv["lines"]):
        try:
            exp = int(Decimal(ln["quantity"]) * Decimal(ln["unit_price_minor"] or 0))
        except Exception:  # noqa: BLE001
            continue
        if ln["amount_minor"] is not None and abs(exp - ln["amount_minor"]) > 1:
            problems.append(f"line {i + 1}: qty x price {exp} != amount {ln['amount_minor']}")
    sub = sum(ln["amount_minor"] or 0 for ln in inv["lines"])
    if inv.get("subtotal_minor") is not None and abs(sub - inv["subtotal_minor"]) > len(inv["lines"]):
        problems.append(f"lines sum {sub} != subtotal {inv['subtotal_minor']}")
    if None not in (inv.get("subtotal_minor"), inv.get("tax_minor"), inv.get("total_minor")):
        if abs(inv["subtotal_minor"] + inv["tax_minor"] - inv["total_minor"]) > max(1, len(inv["lines"])):
            problems.append(f"subtotal + tax != total ({inv['subtotal_minor']} + {inv['tax_minor']} != {inv['total_minor']})")
    if problems:
        flags.append(_flag("ARITHMETIC_ERROR", "; ".join(problems)[:300], problems=problems))
    if inv.get("currency") in EXPECTED_TAX and inv.get("subtotal_minor") and inv.get("tax_minor") is not None and inv["doc_type"] != "credit_note":
        lo, hi = EXPECTED_TAX[inv["currency"]]
        rate = inv["tax_minor"] / inv["subtotal_minor"] if inv["subtotal_minor"] else 0
        if not (lo - 0.005 <= rate <= hi + 0.005):
            flags.append(_flag("TAX_MISMATCH", f"Tax rate {rate:.1%} outside expected {lo:.0%}-{hi:.0%} for {inv['currency']}", rate=round(rate, 4)))
    if inv.get("invoice_date") and inv.get("due_date") and inv["due_date"] < inv["invoice_date"]:
        flags.append(_flag("ARITHMETIC_ERROR", "Due date before invoice date"))
    if inv["doc_type"] == "credit_note":
        flags.append(_flag("CREDIT_NOTE", "Credit note: linked to the original invoice, never scheduled for payment"))
    return {**_add_flags(state, flags), "_summary": "ok" if not flags else ", ".join(f["code"] for f in flags)}


@node("vendor_verify")
async def vendor_verify(state: RunState) -> dict[str, Any]:
    d = _deps(state)
    inv = state["invoice"]
    flags = []
    found = await _tool(state, "search_vendors", {"tax_id": inv.get("vendor_tax_id"), "query": inv.get("vendor_name"), "limit": 3})
    vendors = found.get("vendors", [])
    vendor: dict[str, Any] = {}
    if found.get("match") == "tax_id" and len(vendors) == 1:
        vendor = {**vendors[0], "resolved_by": "tax_id"}
    elif found.get("match") == "name" and vendors and float(vendors[0].get("score", 0)) >= 0.6:
        if len(vendors) > 1 and float(vendors[1].get("score", 0)) >= float(vendors[0]["score"]) - 0.05:
            flags.append(_flag("VENDOR_AMBIGUOUS", "Several vendors match this name", candidates=[v["id"] for v in vendors[:3]]))
        vendor = {**vendors[0], "resolved_by": "name"}
    if not vendor:
        flags.append(_flag("NEW_VENDOR", "Vendor not found in the vendor master", name=inv.get("vendor_name")))
        flags.append(_flag("VENDOR_UNRESOLVED", "Unknown vendor: onboarding required before payment"))
        return {"vendor": {}, **_add_flags(state, flags), "_summary": "vendor not found"}
    master = await _tool(state, "get_vendor", {"vendor_id": vendor["id"]})
    vendor.update({k: master.get(k) for k in ("category", "currency", "payment_terms_days", "cost_center", "created_by", "contract_id")})
    bank = {}
    if inv.get("bank_account") and inv.get("bank_routing"):
        bank = await _tool(state, "compare_bank_account", {"vendor_id": vendor["id"], "routing": inv["bank_routing"], "account_number": inv["bank_account"]})
        vendor["bank_last_changed_by"] = bank.get("last_changed_by")
        if not bank.get("matches_current"):
            flags.append(_flag("BANK_ACCOUNT_MISMATCH", f"Bank account on invoice (..{bank.get('invoice_last4')}) differs from vendor master (..{bank.get('master_last4')})",
                               invoice_last4=bank.get("invoice_last4"), master_last4=bank.get("master_last4")))
        acct_hash = hashlib.sha256(f"{inv['bank_routing']}:{inv['bank_account']}".encode()).hexdigest()
        emp = await _tool(state, "get_employee_conflicts", {"account_hash": acct_hash})
        if emp.get("employees"):
            flags.append(_flag("VENDOR_EMPLOYEE_CONFLICT", "Invoice bank account belongs to an employee", employees=[e["id"] for e in emp["employees"]]))
    if inv.get("currency") and vendor.get("currency") and inv["currency"] != vendor["currency"]:
        flags.append(_flag("CURRENCY_MISMATCH", f"Invoice currency {inv['currency']} differs from vendor currency {vendor['currency']}"))
    # duplicates: vendor + normalised number, plus fuzzy (amount ±0.5%, 30 days, similar number)
    if inv.get("invoice_number") and inv.get("total_minor") is not None and inv.get("invoice_date") and not state["doc"].get("demo_key"):
        async with tenant_tx(d.org_id) as s:
            rows = (await s.execute(text(
                "SELECT i.id, i.vendor_id, i.invoice_number, i.total_minor, i.currency, i.invoice_date, r.status"
                " FROM ap.invoices i JOIN ap.runs r ON r.id = i.run_id JOIN ap.documents doc ON doc.id = i.document_id"
                " WHERE i.vendor_id = :v AND i.run_id <> :run AND doc.demo_key IS NULL"
                " AND r.status NOT IN ('rejected','cancelled','failed','blocked')"),
                {"v": vendor["id"], "run": d.run_id})).mappings().all()
        prior = [PriorInvoice(str(r["id"]), r["vendor_id"], r["invoice_number"] or "", r["total_minor"] or 0,
                              r["currency"] or "", r["invoice_date"], r["status"]) for r in rows if r["invoice_date"]]
        hits = find_duplicates(vendor_id=vendor["id"], number=inv["invoice_number"], total_minor=inv["total_minor"],
                               currency=inv["currency"] or "", invoice_date=date.fromisoformat(inv["invoice_date"]), prior=prior)
        for h in hits[:1]:
            flags.append(_flag("DUPLICATE_EXACT" if h.kind == "exact" else "DUPLICATE_SUSPECTED",
                               f"{'Duplicate' if h.kind == 'exact' else 'Possible duplicate'} of an earlier invoice", invoice_id=h.invoice_id, reasons=list(h.reasons)))
    return {"vendor": vendor, **_add_flags(state, flags),
            "_summary": f"{vendor['name']} ({vendor['id']}) by {vendor['resolved_by']}; bank match: {bank.get('matches_current') if bank else 'n/a'}",
            "_evidence": [{"type": "vendor", "id": vendor["id"]}]}


@node("match")
async def match(state: RunState) -> dict[str, Any]:
    inv, vendor = state["invoice"], state.get("vendor", {})
    flags: list[dict[str, Any]] = []
    lines = [InvoiceLine(i + 1, ln["description"], Decimal(ln["quantity"] or "0"), ln["unit_price_minor"] or 0,
                         ln["amount_minor"] or 0, ln["uom"]) for i, ln in enumerate(inv["lines"])]
    po_lines: list[POLine] = []
    po_info: dict[str, Any] = {}
    if inv.get("po_number"):
        po = await _tool(state, "get_purchase_order", {"po_number": inv["po_number"]})
        if "error" not in po:
            grn = await _tool(state, "get_goods_receipts", {"po_number": po["po_number"]})
            rec = grn.get("received_by_line", {})
            po_info = {"po_number": po["po_number"], "vendor_id": po["vendor_id"], "currency": po["currency"],
                       "receipts": [g["grn_number"] for g in grn.get("receipts", [])]}
            for pl in po["lines"]:
                po_lines.append(POLine(po["po_number"], pl["line_no"], pl["description"], Decimal(pl["quantity"]),
                                       pl["unit_price_minor"], pl["uom"], Decimal(rec.get(str(pl["line_no"]), "0")),
                                       Decimal(0) if state["doc"].get("demo_key") else Decimal(pl["billed_qty"]), pl["is_service"]))
            if vendor and po["vendor_id"] != vendor.get("id"):
                flags.append(_flag("VENDOR_AMBIGUOUS", "PO belongs to a different vendor", po_vendor=po["vendor_id"]))
            if inv.get("currency") and po["currency"] != inv["currency"]:
                flags.append(_flag("CURRENCY_MISMATCH", f"Invoice currency {inv['currency']} differs from PO currency {po['currency']}"))
    res = three_way_match(lines, po_lines, invoice_subtotal_minor=inv.get("subtotal_minor") or sum(x.amount_minor for x in lines),
                          header_po=inv.get("po_number"), tol=Tolerances())
    missing_po_allowed = False
    if not inv.get("po_number") and vendor.get("category") in NO_PO_CATEGORIES and vendor.get("contract_id"):
        base = _to_base(inv.get("total_minor") or 0, inv.get("currency"))
        missing_po_allowed = base <= NO_PO_LIMIT_BASE_MINOR
    for m in res.lines:
        if m.outcome == LineOutcome.PRICE_VARIANCE:
            pass
    if any("non-PO charge within" in n for m in res.lines for n in m.notes):
        flags.append(_flag("FREIGHT_WITHIN_TOLERANCE", "Freight/surcharge line within the 3% policy tolerance"))
    if res.over_billed:
        flags.append(_flag("OVER_BILLING", "Cumulative billed quantity exceeds PO quantity", lines=res.over_billed))
    md = {
        "po": po_info,
        "header_ok": res.header_ok,
        "missing_po_allowed": missing_po_allowed,
        "lines": [{"index": m.index, "outcome": m.outcome.value, "po_number": m.po_number, "po_line": m.po_line,
                   "invoice_unit_price_minor": m.invoice_unit_price_minor, "po_unit_price_minor": m.po_unit_price_minor,
                   "price_diff_minor": m.price_diff_minor, "price_tolerance_minor": m.price_tolerance_minor,
                   "invoice_qty": str(m.invoice_qty), "available_qty": None if m.available_qty is None else str(m.available_qty),
                   "similarity": round(m.similarity, 3), "notes": m.notes} for m in res.lines],
    }
    outcomes = [m.outcome.value for m in res.lines]
    return {"match": md, **_add_flags(state, flags),
            "_summary": f"{outcomes.count('matched')}/{len(outcomes)} lines matched" + (f"; {', '.join(sorted(set(o for o in outcomes if o != 'matched')))}" if set(outcomes) - {"matched"} else ""),
            "_evidence": [{"type": "po", "id": po_info.get("po_number")}, *[{"type": "grn", "id": g} for g in po_info.get("receipts", [])]] if po_info else []}


@node("code_gl")
async def code_gl(state: RunState) -> dict[str, Any]:
    inv, vendor, md = state["invoice"], state.get("vendor", {}), state.get("match", {})
    coded: list[dict[str, Any]] = []
    need: list[int] = []
    po_gl: dict[tuple[str, int], tuple[str, str]] = {}
    if md.get("po", {}).get("po_number"):
        po = await _tool(state, "get_purchase_order", {"po_number": md["po"]["po_number"]})
        po_gl = {(po["po_number"], pl["line_no"]): (pl["gl_account"], pl["cost_center"]) for pl in po.get("lines", [])}
    for i, m in enumerate(md.get("lines", [])):
        key = (m.get("po_number"), m.get("po_line"))
        if key in po_gl:
            gl, cc = po_gl[key]
            coded.append({"line_index": i, "gl_account": gl, "cost_center": cc, "confidence": 0.98, "source": "po_line", "rationale": "Coded from the matched PO line"})
        else:
            coded.append({})
            need.append(i)
    if need:
        chart = await _tool(state, "list_gl_accounts", {})
        if _fake(state):
            for i in need:
                desc = inv["lines"][i]["description"].lower()
                gl = "5020" if any(w in desc for w in ("freight", "delivery", "shipping")) else "6000"
                coded[i] = {"line_index": i, "gl_account": gl, "cost_center": vendor.get("cost_center") or "CC100",
                            "confidence": 0.6, "source": "rule", "rationale": "Deterministic fallback (fake provider mode)"}
        else:
            chart_txt = "\n".join(f"{g['code']} {g['name']}: {g['guidance']}" for g in chart.get("gl_accounts", []))
            chart_txt += "\nCost centers: " + ", ".join(f"{c['code']} {c['name']}" for c in chart.get("cost_centers", []))
            lines_txt = "\n".join(f"{i}: {inv['lines'][i]['description']} (unit {inv['lines'][i]['unit_price_minor']} minor {inv.get('currency')})" for i in need)
            valid = {g["code"] for g in chart.get("gl_accounts", [])}
            valid_cc = {c["code"] for c in chart.get("cost_centers", [])}
            try:
                res = await _llm(state, "gl_coding", {"chart": chart_txt, "vendor": f"{vendor.get('name', inv.get('vendor_name'))} (default cost center {vendor.get('cost_center')})", "lines": lines_txt})
                for gl in res.parsed.lines if res.parsed else []:
                    if gl.line_index in need:
                        ok = gl.gl_account in valid and gl.cost_center in valid_cc
                        coded[gl.line_index] = {"line_index": gl.line_index, "gl_account": gl.gl_account if ok else None,
                                                "cost_center": gl.cost_center if ok else vendor.get("cost_center"),
                                                "confidence": 0.8 if ok else 0.0, "source": res.model, "rationale": gl.rationale}
            except Exception as exc:  # noqa: BLE001
                for i in need:
                    coded[i] = {"line_index": i, "gl_account": None, "cost_center": vendor.get("cost_center"), "confidence": 0.0,
                                "source": "error", "rationale": f"GL coding unavailable: {type(exc).__name__}"}
    for i, c in enumerate(coded):
        if not c:
            coded[i] = {"line_index": i, "gl_account": None, "cost_center": vendor.get("cost_center"), "confidence": 0.0, "source": "none", "rationale": "not coded"}
    low = [c["line_index"] for c in coded if c["confidence"] < 0.6]
    return {"gl_coding": coded, "_summary": f"{len(coded) - len(need)} from PO, {len(need)} proposed" + (f"; {len(low)} low confidence" if low else "")}


POLICY_QUERIES = {
    "price_variance": "invoice unit price tolerance PO price variance",
    "qty_variance": "billed quantity must not exceed received quantity",
    "no_po": "invoices without a purchase order utilities contract",
    "no_receipt": "goods receipt three-way match quantity received",
    "BANK_ACCOUNT_MISMATCH": "bank details change controller call-back",
    "DUPLICATE_EXACT": "duplicate invoice same vendor invoice number",
    "DUPLICATE_SUSPECTED": "suspected duplicate amount date similar number",
    "INJECTION_DETECTED": "instructions inside documents hidden text blocked",
    "CREDIT_NOTE": "credit notes never scheduled for payment",
    "approval": "approval matrix approver controller limits",
    "TAX_MISMATCH": "tax mismatch expected rate",
}


@node("policy_check")
async def policy_check(state: RunState) -> dict[str, Any]:
    from app.rag.embeddings import get_embedder, get_reranker
    from app.rag.service import search

    d = _deps(state)
    topics = {f["code"] for f in state.get("flags", []) if f["code"] in POLICY_QUERIES}
    topics |= {m["outcome"] for m in state.get("match", {}).get("lines", []) if m["outcome"] in POLICY_QUERIES}
    topics.add("approval")
    p = Principal(user_id=d.actor_id, org_id=d.org_id, roles=frozenset({"system"}))
    findings: list[dict[str, Any]] = []
    try:
        emb, rr = get_embedder(), get_reranker()
        for t in sorted(topics)[:5]:
            hits = await search(p, POLICY_QUERIES[t], embedder=emb, reranker=rr, top_k=1)
            for h in hits:
                findings.append({"topic": t, "chunk_id": h.chunk_id, "document": h.filename, "heading": h.heading,
                                 "snippet": h.text[:400]})
    except Exception as exc:  # noqa: BLE001
        findings.append({"topic": "unavailable", "error": type(exc).__name__})
    return {"policy_findings": findings, "_summary": f"{len([f for f in findings if 'chunk_id' in f])} policy citation(s)",
            "_evidence": [{"type": "policy_chunk", "id": f["chunk_id"]} for f in findings if "chunk_id" in f]}


@node("risk_route")
async def risk_route(state: RunState) -> dict[str, Any]:
    from app.domain.matching import LineMatch, MatchResult

    inv, md = state["invoice"], state.get("match", {})
    flags = [Flag(f["code"], f.get("evidence", {}), f["message"]) for f in state.get("flags", [])]
    mr = None
    if md:
        mr = MatchResult(
            lines=[LineMatch(m["index"], LineOutcome(m["outcome"]), notes=m["notes"]) for m in md["lines"]],
            header_ok=md["header_ok"], invoice_subtotal_minor=0, expected_total_minor=0, over_billed=[])
    base = _to_base(abs(inv.get("total_minor") or 0), inv.get("currency"))
    dec = decide(amount_base_minor=base, flags=flags, match=mr, matrix=ApprovalMatrix(), errors=state.get("errors") or None,
                 missing_po_allowed=md.get("missing_po_allowed", False))
    route = dec.route
    reasons = list(dec.reasons)
    forced = sorted({f.code for f in flags} & EXCEPTION_FLAGS)
    if forced and route != Route.EXCEPTION:
        route = Route.EXCEPTION
        reasons.append("exception flags: " + ", ".join(forced))
    if inv.get("path") == "vision" and route == Route.AUTO:
        route = Route.APPROVAL
        reasons.append("scanned document: human review required")
    level = dec.approval.level.value if dec.approval else None
    if route == Route.APPROVAL and (not dec.approval or dec.approval.level == Level.AUTO):
        level = Level.APPROVER.value
    risk = {"score": dec.score, "level": dec.level, "reasons": reasons, "required_role": level if route == Route.APPROVAL else None,
            "callback_required": bool(dec.approval and dec.approval.callback_verification), "amount_base_minor": base}
    await _upsert_invoice(state, route.value, risk)
    return {"risk": risk, "route": route.value, "_summary": f"route={route.value} score={dec.score} ({dec.level})" + (f" → {level}" if route == Route.APPROVAL else "")}


async def _upsert_invoice(state: RunState, route: str, risk: dict[str, Any]) -> None:
    d = _deps(state)
    inv, vendor = state["invoice"], state.get("vendor", {})
    async with tenant_tx(d.org_id) as s:
        iid = (await s.execute(text(
            "INSERT INTO ap.invoices (org_id, run_id, document_id, doc_type, vendor_id, vendor_name, invoice_number, invoice_number_norm,"
            " invoice_date, due_date, currency, subtotal_minor, tax_minor, total_minor, po_number, bank_last4, status, risk_score, risk_level, route)"
            " VALUES (:o,:r,:doc,:dt,:v,:vn,:n,:nn,:idate,:ddate,:c,:sub,:tax,:tot,:po,:l4,:st,:rs,:rl,:route)"
            " ON CONFLICT (run_id) DO UPDATE SET status=EXCLUDED.status, risk_score=EXCLUDED.risk_score, risk_level=EXCLUDED.risk_level, route=EXCLUDED.route"
            " RETURNING id"),
            {"o": d.org_id, "r": d.run_id, "doc": state["document_id"], "dt": inv.get("doc_type"), "v": vendor.get("id"),
             "vn": vendor.get("name") or inv.get("vendor_name"), "n": inv.get("invoice_number"),
             "nn": normalize_invoice_number(inv["invoice_number"]) if inv.get("invoice_number") else None,
             "idate": date.fromisoformat(inv["invoice_date"]) if inv.get("invoice_date") else None,
             "ddate": date.fromisoformat(inv["due_date"]) if inv.get("due_date") else None,
             "c": inv.get("currency"), "sub": inv.get("subtotal_minor"), "tax": inv.get("tax_minor"), "tot": inv.get("total_minor"),
             "po": inv.get("po_number"), "l4": inv.get("bank_account_last4"), "st": route, "rs": risk.get("score"),
             "rl": risk.get("level"), "route": route})).scalar_one()
        await s.execute(text("DELETE FROM ap.invoice_lines WHERE invoice_id = :i"), {"i": iid})
        gl = {c["line_index"]: c for c in state.get("gl_coding", [])}
        outcomes = {m["index"] - 1: m["outcome"] for m in state.get("match", {}).get("lines", [])}
        for i, ln in enumerate(inv["lines"]):
            g = gl.get(i, {})
            await s.execute(text(
                "INSERT INTO ap.invoice_lines (org_id, invoice_id, line_no, description, quantity, uom, unit_price_minor, amount_minor,"
                " gl_account, cost_center, gl_confidence, match_outcome) VALUES (:o,:i,:n,:d,:q,:u,:p,:a,:gl,:cc,:gc,:mo)"),
                {"o": d.org_id, "i": iid, "n": i + 1, "d": ln["description"], "q": ln["quantity"], "u": ln["uom"],
                 "p": ln["unit_price_minor"], "a": ln["amount_minor"], "gl": g.get("gl_account"), "cc": g.get("cost_center"),
                 "gc": str(g.get("confidence")) if g else None, "mo": outcomes.get(i)})


def approval_packet(state: RunState) -> dict[str, Any]:
    inv = state["invoice"]
    return {"run_id": state["run_id"], "vendor_id": state.get("vendor", {}).get("id"), "invoice_number": inv.get("invoice_number"),
            "total_minor": inv.get("total_minor"), "currency": inv.get("currency"), "bank_last4": inv.get("bank_account_last4"),
            "flags": sorted(f["code"] for f in state.get("flags", [])), "required_role": state["risk"]["required_role"],
            "match": [m["outcome"] for m in state.get("match", {}).get("lines", [])]}


@node("human_approval")
async def human_approval(state: RunState) -> dict[str, Any]:
    d = _deps(state)
    packet = approval_packet(state)
    phash = sha256_json(packet)
    step = 1 + len(state.get("approvals", []))
    async with tenant_tx(d.org_id) as s:
        await s.execute(text(
            "INSERT INTO ap.approvals (org_id, run_id, step, required_role, packet_hash, packet, due_at)"
            " VALUES (:o,:r,:s,:role,:h,CAST(:p AS jsonb), now() + make_interval(hours => :sla))"
            " ON CONFLICT (run_id, step) DO NOTHING"),
            {"o": d.org_id, "r": d.run_id, "s": step, "role": packet["required_role"], "h": phash, "p": json.dumps(packet),
             "sla": get_settings().approval_sla_hours})
        await s.execute(text("UPDATE ap.runs SET status = 'awaiting_approval' WHERE id = :r"), {"r": d.run_id})
    await d.emitter.emit("interrupt", "human_approval", packet=packet, packet_hash=phash, step=step,
                         callback_required=state["risk"].get("callback_required", False))
    decision = interrupt({"packet": packet, "packet_hash": phash, "step": step})
    # Resumed: the API already enforced SoD, role and limits at decision time and verified the
    # packet hash. Re-check the facts the approval was bound to (bank details may have changed).
    approvals = [*state.get("approvals", []), {**decision, "step": step, "packet_hash": phash}]
    if decision.get("decision") == "approve" and state.get("vendor", {}).get("id") and state["invoice"].get("bank_account"):
        inv = state["invoice"]
        bank = await _tool(state, "compare_bank_account", {"vendor_id": state["vendor"]["id"], "routing": inv["bank_routing"], "account_number": inv["bank_account"]})
        if bool(bank.get("matches_current")) != ("BANK_ACCOUNT_MISMATCH" not in packet["flags"]):
            return {"approvals": approvals, "status": "needs_reapproval", "_summary": "facts changed after approval: re-approval required"}
    status = {"approve": "approved", "reject": "rejected", "request_info": "exception"}[decision["decision"]]
    upd: dict[str, Any] = {"approvals": approvals, "status": status, "_summary": f"{decision['decision']} by {decision.get('approver_id')}"}
    if status == "exception":
        upd["route"] = Route.EXCEPTION.value
    return upd


@node("post_and_schedule")
async def post_and_schedule(state: RunState) -> dict[str, Any]:
    d = _deps(state)
    inv, vendor, route = state["invoice"], state.get("vendor", {}), state["route"]
    po_lines = [] if state["doc"].get("demo_key") else [
        {"po_number": m["po_number"], "line_no": m["po_line"], "quantity": m["invoice_qty"]}
        for m in state.get("match", {}).get("lines", []) if m.get("po_number") and m.get("po_line")]
    post = await _tool(state, "post_invoice", {"idempotency_key": f"{d.run_id}:post", "vendor_id": vendor.get("id"),
                                               "invoice_number": inv["invoice_number"], "amount_minor": inv["total_minor"],
                                               "currency": inv["currency"], "route": route, "po_lines": po_lines}, route=route)
    if "error" in post:
        return {"errors": [*state.get("errors", []), f"post_invoice: {post['error']['code']}"], "_summary": "post failed"}
    due = inv.get("due_date") or (date.today() + timedelta(days=int(vendor.get("payment_terms_days") or 30))).isoformat()
    pay: dict[str, Any] = {}
    if inv["doc_type"] != "credit_note" and (inv.get("total_minor") or 0) > 0:
        pay = await _tool(state, "schedule_payment", {"idempotency_key": f"{d.run_id}:pay", "erp_ref": post["erp_ref"],
                                                      "amount_minor": inv["total_minor"], "currency": inv["currency"],
                                                      "due_date": due, "route": route, "approval_token": d.approval_token}, route=route)
        if "error" in pay:
            return {"errors": [*state.get("errors", []), f"schedule_payment: {pay['error']['code']}"], "_summary": f"payment refused: {pay['error']['code']}"}
    async with tenant_tx(d.org_id) as s:
        await s.execute(text(
            "INSERT INTO ap.postings (org_id, run_id, idempotency_key, erp_ref, payment_ref, amount_minor, currency)"
            " VALUES (:o,:r,:k,:e,:p,:a,:c) ON CONFLICT (run_id) DO NOTHING"),
            {"o": d.org_id, "r": d.run_id, "k": f"{d.run_id}:post", "e": post["erp_ref"], "p": pay.get("payment_ref"),
             "a": inv["total_minor"], "c": inv["currency"]})
    return {"posting": {"erp_ref": post["erp_ref"], "payment_ref": pay.get("payment_ref"), "due_date": due,
                        "replayed": bool(post.get("replayed"))}, "status": "posted",
            "_summary": f"posted {post['erp_ref']}" + (f", payment {pay['payment_ref']} due {due}" if pay else ""),
            "_evidence": [{"type": "erp_posting", "id": post["erp_ref"]}]}


@node("finalize")
async def finalize(state: RunState) -> dict[str, Any]:
    d = _deps(state)
    errors = state.get("errors", [])
    route = state.get("route") or Route.EXCEPTION.value
    status = state.get("status") or ""
    if errors and status != "posted":
        status, route = "exception", Route.EXCEPTION.value
    elif state.get("blocked"):
        status = "blocked"
    elif route == Route.EXCEPTION.value and status not in ("exception",):
        status = "exception"
    elif status not in ("posted", "rejected", "exception", "blocked"):
        status = "exception" if route == Route.EXCEPTION.value else status or "exception"
    exc_info: dict[str, Any] = {}
    if status in ("exception", "blocked"):
        exc_info = await _exception(state, status, errors)
    flags = state.get("flags", [])
    async with tenant_tx(d.org_id) as s:
        await s.execute(text("DELETE FROM ap.flags WHERE run_id = :r"), {"r": d.run_id})
        for f in flags:
            await s.execute(text("INSERT INTO ap.flags (org_id, run_id, code, severity, message, evidence) VALUES (:o,:r,:c,:s,:m,CAST(:e AS jsonb))"),
                            {"o": d.org_id, "r": d.run_id, "c": f["code"], "s": f["severity"], "m": f["message"][:500], "e": json.dumps(f.get("evidence", {}), default=str)})
        costs = state.get("costs", {})
        await s.execute(text(
            "UPDATE ap.runs SET status=:st, route=:route, outcome=:out, tokens=:tok, est_cost_microusd=:cost,"
            " latency_ms = (extract(epoch FROM now() - created_at) * 1000)::int, finished_at=now(), error=:err,"
            " state = CAST(:state AS jsonb) WHERE id=:r"),
            {"st": status, "route": route, "out": status, "tok": costs.get("tokens", 0), "cost": costs.get("est_usd_micros", 0),
             "err": "; ".join(errors)[:1000] or None, "r": d.run_id,
             "state": json.dumps(public_state(state, status, route, exc_info), default=str)})
        await s.execute(text("UPDATE ap.invoices SET status=:st, route=:route WHERE run_id=:r"), {"st": status, "route": route, "r": d.run_id})
    return {"status": status, "route": route, "exception": exc_info, "_summary": f"{status} (route {route})"}


async def _exception(state: RunState, status: str, errors: list[str]) -> dict[str, Any]:
    d = _deps(state)
    flags = state.get("flags", [])
    md = state.get("match", {})
    if status == "blocked":
        etype, reason = "security", "Document contains hidden text or instructions addressed to an AI system"
    elif errors:
        etype, reason = "processing_error", "; ".join(errors)[:500]
    else:
        bad = [m for m in md.get("lines", []) if m["outcome"] != "matched"]
        codes = {f["code"] for f in flags} & EXCEPTION_FLAGS
        etype = bad[0]["outcome"] if bad else (sorted(codes)[0].lower() if codes else "review")
        reason = "; ".join(state.get("risk", {}).get("reasons", [])) or etype
    facts = {"vendor": state.get("vendor", {}).get("name") or state.get("invoice", {}).get("vendor_name"),
             "invoice_number": state.get("invoice", {}).get("invoice_number"), "currency": state.get("invoice", {}).get("currency"),
             "issue": etype, "reason": reason,
             "lines": [{k: m[k] for k in ("index", "outcome", "invoice_unit_price_minor", "po_unit_price_minor", "price_diff_minor",
                                          "price_tolerance_minor", "invoice_qty", "available_qty")} for m in md.get("lines", []) if m["outcome"] != "matched"]}
    explanation = _template_explanation(facts)
    email = None
    if status != "blocked" and etype != "processing_error":
        email = _template_email(facts)
        if not _fake(state):
            try:
                explanation = (await _llm(state, "explain_match", {"facts": json.dumps(facts)})).text.strip()[:1500]
                email = (await _llm(state, "draft_vendor_email", {"facts": json.dumps(facts)})).text.strip()[:2000]
            except Exception:  # noqa: BLE001 - templates already set
                pass
    async with tenant_tx(d.org_id) as s:
        await s.execute(text(
            "INSERT INTO ap.exceptions (org_id, run_id, type, reason, explanation, drafted_email) VALUES (:o,:r,:t,:re,:ex,:em)"
            " ON CONFLICT (run_id) DO UPDATE SET type=EXCLUDED.type, reason=EXCLUDED.reason, explanation=EXCLUDED.explanation,"
            " drafted_email=EXCLUDED.drafted_email, status='open'"),
            {"o": d.org_id, "r": d.run_id, "t": etype, "re": reason[:1000], "ex": explanation, "em": email})
    return {"type": etype, "reason": reason, "explanation": explanation, "drafted_email": email}


def _money(minor: Any, cur: str | None) -> str:
    if minor is None:
        return "?"
    return f"{int(minor) / 100:,.2f} {cur or ''}".strip()


def _template_explanation(f: dict[str, Any]) -> str:
    parts = [f"Invoice {f['invoice_number']} from {f['vendor']} needs attention: {f['issue'].replace('_', ' ')}."]
    for ln in f["lines"]:
        if ln["outcome"] == "price_variance":
            parts.append(f"Line {ln['index']}: unit price {_money(ln['invoice_unit_price_minor'], f['currency'])} vs PO "
                         f"{_money(ln['po_unit_price_minor'], f['currency'])}, a difference of {_money(ln['price_diff_minor'], f['currency'])} "
                         f"above the allowed {_money(ln['price_tolerance_minor'], f['currency'])}.")
        elif ln["outcome"] in ("qty_variance", "no_receipt"):
            parts.append(f"Line {ln['index']}: billed quantity {ln['invoice_qty']} exceeds received quantity {ln['available_qty'] or 0}.")
        else:
            parts.append(f"Line {ln['index']}: {ln['outcome'].replace('_', ' ')}.")
    return " ".join(parts)


def _template_email(f: dict[str, Any]) -> str:
    return (f"Hello,\n\nWe could not process invoice {f['invoice_number']}. {_template_explanation(f)}\n\n"
            "Please send a corrected invoice or a credit note for the difference.\n\nThank you,\nAccounts Payable")


def public_state(state: RunState, status: str, route: str, exc: dict[str, Any]) -> dict[str, Any]:
    inv = dict(state.get("invoice", {}))
    inv.pop("bank_account", None)
    inv.pop("bank_routing", None)
    return {"status": status, "route": route, "invoice": inv, "vendor": state.get("vendor", {}), "match": state.get("match", {}),
            "gl_coding": state.get("gl_coding", []), "policy_findings": state.get("policy_findings", []),
            "flags": state.get("flags", []), "risk": state.get("risk", {}), "approvals": state.get("approvals", []),
            "posting": state.get("posting", {}), "exception": exc, "timings": state.get("timings", {}),
            "costs": state.get("costs", {}), "errors": state.get("errors", []),
            "doc": {k: v for k, v in state.get("doc", {}).items() if k != "text"}}


# ---------------------------------------------------------------------------- wiring
def _after_intake(state: RunState) -> str:
    return "finalize" if state.get("blocked") else "extract"


def _after_risk(state: RunState) -> str:
    if state.get("errors") or state["route"] == Route.EXCEPTION.value:
        return "finalize"
    return "human_approval" if state["route"] == Route.APPROVAL.value else "post_and_schedule"


def _after_approval(state: RunState) -> str:
    st = state.get("status")
    if st == "approved":
        return "post_and_schedule"
    if st == "needs_reapproval":
        return "human_approval"
    return "finalize"


def _guard_errors(nxt: str):  # type: ignore[no-untyped-def]
    def route(state: RunState) -> str:
        return "finalize" if state.get("errors") else nxt
    return route


def build_graph():  # type: ignore[no-untyped-def]
    g = StateGraph(RunState)
    for fn in (intake_guard, extract, validate, vendor_verify, match, code_gl, policy_check, risk_route,
               human_approval, post_and_schedule, finalize):
        g.add_node(fn.__name__, fn)
    g.add_edge(START, "intake_guard")
    g.add_conditional_edges("intake_guard", _after_intake, ["extract", "finalize"])
    g.add_conditional_edges("extract", _guard_errors("validate"), ["validate", "finalize"])
    g.add_conditional_edges("validate", _guard_errors("vendor_verify"), ["vendor_verify", "finalize"])
    g.add_edge("vendor_verify", "match")
    g.add_edge("match", "code_gl")
    g.add_edge("code_gl", "policy_check")
    g.add_edge("policy_check", "risk_route")
    g.add_conditional_edges("risk_route", _after_risk, ["human_approval", "post_and_schedule", "finalize"])
    g.add_conditional_edges("human_approval", _after_approval, ["post_and_schedule", "human_approval", "finalize"])
    g.add_edge("post_and_schedule", "finalize")
    g.add_edge("finalize", END)
    return g
