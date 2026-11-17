# Changelog

## Unreleased — Phases 2–5

Written and verified locally (lint, types, 195 unit tests); **not yet run against a database or
deployed**. Nothing here claims a measured result.

### Phase 2 — context engine and copilot

- **Knowledge graph** (`app/graph`): Neo4j client with explicit unavailability and a 60 s
  backoff, constraints and indexes, transactional-outbox projection with idempotent `MERGE`s,
  eight parameterised query templates, and a text-to-Cypher guard (server-side READ transaction
  first, validation second, foreign-org rows dropped third).
- **Fraud checks** wired into `vendor_verify`: shared bank accounts, vendor/employee conflicts,
  split invoices under an approval limit, creator-approved new vendors, alias duplicates. An
  unavailable graph raises `GRAPH_UNAVAILABLE` (MEDIUM) and routes to human review.
- **Long-term memory** (`app/memory`): namespaced store with the anti-poisoning write policy
  (human confirmation, or three consistent observations — never document text), embedding
  recall, TTL, decay, hard delete, and a page where users see and delete what the agent knows.
  Memories used in a run appear in its lineage.
- **AURA MCP server** at `/mcp`: `list_invoices`, `get_invoice`, `explain_decision`,
  `ask_copilot`, and `approve_invoice` gated by host elicitation or a confirm-in-app link.
- **Copilot rebuilt** as a bounded tool loop over the router and gateway: policy search, graph
  templates, read-only SQL templates, invoices, audit lineage, and a confirmation-gated write
  tool; threads with summarisation, SSE streaming, and answers withheld when a citation does
  not resolve.

### Phase 3 — trust layer

- **Shared guardrail screen** used by intake, chat, the challenge page and the red-team runner;
  every verdict stored in `ai.guardrail_events`; output validators for citations, external
  references and bank-like digits.
- **Evaluation harness**: 12-check deterministic library, baselines and gates that refuse
  invalid comparisons, red-team runner that separates input-screen blocks from structural
  defences, policy-QA and trajectory suites, offline RAGAS-style metrics, public report builder.
- **Datasets**: 50 attacks + 15 benign controls, 62 policy questions, 44 trajectories, all
  generated deterministically and checked for freshness in CI.
- **Cassettes** for deterministic CI, and a promptfoo guardrail pack.
- **Feedback inbox**: in-app corrections (optionally remembered for the vendor) plus an
  HMAC-signed, replay-resistant webhook that is idempotent by `event_id`, with triage into
  regression datasets.
- **Public challenge page** against a sandbox tenant with no write tools; misses file themselves
  as regression cases.
- **Observability**: cost and latency by task, STP and HITL rates, guardrail summary, drift
  (PSI on amounts and vendor mix, confidence shift, override rate), copilot grounding.
- **Workflows**: nightly evals, weekly evals, keep-alive, demo reset, audit-chain anchoring,
  retrain, browser agent, kind e2e.
- **Docs**: threat model mapped to the OWASP LLM and agentic lists, runbook entries for the new
  failure modes, cost model, ADRs 005–008.

### Phase 4 — fine-tuning

- `ml/gl_coder`: dataset builder (generator ground truth + human corrections + open-weight
  paraphrase), vendor-held-out splits chosen so every test label is learnable, leakage checks,
  Unsloth QLoRA trainer, baseline evaluator, HF dataset publishing, Kaggle kernel.
- `ml/specialist-space`: Gradio ZeroGPU app with a tight GPU reservation and one batched call
  per invoice.
- `specialist/gl-coder` provider transport in the router with an 18 s timeout and fallback;
  model registry with canary and audited manual promotion.
- **No training run yet** — HC-3 (HF write token, Kaggle API token) is still open, so every
  figure in `docs/MODEL_CARD.md` reads "not measured".

### Phase 5 — stretch

- Mock legacy vendor portal (no API) and an accessibility-tree-first Playwright browser agent
  that records a scoreable trajectory.
- Vendor onboarding workflow pack: deterministic KYC, tax-ID, screening-list, bank-verification
  and duplicate rules on the same runtime, guardrails, audit chain and approval separation.
- Dockerfiles for api, web and erp; Helm chart; kind end-to-end test; Terraform for a Bedrock
  OIDC role and an artifacts bucket, validated and planned only.
- k6 load profile against a preview deploy with the fake provider.

### Fixed

- Text-to-Cypher validator: a malformed string-literal pattern meant every query raised a regex
  error, and the validator returned the *stripped* query, which would have executed with its
  string literals blanked. Both found by the new tests.

## Unreleased — Phase 0

- Rebuild as AURA finance-ops platform.
- API foundation, RLS tenancy, model router, prompt registry, RAG v0, limits and budgets, tracing.
- Next.js web shell with Better Auth, guest demo, knowledge base and playground.
- CI (lint, types, tests, migration round-trip, bundle gate, audits, secret scan) and deploy workflow (migrate → deploy → smoke).
