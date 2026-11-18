"""Record and replay provider responses for deterministic CI (§B10).

`ROUTER_CASSETTE_MODE=record` writes one JSON file per request into `evals/cassettes/`;
`replay` serves those files and never touches a provider — a request with no cassette fails
loudly rather than falling through to the network, so a PR-tier run can never quietly spend
quota or depend on a live model.

The key covers everything that changes a response: model, messages, temperature, max_tokens and
JSON mode. Prompt text is part of the key, so editing a prompt invalidates its cassettes —
which is the point: the recorded answer no longer corresponds to the request.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.llm.providers import ProviderError, ProviderRequest, ProviderResponse, Transport

log = get_logger("cassettes")

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "evals" / "cassettes"


def key(req: ProviderRequest) -> str:
    blob = json.dumps(
        {
            "model": req.model,
            "messages": req.messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "json_mode": req.json_mode,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


@dataclass
class CassetteTransport:
    """Wrap a transport with record/replay. `mode` is 'record', 'replay' or 'off'."""

    inner: Transport
    mode: str = "off"
    directory: Path = DEFAULT_DIR

    def path_for(self, req: ProviderRequest) -> Path:
        provider = req.model.split("/", 1)[0]
        return self.directory / provider / f"{key(req)}.json"

    async def __call__(self, req: ProviderRequest) -> ProviderResponse:
        if self.mode == "off":
            return await self.inner(req)
        path = self.path_for(req)
        if self.mode == "replay":
            if not path.exists():
                raise ProviderError(
                    "not_configured",
                    f"no cassette for {req.model} ({path.name}); record it or use fake/*",
                )
            data = json.loads(path.read_text(encoding="utf-8"))
            return ProviderResponse(
                text=data["text"],
                tokens_in=int(data.get("tokens_in", 0)),
                tokens_out=int(data.get("tokens_out", 0)),
                raw_model=data.get("raw_model"),
            )
        response = await self.inner(req)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "model": req.model,
                    "text": response.text,
                    "tokens_in": response.tokens_in,
                    "tokens_out": response.tokens_out,
                    "raw_model": response.raw_model,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        log.info("cassette.recorded", model=req.model, file=path.name)
        return response


def wrap(inner: Transport, mode: str, directory: str | None = None) -> Transport:
    if mode not in ("record", "replay"):
        return inner
    return CassetteTransport(inner, mode, Path(directory) if directory else DEFAULT_DIR)
