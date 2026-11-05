# AURA — Auditable, Unified, Reliable Agents

A live, publicly demoable finance-operations AI platform on a **$0 free-tier stack**: an invoice-to-pay multi-agent workflow, a finance copilot, and a trust layer (guardrails, evals, observability, audit lineage, human-in-the-loop).

> **Status:** foundation and the original invoice agent are deployed at https://aura-henna-one.vercel.app. New Purchasing, Copilot and AI Quality implementation is on `codex/procurement-workflow`; see [PROGRESS.md](PROGRESS.md) for rollout and remaining acceptance checks. All demo data is synthetic; no real payments.

## What works today

- Sign-up/login and a Turnstile-protected guest demo (Better Auth, organizations, roles).
- FastAPI with JWT/JWKS auth, hashed API keys, Postgres row-level security per org.
- Model router: Groq → Gemini fallbacks, token buckets, exact cache, structured outputs, geo gate, per-attempt telemetry.
- Prompt registry with immutable versions and audited labels.
- Knowledge base: upload, hybrid pgvector + full-text search with RRF and cross-encoder rerank, cited answers with citation validation.
- Rate limits, daily demo budgets, tracing to `ai.traces` with optional Langfuse export.

Metrics: **not measured** until stored eval runs exist (Phase 1+).

## Quickstart (local)

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 22+.

```bash
cp .env.example .env.local          # then add any provider keys you have
make up                             # Postgres+pgvector, Redis, Upstash REST facade
make deps
make migrate && make seed
cd apps/web && npm run auth:migrate && cd ../..
make dev                            # api :8010, web :3000
```

Open http://localhost:3000 and choose **Try the live demo**. Without Groq/Gemini keys, LLM calls fall back to a local Ollama model if `OLLAMA_BASE_URL` is set.

On an exFAT external drive (macOS), keep the Python venv off the drive (`export UV_PROJECT_ENVIRONMENT=$HOME/.venvs/aura-api`) and delete `._*` files if tools complain.

## Docs

[Build spec](AURA_BUILD_PROMPT.md) · [Progress](PROGRESS.md) · [Architecture](docs/ARCHITECTURE.md) · [ADRs](docs/adr) · [Costs](docs/COSTS.md) · [Runbook](docs/RUNBOOK.md) · [Validation](VALIDATION.md)

## Limits (honest)

Demo on synthetic data; free-tier quotas cap usage; model answers can be wrong — citations are pointers, not proof. The previous AI-evaluation app lives in `legacy/` until its parts are ported.
## Implementation update

The current implementation branch adds **Purchasing**, **Copilot**, and **AI quality**. See [the purchasing walkthrough](docs/PROCUREMENT_GUIDE.md), [Gmail configuration](docs/GMAIL_SETUP.md), and [evaluation evidence and limitations](docs/EVALS.md). Deployment status and remaining phases are recorded in [PROGRESS.md](PROGRESS.md); branch implementation does not imply all phases are complete or deployed.
