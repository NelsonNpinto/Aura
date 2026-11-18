# Validation log

Dated evidence of what was actually run. Nothing here is projected.

## 2026-11-17 — Phases 2–5 implementation, local checks only

Windows 11, Python 3.12 venv at `apps/api/.venv`. **No database, no Neo4j and no deployment were
available**, so everything below is either a pure-code check or an endpoint that needs neither.

| Check | Result | Evidence |
|---|---|---|
| `ruff check .` and `ruff format --check .` | clean | 140 files |
| `mypy app` (strict) | clean | 120 source files |
| `pytest` | 195 passed, 45 skipped, 1 failed | the failure is `test_jwt_principal`, which needs Postgres and hits the known Windows psycopg/Proactor limitation; the 45 skips are database-dependent |
| Cypher guard rejects writes and procedures | pass | 10 parameterised cases in `tests/test_graph.py`, plus multi-statement, limit-cap and string-literal cases |
| Cross-tenant rows dropped from graph results | pass | `test_rows_from_another_tenant_are_dropped`, incl. nested |
| Every graph template binds `$org_id` as a parameter | pass | `test_every_template_binds_org_id_as_a_parameter` |
| Memory write policy (3 observations or one confirmation) | pass (pure parts) | `tests/test_memory.py`; the storage paths are marked `db` and skipped |
| Guardrail screen blocks instruction phrases, passes clean text | pass | 8 cases, including the false-positive controls |
| Classifier failure never blocks on its own | pass | `test_classifier_failure_never_blocks_on_its_own` |
| Output validation blocks unresolvable citations, external images, stray bank digits | pass | 4 cases |
| Gates refuse an invalid comparison (snapshot or mode mismatch) | pass | 2 cases |
| Hard gates fail on a false auto-post and on missed HITL | pass | 2 cases |
| Cassette record → replay without touching the provider | pass | `tests/test_copilot_and_feedback.py` |
| Webhook signature: tampered body, expired timestamp, missing secret all rejected | pass | 4 cases |
| Copilot withholds an answer whose citation does not resolve | pass | `test_an_answer_citing_nothing_gathered_is_withheld` |
| Onboarding rules (sanctions, KYC, employee bank conflict, duplicates, tax-ID formats) | pass | 9 cases |
| Dataset generation reproducible | pass | `trust_datasets --check` matches the committed files |
| API starts and serves | pass | `/api/v1/health` 200; `/api/v1/challenge/categories` 200; MCP session manager started; `/api/v1/ready` 503 correctly reporting Postgres and Redis down |

### Offline red-team measurement

`aura-eval redteam` (deterministic layer only — no classifier, no copilot), 65 cases:

- attack success rate **0** (no response is generated offline, so nothing can exhibit the
  behaviour an attack asks for)
- block rate **0.42**, defended rate **0.68**
- false-positive rate on 15 benign controls **0.00**
- per category: direct_injection 1.00 blocked, hidden_text 1.00, indirect_injection 0.43,
  exfiltration 0.38, jailbreak 0.12; tool_misuse and memory_poisoning 0.00 blocked but 1.00
  defended structurally (tool gateway, memory write policy)

This is a measurement of the deterministic layer, not of the system's overall resistance. The
classifier and output validation — which is where jailbreak and exfiltration attempts are
expected to be caught — were not exercised.

### Two defects found and fixed

1. `app/graph/guard.py`: the string-literal regex lost a level of escaping when the file was
   written, so every call to `validate()` raised `re.PatternError`. No generated query could
   ever have been validated.
2. The same function returned the comment- and literal-stripped copy as the query to execute, so
   a query filtering on a string value would have run with that value blanked.

Both were found by the new tests, not by inspection.

### Not measured

No migration applied (`0005` has never run), no seed, no invoice run, no copilot answer, no
graph projection, no live model call on any new path, no training run, no deployment, no
browser-agent run, no Helm/kind run. Nothing in this entry should be read as evidence that the
Phase 2–5 features work end to end.

## 2026-11-11 — Finance Copilot benchmark

