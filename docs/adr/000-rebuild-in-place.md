# ADR-000: Rebuild AURA in the existing repository

- **Status:** accepted
- **Date:** 2026-11-04

## Context

`AURA_BUILD_PROMPT.md` assumes an empty repository. This repository (`NelsonNpinto/Aura`) already held a local-first AI evaluation platform (Vite frontend, FastAPI backend, Ollama) with useful pieces: deterministic checks, an LLM judge with unscored-on-failure semantics, a RAGAS adapter, human calibration (kappa), webhook ingestion with idempotency, and a prompt registry.

## Decision

The human chose to rebuild in place on branch `rebuild/finance-ops`. The previous application moved, with history, to `legacy/`. It is not built, tested or deployed. Code is ported into the §B3 layout when a phase needs it (evaluation toolkit mostly in Phase 3), then `legacy/` is deleted.

## Consequences

- One repository and one GitHub history.
- `legacy/` adds noise to searches; CI ignores it.
- The old Vercel project config (`legacy/vercel.json`) no longer applies; a new config is written in task 0.10.
