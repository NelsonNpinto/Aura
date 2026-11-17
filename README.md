# AURA — Auditable, Unified, Reliable Agents

A finance-operations AI platform running live on a **$0 free-tier stack**: an invoice-to-pay agent workflow, a purchasing approval workflow, a cited finance copilot, and a trust layer of guardrails, evaluations, audit lineage and human-in-the-loop controls.

**Live demo:** https://aura-henna-one.vercel.app · **Guest access:** [/demo](https://aura-henna-one.vercel.app/demo) (no account needed)

> All data is synthetic. No real payments are made and no real emails are sent.

## Two workflows, one runtime

**Invoice-to-pay agent** (`/app/inbox`) — upload or pick an invoice and watch an eleven-step LangGraph workflow run live over SSE: intake guard → extract → validate → vendor verify → three-way match → GL coding → policy check → risk & route → human approval → post → finalize. It auto-posts, routes to an approver, raises an exception, or blocks the document — and shows why.

**Purchasing workflow** (`/app/procurement`) — a buyer, a vendor, an L1 approver and a finance reviewer each supply or approve their own part. Documents are extracted by a model and **confirmed by a person**. Three-way comparison is deterministic code; approval requires two different people, neither of whom uploaded the evidence.

Five scripted demo invoices exercise the interesting paths: a clean invoice, a price variance beyond tolerance, a changed vendor bank account, a hidden prompt injection, and a scanned image.

## What it demonstrates

- **Multi-agent orchestration** — LangGraph with Postgres checkpointing, so a run survives a redeploy and resumes where it paused.
- **Deterministic where it matters** — matching maths, tolerances, the approval matrix, segregation of duties and risk scoring are plain, unit-tested Python. Models extract, classify and explain; they never decide an amount.
- **Guardrails** — hidden-text and prompt-injection detection on every document, spotlighting of untrusted text, PII redaction before any external call, and output validation against the computed facts.
- **Segregation of duties, enforced server-side** — the preparer cannot approve; whoever last edited a vendor's bank details cannot approve that vendor's payment; approvals bind to a hash of the evidence packet, so changed facts force re-approval.
- **Tamper-evident audit lineage** — every decision is a SHA-256 hash-chained event. `GET /api/v1/audit/verify` recomputes the chain and names the first broken link.
- **Hybrid retrieval with checked citations** — pgvector + Postgres full-text, reciprocal rank fusion, cross-encoder rerank. Invalid citation numbers are detected and reported rather than rendered.
- **Evaluation and release gates** — versioned synthetic datasets, a deterministic checks library, an LLM judge whose invalid outputs are stored *unscored*, human calibration (agreement and Cohen's kappa, reported as undefined when there are too few labels), and CI gates that block a regression.
- **Model routing** — one door for every LLM call: ordered model chains, Redis token buckets, fallback with a recorded reason, exact-match caching, structured outputs, and per-attempt telemetry.
- **A knowledge graph for the questions SQL answers badly** — vendors, bank accounts, employees and decisions in Neo4j, projected through a transactional outbox. It finds shared bank accounts, split invoices and creator-approved vendors. When AuraDB is paused the check reports *unavailable* and the invoice goes to a human; it never reports a silent pass.
- **Memory the user controls** — long-term notes are written only from confirmed corrections or three consistent observations, never from document text. Every note shows its source, confidence and expiry, and can be deleted.
- **An MCP server** — `/mcp` exposes the same services to other hosts with the caller's identity. Approving an invoice there requires host confirmation, or a link back into the app.
- **A public red-team challenge** — [/challenge](https://aura-henna-one.vercel.app/challenge) runs your attack against the same guardrails, in a sandbox with no write tools. Anything that gets through is filed as a regression case.

Headline metrics are **not published** until stored evaluation runs produce them. Empty metrics in the UI are deliberate, not missing data.

## Stack

| Layer | Choice |
|---|---|
| Web | Next.js (App Router, TypeScript strict), Tailwind, shadcn/ui, TanStack Query, Better Auth |
| API | FastAPI, Python 3.12, SQLAlchemy 2, Alembic, LangGraph |
| Data | Neon Postgres + pgvector (row-level security per org), Upstash Redis, Vercel Blob, Neo4j AuraDB |
| Models | Groq and Google Gemini free tiers behind a LiteLLM router; a fine-tuned GL coder on a free Hugging Face ZeroGPU Space; fastembed (ONNX) for embeddings and rerank, in-process |
| Ops | Vercel Services (web / api / erp), GitHub Actions, Langfuse (optional) |

Full picture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [/architecture](https://aura-henna-one.vercel.app/architecture) in the app.

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

Open http://localhost:3000 and choose **Try the demo**. Without Groq or Gemini keys, LLM calls fall back to a local Ollama model if `OLLAMA_BASE_URL` is set.

Optional extras: `docker compose up -d neo4j` enables the knowledge graph (without it, graph
checks report *unavailable* and invoices route to human review, which is the designed
behaviour). `python -m evals.generator.trust_datasets` regenerates the red-team, policy-QA and
trajectory datasets; `aura-eval redteam --gate` runs the attack corpus with no provider calls.

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Threat model](docs/THREAT_MODEL.md) · [Purchasing walkthrough](docs/PROCUREMENT_GUIDE.md) · [Evaluation evidence and limits](docs/EVALS.md) · [Model card](docs/MODEL_CARD.md) · [ADRs](docs/adr) · [Runbook](docs/RUNBOOK.md) · [Postmortems](docs/POSTMORTEMS.md) · [Costs](docs/COSTS.md) · [Validation](VALIDATION.md)

## Honest limits

- Every vendor, purchase order, invoice and payment is synthetic. Payments are recorded, never executed.
- Free-tier quotas cap live usage. When the daily budget is exhausted, the demo plays back recorded runs, clearly labelled as such.
- Model answers can be wrong. A citation is a pointer to evidence, not proof that the evidence supports the claim.
- Live extraction accuracy, judge-to-human agreement and end-to-end latency are **not yet measured** on a large enough sample to publish. What has actually been run is recorded in [VALIDATION.md](VALIDATION.md).
- The audit log is **tamper-evident, not tamper-proof**. Someone with database-owner access could rewrite the whole chain so it still verifies; the daily anchor committed to `audit-anchors/` is what makes that detectable.
- The fine-tuned GL coder has **not been trained yet** — the pipeline, serving app and promotion flow exist, but every figure in [docs/MODEL_CARD.md](docs/MODEL_CARD.md) reads "not measured" until a GPU run produces one.
- Red-team block rates are measured on a synthetic corpus of 50 attacks. They say something about these attacks, not about security in general.
