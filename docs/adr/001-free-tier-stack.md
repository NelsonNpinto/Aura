# ADR-001: $0 free-tier stack

- **Status:** accepted
- **Date:** 2026-11-04

## Context

AURA must run live at $0/month (§B4) and still look like production: auth, Postgres with vectors, a cache/rate-limit store, tracing, LLMs, a graph, CI/CD.

## Decision

| Need | Choice | Why |
|---|---|---|
| Hosting | Vercel Hobby, **Services** (`web` Next.js + `api` FastAPI in one project) | One domain, shared env, no CORS; paths reach the service unchanged |
| Postgres + vectors | Neon Free + pgvector | Scales to zero; pooled URL for the app, direct URL for migrations |
| Counters, cache, limits | Upstash Redis over REST | Works from serverless functions; local dev uses `serverless-redis-http` so the same client runs everywhere |
| Embeddings + rerank | fastembed ONNX in-process (`bge-small-en-v1.5` 384-d, int8 `ms-marco-MiniLM-L-6-v2`) | No torch, no paid embedding API; models ship in the bundle |
| Files | Vercel Blob (private), local FS in dev | Never `list`; metadata in Postgres |
| Tracing | Langfuse Cloud Hobby (optional export) + `ai.traces` | Our own table stays authoritative |
| LLMs | Groq + Gemini free tiers via LiteLLM; local Ollama fallback only in dev | See ADR-002 |
| CI/CD | GitHub Actions (public repo) | Free minutes |

## Consequences

- **api bundle budget.** LiteLLM (~100 MB) + onnxruntime + models dominate. Measured locally on macOS 2026-11-04: deps 337 MB (after pruning LiteLLM's proxy UI), models 91 MB, total 428 MB. CI measures on Linux and fails above 450 MB. The fp32 reranker (91 MB) was replaced by its int8 build (23 MB) for this reason.
- Neon is never kept warm; first request after idle pays ~1 s.
- Gemini's free tier is skipped for EEA/CH/UK visitors (geo gate in the router).
- If Services (beta) misbehaves, fall back to two Vercel projects with CORS limited to the web origin (§B17).

## Alternatives considered

- Torch + sentence-transformers (previous app): breaks the bundle limit.
- External embedding API: costs money or adds a quota to manage.
