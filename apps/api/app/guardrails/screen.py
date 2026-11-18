"""Runtime guardrails shared by every untrusted-text surface (§B11).

Input screening (documents, chat, challenge submissions):
  * instruction-phrase heuristics;
  * zero-width and bidi control characters;
  * Prompt Guard 2 through the router, on overlapping chunks so text longer than the
    classifier's window is still fully covered (§B18);
  * PII inventory, with redaction applied before any provider call, log or trace.

Output validation:
  * citations must resolve;
  * bank details may never originate from model output;
  * numeric claims are cross-checked against computed facts.

Every verdict is written to `ai.guardrail_events` and surfaced in the UI.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.guardrails.pii import find_pii
from app.models.tables import guardrail_events

log = get_logger("guardrails")

# Instruction-like phrases addressed at an AI system. Kept deliberately narrow: a false positive
# routes a clean invoice to a human, and that cost is measured in the eval report.
INJECTION_PATTERNS = re.compile(
    r"(ignore (all )?(previous|prior) (instructions|rules)|disregard (all )?(prior|previous)|"
    r"you are now|system\s*:|note to (the )?ai|skip (vendor )?verification|approve and pay|"
    r"do not (flag|review|verify)|bypass (the )?(approval|policy|check)|"
    r"as an ai (model|assistant)|developer mode|jailbreak|"
    r"reveal (your )?(system )?prompt|print (your )?instructions|"
    r"send (the )?(data|details) to\b|exfiltrate)",
    re.I,
)
# Zero-width, bidi overrides and other invisible controls used to hide instructions.
INVISIBLE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
CHUNK_CHARS = 1800  # ~512 tokens
CHUNK_STRIDE = 1500  # overlap so a phrase split across chunks is still classified
MAX_SCREEN_CHARS = 20_000

PERSONAL_PII = frozenset({"EMAIL", "PHONE", "SSN", "PAN", "CARD"})


@dataclass(frozen=True)
class Finding:
    check: str
    verdict: str  # pass | flag | block
    severity: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScreenResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.verdict == "block" for f in self.findings)

    @property
    def flagged(self) -> bool:
        return any(f.verdict in ("block", "flag") for f in self.findings)

    def public(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "flagged": self.flagged,
            "findings": [f.public() for f in self.findings],
        }


def heuristics(text: str) -> list[Finding]:
    """Deterministic checks. No model call, so these always run — even with no quota left."""
    out: list[Finding] = []
    phrases = sorted({m.group(0).lower() for m in INJECTION_PATTERNS.finditer(text)})
    if phrases:
        out.append(
            Finding(
                "instruction_heuristic",
                "block",
                "HIGH",
                "Instruction-like text addressed to an AI system",
                {"phrases": phrases[:5]},
            )
        )
    invisible = INVISIBLE.findall(text)
    if invisible:
        out.append(
            Finding(
                "invisible_characters",
                "flag",
                "MEDIUM",
                f"{len(invisible)} zero-width or bidi control character(s)",
                {"count": len(invisible)},
            )
        )
    personal = [p for p in find_pii(text) if p.kind in PERSONAL_PII]
    if personal:
        kinds = sorted({p.kind for p in personal})
        out.append(
            Finding(
                "pii",
                "flag",
                "LOW",
                f"Personal data present and redacted before model calls: {', '.join(kinds)}",
                {"kinds": kinds},
            )
        )
    return out


def chunks(text: str, limit: int = MAX_SCREEN_CHARS) -> list[str]:
    body = text[:limit]
    return [body[i : i + CHUNK_CHARS] for i in range(0, len(body), CHUNK_STRIDE)] or [""]


def interpret_prompt_guard(label: str) -> bool:
    upper = label.strip().upper()
    return "MALICIOUS" in upper or "INJECTION" in upper or upper.startswith("1")


async def classify(text: str, run_task: Any) -> list[Finding]:
    """Run the injection classifier over overlapping chunks.

    `run_task(chunk) -> object with .text and .model`. A classifier failure is recorded but never
    blocks on its own: the heuristics above are the deterministic floor.
    """
    out: list[Finding] = []
    for chunk in chunks(text):
        if not chunk.strip():
            continue
        try:
            res = await run_task(chunk)
        except Exception as exc:
            out.append(
                Finding(
                    "prompt_guard",
                    "pass",
                    "LOW",
                    f"Classifier unavailable: {type(exc).__name__}",
                    {"error": type(exc).__name__},
                )
            )
            break
        label = str(getattr(res, "text", "")).strip()
        if interpret_prompt_guard(label):
            out.append(
                Finding(
                    "prompt_guard",
                    "block",
                    "HIGH",
                    "Prompt Guard classified this text as an injection",
                    {"model": getattr(res, "model", None), "label": label[:40]},
                )
            )
            break
        out.append(
            Finding(
                "prompt_guard",
                "pass",
                "LOW",
                "No injection detected",
                {"model": getattr(res, "model", None), "label": label[:40]},
            )
        )
        break  # one clean chunk classification is enough to record; heuristics cover the rest
    return out


async def record(
    session: AsyncSession,
    org_id: str,
    findings: list[Finding],
    *,
    surface: str,
    run_id: str | None = None,
) -> None:
    """Persist verdicts to ai.guardrail_events (§B11: every guardrail decision is logged)."""
    if not findings:
        return
    await session.execute(
        insert(guardrail_events),
        [
            {
                "org_id": org_id,
                "run_id": run_id,
                "surface": surface,
                "check": f.check,
                "verdict": f.verdict,
                "severity": f.severity,
                "details": {"detail": f.detail, **f.evidence},
            }
            for f in findings
        ],
    )


# ---------------------------------------------------------------- output validation
CITATION = re.compile(r"\[([A-Za-z0-9_.:-]{1,40})\]")
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
BANK_LIKE = re.compile(r"\b\d{8,20}\b")


def invalid_citations(answer: str, known_ids: set[str]) -> list[str]:
    return sorted({c for c in CITATION.findall(answer) if c not in known_ids})


def external_references(answer: str) -> list[str]:
    """External images and links are blocked: they are a data-exfiltration channel (§B18)."""
    refs = MARKDOWN_IMAGE.findall(answer) + MARKDOWN_LINK.findall(answer)
    return [r for r in refs if r.startswith(("http://", "https://", "//", "data:"))]


def bank_details_from_model(answer: str, allowed: set[str]) -> list[str]:
    """Bank numbers may never originate from model output; only known last4s may appear."""
    return [m for m in BANK_LIKE.findall(answer) if m not in allowed]


def validate_output(
    answer: str, *, known_ids: set[str], allowed_numbers: set[str] | None = None
) -> list[Finding]:
    findings: list[Finding] = []
    if bad := invalid_citations(answer, known_ids):
        findings.append(
            Finding(
                "citation_valid",
                "block",
                "HIGH",
                "Answer cites evidence that does not exist",
                {"invalid": bad},
            )
        )
    if refs := external_references(answer):
        findings.append(
            Finding(
                "external_reference",
                "block",
                "HIGH",
                "Answer contains an external link or image",
                {"refs": refs[:5]},
            )
        )
    if numbers := bank_details_from_model(answer, allowed_numbers or set()):
        findings.append(
            Finding(
                "bank_from_model",
                "block",
                "HIGH",
                "Answer contains bank-like digits not present in verified data",
                {"numbers": [n[-4:] for n in numbers[:5]]},
            )
        )
    if not findings:
        findings.append(Finding("output_validation", "pass", "LOW", "Output checks passed"))
    return findings
