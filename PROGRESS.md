# PROGRESS

Spec: [AURA_BUILD_PROMPT.md](AURA_BUILD_PROMPT.md). Mode: **auto** (stops at human checkpoints, failures, destructive actions).

## Current

- **Phase:** 0 deploy blocked on HC-1/HC-2; **Phase 1 local work in progress** (§A4: continue work that doesn't depend on the checkpoint)
- **Branch:** `rebuild/finance-ops` (rebuild of this repo, chosen by the human on 2026-11-04 over a new repo)
- **Last verified production deploy:** none yet for the rebuild. The previous product (AI eval platform) lives under `legacy/` for reference and code porting.

## Next step

**Blocked on HC-1 + HC-2** for the first deploy. All Phase 0 local work is done and green (see VALIDATION.md).
When the human reports HC-1/HC-2 done: verify provider model IDs against Groq/Gemini `/models`, run `deploy.yml` (or a manual first deploy), smoke-test the live URL, check Langfuse for unredacted PII, tick the acceptance boxes, then start Phase 1 (synthetic world generator).

## Open human checkpoints

### HC-1 — accounts and keys (DONE 2026-11-05, verified live)

Verified 2026-11-05 with live probes (values never printed): Neon pooled + direct (Postgres 18.6, pgvector available, not migrated yet), Upstash PING, Neo4j AuraDB (database name = instance id → `NEO4J_DATABASE`), Langfuse auth, Groq (`/models` + a live router call), Gemini (live router call via forced Groq 429), Turnstile secret accepted by Cloudflare. Model changes: Groq retired `qwen3-32b` → `qwen/qwen3.8-27b`; Gemini 2.5 is closed to new accounts → `gemini-3.6-flash` / `gemini-3.5-flash-lite` (free-tier RPM/RPD not published; conservative values in tasks.yaml). Router now falls back on HTTP 404 (`model_unavailable`). Still open: Hugging Face account (Phase 4), Vercel Blob store (HC-2).

<details><summary>Original checklist</summary>


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

</details>

### HC-2 — deploy (IN PROGRESS)

Done: Vercel CLI 65.11.0 logged in; repo linked to the **existing** project `aura` (prj_…Cnl, Services preset, iad1, `aura-henna-one.vercel.app`, Git-connected to NelsonNpinto/Aura). Vercel MCP (`https://mcp.vercel.com`, user scope) + Vercel plugin installed. Existing project env vars are from the legacy app: `API_KEY`, `VITE_API_TIMEOUT_MS` (unused by the rebuild), `DATABASE_URL`, `WEBHOOK_SECRET` (must be replaced).


Run these yourself (never paste values into chat):

1. `npm i -g vercel` → `vercel login` → in the repo root `vercel link` (create project `aura`, Hobby). In Project Settings → Build & Deployment, confirm Services are detected from `vercel.json`.
2. Vercel env vars for **Production** (and Preview with the Neon `preview` branch URLs) via `vercel env add NAME production`:
   `APP_ENV=production`, `DATABASE_URL` (pooled), `DATABASE_URL_UNPOOLED`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `BETTER_AUTH_SECRET` (`openssl rand -base64 32`), `BETTER_AUTH_URL=https://<your>.vercel.app`, `AURA_JWKS_URL=https://<your>.vercel.app/api/auth/jwks`, `AURA_JWT_ISSUER=https://<your>.vercel.app`, `WEB_ORIGIN=https://<your>.vercel.app`, `TURNSTILE_SECRET_KEY`, `NEXT_PUBLIC_TURNSTILE_SITE_KEY`, `BLOB_READ_WRITE_TOKEN` (create a **private** Blob store in the project; it injects this), `DAILY_RUN_BUDGET=200`, `GUEST_DAILY_RUNS=10`.
3. GitHub → Settings → Environments → create `production`, then `gh secret set NAME --env production` for: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` (both in `.vercel/project.json` after `vercel link`), `DATABASE_URL_UNPOOLED`, `BETTER_AUTH_SECRET`. Optionally `gh variable set PRODUCTION_URL`.
4. Merge branch `rebuild/finance-ops` into `main` (or tell me to open the PR) — `deploy.yml` runs tests → migrations → `vercel deploy --prod` → smoke.

## Decisions

- [ADR-000](docs/adr/000-rebuild-in-place.md) — rebuild in this repo, old app kept in `legacy/` until ported.
- [ADR-001](docs/adr/001-free-tier-stack.md) free-tier stack; int8 reranker to fit the bundle budget.
- [ADR-002](docs/adr/002-model-router.md) model router.
- [ADR-003](docs/adr/003-auth-and-tenancy.md) Better Auth in schema `auth`, JWT/JWKS, RLS via `SET LOCAL ROLE aura_app`.
- `apps/web/.npmrc` sets `legacy-peer-deps=true`: npm 10's arborist crashes resolving better-auth's optional peer set (`Cannot read properties of null (reading 'edgesOut')`).
- Local dev on this exFAT drive: Python venv at `~/.venvs/aura-api`; `apps/web/node_modules` is an APFS sparse image (`.local/web-node_modules.sparsebundle`, mount with `diskutil mount -mountPoint <repo>/apps/web/node_modules <disk>` after `hdiutil attach -nobrowse`); Turbopack disk cache disabled. API dev port 8010 (8000 is used by another local project).

## Phase 0 plan

Dependencies (with reasons) are recorded per package in `apps/api/pyproject.toml` comments and ADRs. Versions checked on PyPI/npm on 2026-11-04.

| Task | Status | Owner | Files | Tests |
|---|---|---|---|---|
| 0.1 HC-1 checklist | printed, **waiting on human** | claude-code | PROGRESS.md | — |
| 0.2 Monorepo scaffold | done | claude-code | Makefile, .editorconfig, .pre-commit-config.yaml, docker-compose.yml, .env.example, docs/adr/ | lint |
| 0.3 API foundation | done | claude-code | apps/api/app/{core,api,models}, alembic | health/ready, middleware, errors, RLS |
| 0.4 Auth + tenancy | done locally | claude-code | apps/web/src/lib/auth*, apps/api/app/core/auth.py | JWT/JWKS, API keys, RLS tests, guest flow (manual) |
| 0.5 Router + prompt registry | done | claude-code | apps/api/app/llm, apps/api/app/prompts | 12 router tests, 3 registry tests |
| 0.6 RAG v0 | done | claude-code | apps/api/app/rag, app/services/blob.py | ingest/search/ask test |
| 0.7 Observability v0 | done locally; Langfuse unverified (no keys) | claude-code | apps/api/app/monitoring | traces row test |
| 0.8 Redis limits + budgets | done | claude-code | apps/api/app/core/{store,limits}.py | 429 + Retry-After, budget_exhausted |
| 0.9 Web shell | done | claude-code | apps/web | lint, typecheck, vitest, build |
| 0.10 Deploy | config done; **blocked on HC-1/HC-2** | claude-code | vercel.json, .github/workflows, scripts/smoke.sh | smoke (local pass) |
| 0.11 Docs | done for Phase 0 | claude-code | README, docs/*, VALIDATION.md, CHANGELOG.md | — |

**Risks:** Neon pooler (PgBouncer transaction mode) breaks server-side prepared statements → disable psycopg prepare. Vercel Services is beta → fallback plan in §B17. fastembed model files add ~150 MB to the bundle → measure in CI.

## Phase 1 plan — invoice-to-pay agents

Order chosen so each step is testable without cloud accounts. Live acceptance (five demo invoices live, Queues batch, redeploy durability) waits for HC-1/HC-2.

| Task | Status | Owner | Files | Tests | Dependencies (reason) |
|---|---|---|---|---|---|
| 1.5 Domain rules | in progress | claude-code | apps/api/app/domain/{money,matching,duplicates,approval,sod,risk}.py | table-driven unit tests | none (pure Python) |
| 1.4 Audit lineage | pending | — | app/audit, migration 0002 | chain verify, tamper, concurrent appends | none |
| 1.1 Synthetic world generator | pending | — | evals/generator | determinism, ground truth | fpdf2 (PDF render), pypdfium2 + Pillow (scans), Faker not used (seeded own lists) |
| 1.2 Mock ERP + MCP | pending | — | services/erp-mock | contract test per tool | mcp (official SDK, Streamable HTTP stateless) |
| 1.3 Tool registry + gateway | pending | — | app/tools | each policy branch | mcp client |
| 1.6 Workflow graph | pending | — | app/agents/invoice_to_pay | fake provider + cassettes | langgraph, langgraph-checkpoint-postgres, pdfplumber |
| 1.7 Runs API (SSE, resume, cancel) | pending | — | app/api/v1/runs.py | SSE replay, SoD, idempotency | — |
| 1.8 aura-eval v0 | pending | — | app/evaluation/cli.py | route accuracy stored | — |
| 1.9 UI pages | pending | — | apps/web | e2e | @xyflow/react, pdfjs-dist |
| 1.10 Demo data, replay, personas | pending | — | seed snapshot | budget=0 replay | — |
| 1.11 Playwright e2e | pending | — | apps/web/e2e | five scenarios | @playwright/test |

**Risks:** Vercel Queues API for Python is new (check docs at 1.7); MCP 2026-07-28 stateless transport support in the Python SDK must be verified; Groq 8K TPM constrains extraction of long invoices (chunk + fall back to Gemini).

## Acceptance — Phase 0

- [ ] Public URL: sign up, log in, guest demo; Turnstile enforced
- [ ] Playground via router; forced Groq 429 falls back to Gemini with `fallback_reason` stored; prompt versions immutable (test) — **tests pass; live check pending keys**
- [ ] Knowledge upload, hybrid search + rerank, cited answer on Neon; no torch in api bundle; bundle < 450 MB
- [x] RLS blocks cross-org reads (test); rate limit returns 429 + `Retry-After`
- [ ] Langfuse traces with no raw PII
- [ ] CI green; deploy.yml migrates before deploy; rollback documented