- The finance fixture CLI checked eight reference answers across four synthetic cases and exited 0. Replacing a valid citation with an invented receipt ID in an isolated dataset copy made the same command exit 1 and identify `quantity-hold/supported`.
- The quality fixture endpoint returned HTTP 200 with all eight answers using the in-memory rate limiter. All four demo PDFs rendered and passed Aura's PDF text and hidden-text checks. Their quantities produced the expected shortfall and correction in the Purchasing comparison function.
- API verification passed 99 tests after excluding database-dependent checks, including the JWT principal test that accesses Postgres. Ruff and mypy passed. Web type checking, lint and four Vitest tests passed.
- The pre-key live check stopped before model calls. After a Groq key was configured, the first live run on `4dc7b56` rejected all four deliberately incorrect reference answers, accepted three of four correct references, and accepted two of four generated Copilot answers. Two generated answers were unscored when their judge calls failed. The gate failed. The rejected correct reference exposed that an approval status by itself does not provide explicit payment evidence.
- The second live run classified all eight reference answers as expected. One of four generated answers passed. The price answer omitted the amount of the variance, the payment answer omitted approval status, and a judge request was unscored after a Groq bad request. The gate failed. The Copilot now calculates the same-currency price difference from stored comparison values, the payment question asks for approval status explicitly, and the judge can fall back to the configured smaller Groq model.
- The third live run classified all eight reference answers as expected and accepted three of four generated answers. The quantity hold answer cited the 40 invoiced and 30 received correctly but omitted the ten-unit difference. The gate failed. The next version supplies the calculated unreceived quantity in the comparison evidence and asks for it explicitly.
- A separate live smoke test of the synthetic invoice PDF passed all eight extraction assertions using Groq GPT-OSS 20B through the router. It read invoice `INV-8401`, PO `PO-8401`, USD, SKU `FILTER-02`, one line, 40 units, 4,500 minor units per item and 180,000 minor units total. The smoke test pinned the configured fallback model and used the same PDF parser, prompt and output schema as Purchasing.
- The fourth live run matched all eight reference verdicts, accepted two of four generated answers, and scored every case. The generated quantity and price arithmetic was supported, but the judge did not find enough cited evidence for the additional hold and correction claims. The live gate exited 1. Independent reviews are needed to distinguish judge interpretation errors from Copilot citation omissions.
- The continuation run added an explicit correction-hold explanation and status citation instructions. The judge supported the hold and correction claims. It matched all eight reference verdicts and accepted two of four generated answers. The hold answer omitted the invoiced and received quantities, and the partial-billing answer cited a summary without the figures it used. The follow-up prompt requires all three shortfall figures and distinguishes comparison findings from source-document figures. The fixture gate passed after that change.
- The follow-up live run using the prompt committed in `bd61ea1` exited 0. It matched eight of eight reference verdicts and accepted four of four generated answers on the same dataset snapshot. There were no false passes or unscored cases. The router estimated $0.006175 at configured rates. Actual billing and independent human agreement were not measured.
- The production health and readiness endpoints returned OK at `1a7cc9a`. The public login page returned HTTP 200 and showed the Purchasing demo account section.
- Independent human agreement, the signed-in Purchasing walkthrough and production rollout remain unverified.

## 2026-11-05 — Purchasing, copilot and quality implementation

- Local API suite: **127 passed** (7.40 s), including vendor assignment/stale-role restriction/revocation, cross-vendor/org access, ordered approval, changed evidence, payment idempotency, Gmail mocked transport outcomes, copilot citation/scope checks and human-label privacy/calibration.
- API ruff and mypy passed. Web typecheck, eslint, 3 vitest checks and production build passed with Purchasing/Copilot/Quality routes.
- Actual fixture workflow CLI: **5/5**, no execution errors, no inappropriate automatic routes. Dataset SHA `0aba2045b135964413ae2ee85f48092d8e416af053eb8061cd16788d2ef9158f`; selected snapshot `000b6c9c70f8c8c01ac85bbd3d008bd04f33e36ff2119098db67ed2b1c54a34c`. Fixture extraction is ground truth, so extraction F1 remains unmeasured.
- Actual live marketing judge: local stored run `93b363a2-df07-449f-beef-019d26651fd3`, Groq gpt-oss-120b, score **0.2**, failed, unsupported claims identified: 48-hour battery life and 30% discount. One case only; no human calibration evidence inferred.
- Browser: local `/app/procurement` redirects unauthenticated visitors to login. A complete signed-in multi-account walkthrough was not performed.
- Real Gmail delivery, new live document/scan extraction and new production deployment have not yet been verified. No real funds moved or emails sent during this validation.

Additional live synthetic smoke: Gemini 3.6 Flash extracted PO-1001 as 2 laptops at INR 500.00 each, total INR 1,000.00. This found and fixed Decimal JSON-cache serialization; a regression test verifies cached decimal quantities. Groq's case answer correctly described the 2 ordered/invoiced versus 1 received shortfall, but omitted inline references while returning valid structured source IDs. The API now renders those verified IDs itself; unknown references still fail closed. Representative PDF/scan extraction and signed-in browser acceptance remain pending.

The first full 207-case fixture run matched 84 outcomes and failed its gate. It is invalid as an accuracy benchmark because tool quotas and conflicting generator expectations affected results. Examples: g10002 required suspected-duplicate review; g10010/g10012 required vendor/employee conflict review despite their expected clean route. Zero inappropriate automatic routes were recorded. Node-error reporting and pacing were subsequently corrected; reviewed expectations and a paced full rerun remain outstanding. The original local report is retained privately.

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
