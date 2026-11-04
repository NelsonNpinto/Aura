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
