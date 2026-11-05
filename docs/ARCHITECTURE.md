# Architecture

Status: **Phase 0** (foundation). Target architecture: [AURA_BUILD_PROMPT.md §B2](../AURA_BUILD_PROMPT.md).

```
Browser ──▶ Vercel (iad1), one project, Services routing
            ├─ /api/v1/*, /mcp*  ─▶ api  (FastAPI, Python 3.12, Fluid compute)
            └─ everything else    ─▶ web  (Next.js 16, Better Auth at /api/auth/*)

api ──▶ Neon Postgres (pooled)   schemas core, ai, kb (+ ap, audit, ops reserved), RLS for aura_app
    ──▶ Upstash Redis (REST)     rate limits, budgets, token buckets, exact LLM cache
    ──▶ Groq / Gemini            via the model router (LiteLLM)
    ──▶ Vercel Blob (private)    knowledge files
    ──▶ Langfuse Cloud           optional, masked trace export
web ──▶ Neon Postgres            schema auth (Better Auth)
```

## Request path (Phase 0)

1. The browser gets a 15-minute EdDSA JWT from `GET /api/auth/token` (session cookie).
2. It calls `/api/v1/*` with `Authorization: Bearer …`. Middleware assigns `X-Request-ID`, enforces the 12 MB body limit and adds security headers.
3. The per-IP rate limiter and, for LLM-backed calls, the daily budget governor each cost one Redis command.
4. Handlers open `tenant_tx(org_id)`, so RLS scopes every query.
5. LLM work goes through the router; each attempt writes `ai.llm_calls`, each request span writes `ai.traces`.

## Code map

| Path | What |
|---|---|
| `apps/api/app/core` | settings, logging, errors, middleware, DB/RLS, auth, store, limits |
| `apps/api/app/llm` | router, `tasks.yaml`, providers, faults, geo gate, telemetry |
| `apps/api/app/prompts` | registry + `defaults.yaml` seed |
| `apps/api/app/rag` | extraction, chunking, embeddings, hybrid search, citations |
| `apps/api/app/monitoring` | tracing |
| `apps/api/alembic` | migrations |
| `apps/web/src` | Next.js app, Better Auth config, pages |
| `legacy/` | previous app, kept for porting only (ADR-000) |
