# Validation log

Dated evidence of what was actually run. Nothing here is projected.

## 2026-11-05 — Purchasing, copilot and quality implementation

- Local API suite: **127 passed** (7.40 s), including vendor assignment/stale-role restriction/revocation, cross-vendor/org access, ordered approval, changed evidence, payment idempotency, Gmail mocked transport outcomes, copilot citation/scope checks and human-label privacy/calibration.
- API ruff and mypy passed. Web typecheck, eslint, 3 vitest checks and production build passed with Purchasing/Copilot/Quality routes.
- Actual fixture workflow CLI: **5/5**, no execution errors, no inappropriate automatic routes. Dataset SHA `0aba2045b135964413ae2ee85f48092d8e416af053eb8061cd16788d2ef9158f`; selected snapshot `000b6c9c70f8c8c01ac85bbd3d008bd04f33e36ff2119098db67ed2b1c54a34c`. Fixture extraction is ground truth, so extraction F1 remains unmeasured.
- Actual live marketing judge: local stored run `93b363a2-df07-449f-beef-019d26651fd3`, Groq gpt-oss-120b, score **0.2**, failed, unsupported claims identified: 48-hour battery life and 30% discount. One case only; no human calibration evidence inferred.
- Browser: local `/app/procurement` redirects unauthenticated visitors to login. A complete signed-in multi-account walkthrough was not performed.
- Real Gmail delivery, new live document/scan extraction and new production deployment have not yet been verified. No real funds moved or emails sent during this validation.

Additional live synthetic smoke: Gemini 3.6 Flash extracted PO-1001 as 2 laptops at INR 500.00 each, total INR 1,000.00. This found and fixed Decimal JSON-cache serialization; a regression test verifies cached decimal quantities. Groq's case answer correctly described the 2 ordered/invoiced versus 1 received shortfall, but omitted inline references while returning valid structured source IDs. The API now renders those verified IDs itself; unknown references still fail closed. Representative PDF/scan extraction and signed-in browser acceptance remain pending.

## 2026-11-04 — Phase 0, local (macOS, Docker Postgres 17 + pgvector 0.8.7, Redis via serverless-redis-http)

| Check | Result | Evidence |
|---|---|---|
| API unit/integration tests | 32 passed | `cd apps/api && uv run pytest` |
| Forced Groq 429 falls back to Gemini, `fallback_reason` stored in `ai.llm_calls` | pass | `tests/test_api.py::test_playground_fallback_reason_stored`, `tests/test_router.py` |
| EEA/CH/UK/NO visitors never reach Gemini free tier | pass | `test_eea_and_uk_visitors_never_reach_gemini_free_tier` |
| Prompt versions immutable (app role + owner), concurrent saves get distinct versions | pass | `tests/test_prompts.py` |
| RLS blocks cross-org reads under 40 concurrent transactions; no leak across transactions on one connection | pass | `tests/test_rls.py` |
| Rate limit → 429 + `Retry-After`; budget → 429 `budget_exhausted` | pass | `tests/test_api.py` |
| 12 MB body limit → 413 | pass | `test_body_limit_413` |
| Knowledge upload (SHA-256 dedup), hybrid search with RRF + rerank, citation validation flags invalid `[9]` | pass | `test_knowledge_upload_dedup_search_and_cited_answer` |
| Real fastembed models: relevant chunk ranked #1 by vector, keyword and rerank | pass (manual) | local run: bank-change chunk vector rank 1, keyword rank 1, rerank 2.5 (int8) |
| Migration round-trip upgrade → check → downgrade → upgrade | pass | local + `ci.yml` |
| Web: lint, typecheck, vitest (Markdown exfiltration test), production build | pass | `apps/web` |
| Guest demo end to end: Turnstile (test key) → anonymous user → demo org → JWT via JWKS → API → Redis usage | pass (manual, browser) | dashboard showed budget 10/10, 100/100, 200/200 |
| api bundle estimate | 428 MB (< 450) | `scripts/api_bundle_size.sh`, macOS wheels; Linux figure comes from CI |

**Not measured yet:** anything on the public URL (not deployed: HC-1/HC-2 open), Langfuse traces (no keys), Groq/Gemini behaviour (no keys; local runs used Ollama `qwen2.5:0.5b`, which answered the policy question with "not in the provided data" — a model-quality limit of the 0.5B fallback, not a pipeline result).
