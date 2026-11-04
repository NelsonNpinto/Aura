# PROGRESS

Spec: [AURA_BUILD_PROMPT.md](AURA_BUILD_PROMPT.md). Mode: **auto** (stops at human checkpoints, failures, destructive actions).

## Current

- **Phase:** 0 — Foundation and first live deploy
- **Branch:** `rebuild/finance-ops` (rebuild of this repo, chosen by the human on 2026-11-04 over a new repo)
- **Last verified production deploy:** none yet for the rebuild. The previous product (AI eval platform) lives under `legacy/` for reference and code porting.

## Next step

Continue 0.3 API foundation → 0.5 router/prompt registry → 0.6 RAG → 0.8 Redis (all local-only, no accounts needed). Then 0.4/0.9 web, then 0.10 deploy once HC-1 and HC-2 are resolved.

## Open human checkpoints

### HC-1 — accounts and keys (OPEN)

Create these accounts. **Do not paste any secret into chat.** Put values in `.env.local` at the repo root (git-ignored); variable names are in `.env.example`.

| # | Service | What to create | Variables |
|---|---|---|---|
| 1 | GitHub | Repo `NelsonNpinto/Aura` exists. Make it public when ready (Actions minutes are free for public repos). | — |
| 2 | Vercel Hobby | Account linked to GitHub. | `VERCEL_TOKEN` (later, HC-2) |
| 3 | Neon Free | Project in **AWS US East (N. Virginia)**, Postgres 17. Copy pooled + direct URLs. Create branch `preview`. | `DATABASE_URL` (pooled), `DATABASE_URL_UNPOOLED` (direct) |
| 4 | Upstash Redis | Database, region **us-east-1**, free plan, no payment method. | `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` |
| 5 | Neo4j AuraDB Free | One free instance. Password is shown **once** — save it straight to `.env.local`. | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` |
| 6 | Langfuse Cloud | Hobby plan, **US region** (`https://us.cloud.langfuse.com`), project `aura`. | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` |
| 7 | Groq | API key at console.groq.com (free tier). | `GROQ_API_KEY` |
| 8 | Google AI Studio | Gemini API key on a project **without billing** enabled. | `GEMINI_API_KEY` |
| 9 | Cloudflare Turnstile | Widget, mode "Managed", hostnames `localhost` + your `*.vercel.app` domain. | `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` |
| 10 | Hugging Face | **Create now** — ZeroGPU needs the account ≥ 30 days old with verified email (usable ≈ 2026-12-04). | `HF_TOKEN` (Phase 4) |
| 11 | AWS (optional) | Free-plan account only, never upgrade. Skip unless you want Bedrock. | — |

Reply "HC-1 done" (listing which ones exist) when finished. Work continues locally meanwhile.

### HC-2 — deploy (pending, after HC-1)

You run: `npm i -g vercel`, `vercel login`, `vercel link` (in repo root), then add secrets with `vercel env add` / `gh secret set`. Exact list will be printed when we reach 0.10.

## Decisions

- [ADR-000](docs/adr/000-rebuild-in-place.md) — rebuild in this repo, old app kept in `legacy/` until ported.
- ADR-001/002/003 — written during Phase 0.

## Phase 0 plan

Dependencies (with reasons) are recorded per package in `apps/api/pyproject.toml` comments and ADRs. Versions checked on PyPI/npm on 2026-11-04.

| Task | Status | Owner | Files | Tests |
|---|---|---|---|---|
| 0.1 HC-1 checklist | printed, waiting on human | claude-code | PROGRESS.md | — |
| 0.2 Monorepo scaffold | in progress | claude-code | Makefile, .editorconfig, .pre-commit-config.yaml, docker-compose.yml, .env.example, docs/adr/ | `make lint` |
| 0.3 API foundation | pending | — | apps/api/app/{core,api,models}, alembic | health/ready, middleware, error model, RLS helper |
| 0.4 Auth + tenancy | pending | — | apps/web (Better Auth), apps/api/app/core/auth.py | JWT/JWKS verify, API keys, RLS cross-org test |
| 0.5 Router + prompt registry | pending | — | apps/api/app/llm, apps/api/app/prompts | fallback on 429, cache, buckets, prompt immutability |
| 0.6 RAG v0 | pending | — | apps/api/app/rag | chunking, RRF, citation validation |
| 0.7 Observability v0 | pending | — | apps/api/app/monitoring | PII redaction before export |
| 0.8 Redis limits + budgets | pending | — | apps/api/app/core/limits.py | 429 + Retry-After, budget exhaustion |
| 0.9 Web shell | pending | — | apps/web | lint, typecheck, vitest, build |
| 0.10 Deploy | blocked on HC-1/HC-2 | — | vercel.json, .github/workflows | smoke |
| 0.11 Docs | pending | — | README, docs/* | — |

**Risks:** Neon pooler (PgBouncer transaction mode) breaks server-side prepared statements → disable psycopg prepare. Vercel Services is beta → fallback plan in §B17. fastembed model files add ~150 MB to the bundle → measure in CI.

## Acceptance — Phase 0

- [ ] Public URL: sign up, log in, guest demo; Turnstile enforced
- [ ] Playground via router; forced Groq 429 falls back to Gemini with `fallback_reason` stored; prompt versions immutable (test)
- [ ] Knowledge upload, hybrid search + rerank, cited answer on Neon; no torch in api bundle; bundle < 450 MB
- [ ] RLS blocks cross-org reads (test); rate limit returns 429 + `Retry-After`
- [ ] Langfuse traces with no raw PII
- [ ] CI green; deploy.yml migrates before deploy; rollback documented
