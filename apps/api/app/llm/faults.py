"""Non-production fault injection, e.g. ROUTER_FAULT_INJECTION="groq/*=429,gemini/*=timeout"."""

from __future__ import annotations

import fnmatch

from app.llm.providers import ErrorKind, ProviderError

_CODES: dict[str, ErrorKind] = {
    "429": "rate_limited",
    "500": "server_error",
    "503": "server_error",
    "timeout": "timeout",
}


def parse_faults(spec: str) -> dict[str, ErrorKind]:
    out: dict[str, ErrorKind] = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        pattern, _, code = part.partition("=")
        if code.strip() in _CODES:
            out[pattern.strip()] = _CODES[code.strip()]
    return out


def maybe_inject(model: str, faults: dict[str, ErrorKind]) -> None:
    for pattern, kind in faults.items():
        if fnmatch.fnmatch(model, pattern):
            raise ProviderError(kind, "injected")
