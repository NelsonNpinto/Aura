# Runbook

## Rollback

1. `npx vercel rollback --token "$VERCEL_TOKEN"` (or Vercel dashboard → Deployments → previous → Promote).
2. Migrations are expand-only, so the previous build still works against the current schema. Never run `alembic downgrade` on production without a backup branch in Neon.
3. Record the incident in `docs/POSTMORTEMS.md`.

## Provider quota exhausted

Symptoms: `ai.llm_calls` rows with `error_type = rate_limited` or `bucket_exhausted`, responses with `fallback_reason`. The router falls back automatically. If every model is exhausted, endpoints return `503 router_exhausted`; LLM-backed endpoints return `429 budget_exhausted` when the daily demo budget is spent. Both reset at UTC midnight.

## Neon cold start

The first request after ~5 min idle takes ~1 s longer. `/api/v1/ready` reports `postgres: ok` once warm. Do not add keep-warm pings (they burn CU-hours).

## Failed migration

`deploy.yml` stops before `vercel deploy` when migrations fail, so production keeps serving the old build. Fix forward with a new migration; use a Neon branch to rehearse.

Sections for Neo4j paused, demo budget exhausted and injection spike are added in phases 1–3.

## Shared Neon database with the legacy app

The production Neon database (`neondb`) also holds the previous app's tables in `public`,
including its own `public.alembic_version` (revision `4962370af0b4`). AURA must not touch them.
AURA's Alembic history lives in `public.aura_alembic_version` and all AURA tables live in
their own schemas (`core`, `ai`, `kb`, `ap`, `audit`, `ops`; Better Auth in `auth`).
Dropping the legacy tables is a separate, human-approved decision (ADR-000).

## Neo4j AuraDB paused or unreachable

**Symptom.** `/api/v1/ready` reports `neo4j: unavailable`, invoices carry a `GRAPH_UNAVAILABLE`
flag and route to human review, and `/app/graph` shows the unavailable banner.

**Why it is not an outage.** Graph checks degrade by design: an unavailable graph raises a
MEDIUM flag, never a silent pass. Invoice processing continues.

**What to do.**
1. Check the reason: `GET /api/v1/graph/health` returns `not_configured`,
   `driver_not_installed`, or the exception type from the last attempt.
2. AuraDB Free pauses after a few days idle. **Resuming is manual in the Aura console** — a
   connection attempt does not wake it. Open the instance and press Resume.
3. The daily `keepalive.yml` ping exists to prevent this. If it has been failing, check its
   recent runs first.
4. After resuming, drain the backlog: `/app/admin` → "Drain the outbox", or
   `python -m app.scripts.graph_admin --sync`. Nothing was lost; the outbox retried and backed
   off.
5. The client caches unavailability for 60 s, so allow a minute before expecting recovery.

## Demo budget exhausted

**Symptom.** Runs return 429 `budget_exhausted`; the usage panel shows 0 remaining.

**What to do.** Nothing, usually — this is the budget governor working. The demo falls back to
replay mode and serves the five recorded runs, labelled "recorded run". Budgets reset at UTC
midnight. To raise them, change `DAILY_RUN_BUDGET` / `GUEST_DAILY_RUNS` and redeploy; check
`docs/COSTS.md` first so a raise does not push a provider past its free tier.

## Injection spike

**Symptom.** A jump in `ai.guardrail_events` with `verdict = block`, or a run of challenge
attempts getting through.

**What to do.**
1. `/app/observability` → Guardrails shows the counts by check and surface.
2. `GET /api/v1/guardrails/events?verdict=block` lists them with evidence.
3. Attempts that got through are already filed in the feedback inbox. Triage them into the
   `redteam` dataset (`/app/quality` → feedback) so they become regression cases.
4. If a specific phrasing is getting through repeatedly, add it to `INJECTION_PATTERNS` in
   `app/guardrails/screen.py` and regenerate the corpus
   (`python -m evals.generator.trust_datasets`). Check the benign controls afterwards: the
   false-positive rate is measured in the same run and a careless pattern will raise it.
5. `CHALLENGE_ENABLED=false` disables the public challenge page without a deploy if it is being
   abused.

## Specialist model unavailable

**Symptom.** `fallback_reason` on `gl_coder_specialist` calls, or `/api/v1/ready` shows
`specialist: enabled` with no space configured.

**What to do.** Nothing urgent: the router falls back to the general chain within 18 s and GL
coding continues. The usual causes are a cold Space (first call after idle), the daily ZeroGPU
allowance (~5 GPU-minutes) being spent, or a Space restart. Set `ENABLE_SPECIALIST=false` to
stop trying altogether. Check `/app/admin` → model registry for which version is serving.

## Audit chain verification fails

**Symptom.** `GET /api/v1/audit/verify?run_id=…` reports a broken link, or the invoice page
shows the chain badge in red.

**What to do.** This is serious: it means stored events no longer hash to their chain.
1. Note the first broken sequence number from the verify response — that is where the chain
   diverges.
2. Compare each org's current head with the last committed anchor in `audit-anchors/` in this
   repository. If the head matches an anchor and only later events are broken, the damage is
   recent and bounded.
3. Do not "repair" the chain. Preserve it, capture the broken rows, and write a postmortem.
4. Remember what this does and does not prove: the log is **tamper-evident, not tamper-proof**.
   Someone with database-owner access could rewrite the whole chain so it verifies again — the
   daily anchor is what makes that detectable.

## Drift breach

**Symptom.** A nightly issue, or `/app/observability` → Drift showing a breached metric.

**What to do.** Read the metric before acting: `insufficient_data` means the window had too few
observations and nothing is wrong. A real `amount_psi` or `vendor_mix_psi` breach usually means
the demo data was reseeded or a new vendor set arrived — compare against the reseed time. A
breach in `override_rate_delta` is the one worth investigating: humans are correcting the agent
more often than before, which is an eval signal, not a config problem.
