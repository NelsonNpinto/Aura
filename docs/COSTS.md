# Costs and free-tier usage

Target: **$0/month**. Limits from §B4 (checked by the spec author 2026-11). Observed usage is filled in from real dashboards only; blank means not measured yet.

| Service | Free limit | Design guard | Observed (month) |
|---|---|---|---|
| Vercel invocations | 1M / month | rate limiter 60/min/IP, budgets | not measured (not deployed) |
| Vercel active CPU | 4 h / month | no torch; Neon/LLM waits don't bill CPU | not measured |
| Vercel api bundle | 500 MB | CI gate 450 MB | 428 MB estimate (macOS, 2026-11-04); Linux measured in CI |
| Neon | 0.5–1 GB, 100 CU-h | scale to zero, never kept warm | not measured |
| Upstash | 500K commands | 1 EVAL per limit check; MGET for usage | not measured |
| Vercel Blob | 1 GB, 2K advanced ops | SHA-256 dedup before upload; never `list` | not measured |
| Langfuse | 50K units | optional export, `LANGFUSE_SAMPLE_RATE` | not measured |
| Groq | ≈30 RPM / 1K RPD per model | Redis token buckets, fallbacks, cache | not measured |
| Gemini | per-project daily quota | buckets; geo gate | not measured |

Demo budget defaults: `DAILY_RUN_BUDGET=200`, `GUEST_DAILY_RUNS=10`, 100 runs/org/day, 300K tokens/org/day.

## Phases 2–5 additions

| Service | Free limit | Design guard | Observed (month) |
|---|---|---|---|
| Neo4j AuraDB Free | 1 instance, node/relationship caps, auto-pause | projection through the outbox (never inline), daily keep-alive ping, 60 s unavailability cache, graceful degrade to human review | not measured |
| Hugging Face ZeroGPU | ≈5 GPU-min/day per token | `@spaces.GPU(duration=20)`, one batched call per invoice, 18 s router timeout then fallback | not measured (no training run yet) |
| Kaggle GPU | ≈30 GPU-h/week | one training kernel per retrain, triggered manually or weekly | not measured |
| GitHub Actions | free for public repos | nightly runs a rotating slice, weekly is the only full run | not measured |
| Vercel Queues | 1M ops/month | batch runs only; single invoices stream inline | not measured |

## Where the added load actually lands

- **Postgres rows.** Fifteen new tables. The ones that grow with use are
  `ai.guardrail_events` (a few rows per run), `ai.copilot_messages` (two per turn) and
  `ai.challenge_attempts` (one per public attempt). At demo volume this is far below Neon's
  1 GB; a production deployment would want retention on all three.
- **Redis commands.** The challenge page adds one `take` per attempt; memory and graph add
  none. The budget governor still costs one EVAL per check.
- **Model calls.** The copilot loop can spend up to `MAX_STEPS` (5) router calls per question
  against the previous one. That is the single largest addition to provider quota, which is why
  the copilot's cache policy is `none` only for the step task and summarisation is capped.
- **CPU.** fastembed now also embeds memories. One embedding per memory write and per recall —
  negligible next to document ingestion.

## Projected cost if this left the free tier

Rough, at list prices, assuming the measured shape of a demo run (figures marked *not measured*
have no stored run behind them yet):

| Scale | Invoices/month | Model cost | Postgres | Notes |
|---|---|---|---|---|
| Demo (today) | ~100 | within free tier | within free tier | everything $0 |
| 10× | ~1,000 | not measured | within Neon free tier | Groq daily caps bind first; batching and the cache matter |
| 100× | ~10,000 | not measured | needs a paid Neon plan | Vercel active-CPU and Blob ops become the next limits |

The honest statement: **cost per invoice has not been measured on a live run at volume.** The
per-run estimate on `/app/observability` comes from `ai.llm_calls` at list prices and is the
number to extrapolate from once a representative batch has run.
