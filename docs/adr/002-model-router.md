# ADR-002: In-process model router over LiteLLM

- **Status:** accepted
- **Date:** 2026-11-04

## Decision

All LLM calls go through `apps/api/app/llm/router.py`. Model names and chains live only in `tasks.yaml`.

Per call: resolve the prompt by label → render with spotlighting of untrusted variables → choose an A/B variant by a stable hash of `run_id` → filter the chain (geo, open-weight-only, local-only) → exact cache (Redis, temperature-0 tasks) → per-model token buckets (RPM, RPD, TPM and the org's daily tokens in **one** Lua EVAL) → provider call → Pydantic validation with one repair retry → fallback on 429/5xx/timeout/not-configured → one `ai.llm_calls` row per attempt.

- **Never wait** on an empty bucket: skip to the next model (Vercel's 300 s cap).
- Token cost is pre-charged with an upper bound (prompt chars/4 + `max_tokens`), so there is no second Redis command to reconcile.
- `fallback_reason` is `<model>:<kind>` of the previous failure.
- Fault injection (`ROUTER_FAULT_INJECTION="groq/*=429"`) is ignored in production.
- Costs are estimates at list price, stored as integer micro-USD.

## Consequences

- One door for models: providers are only touched in `providers.py`.
- The `fake/*` provider and scripted transports make router behaviour testable without network.
