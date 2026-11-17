# Architecture

Two workflows share one runtime: an **invoice-to-pay agent** (LangGraph, risk-routed, human approvals) and a **purchasing workflow** (explicit evidence, mandatory L1 then finance review). Both run through the same model router, tool gateway, guardrails and hash-chained audit log.

```
Browser ──▶ Vercel (iad1), one project, Services routing
            ├─ /api/v1/*, /mcp*  ─▶ api  (FastAPI, Python 3.12, Fluid compute)
            └─ everything else    ─▶ web  (Next.js 16, Better Auth at /api/auth/*)

api ──▶ Neon Postgres (pooled)   schemas core, ai, kb, ap, audit, erp, ops — RLS for aura_app
    ──▶ Upstash Redis (REST)     rate limits, budgets, token buckets, exact LLM cache
    ──▶ Groq / Gemini            via the model router (LiteLLM)
    ──▶ Vercel Blob (private)    knowledge files
    ──▶ Langfuse Cloud           optional, masked trace export
    ──▶ Neo4j AuraDB Free        relationship and fraud checks; degrades to "unavailable"
    ──▶ HF ZeroGPU Space         fine-tuned GL coder; 18 s timeout then fallback
web ──▶ Neon Postgres            schema auth (Better Auth)
```

An MCP host can reach the same services at `/mcp` (stateless Streamable HTTP, per-user API
keys), and the mock ERP is itself an MCP server at `/erp/mcp` — the AP system never queries
schema `erp` directly.

## Request path

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
| `apps/api/app/agents` | LangGraph invoice-to-pay workflow and copilot |
| `apps/api/app/domain` | deterministic rules: matching, duplicates, approval matrix, SoD, risk |
| `apps/api/app/guardrails` | shared input screen, hidden-text detection, PII redaction, output validators |
| `apps/api/app/graph` | Neo4j client, constraints, outbox projection, query templates, Cypher guard |
| `apps/api/app/memory` | long-term memory store, write policy, TTL and decay |
| `apps/api/app/mcp_server` | AURA MCP server at `/mcp` |
| `apps/api/app/tools` | tool registry and gateway (policy enforcement point), MCP clients |
| `apps/api/app/audit` | hash-chained audit log and verification |
| `apps/api/app/evaluation` | checks library, judge, gates, baselines, red team, suites, report |
| `apps/api/app/monitoring` | tracing, drift |
| `apps/api/alembic` | migrations |
| `apps/web/src` | Next.js app, Better Auth config, pages |
| `services/erp-mock` | mock ERP behind MCP, owns schema `erp` |
| `evals/` | synthetic world generator, versioned datasets, cassettes, promptfoo pack |
| `ml/gl_coder` | dataset builder, leakage checks, Unsloth QLoRA trainer, baseline evaluator |
| `ml/specialist-space` | Gradio app serving the specialist on free ZeroGPU |
| `services/vendor-portal` | mock legacy portal (no API) + the Playwright browser agent |
| `infra/` | Dockerfiles, Helm chart, Terraform (plan-only), k6 load profile |
