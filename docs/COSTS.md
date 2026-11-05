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
