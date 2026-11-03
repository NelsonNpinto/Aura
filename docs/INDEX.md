# AURA documentation index

Every document in this set describes the implemented local platform. Nothing here claims hosted, multi-tenant, or production operation.

## Read in this order

| # | Document | Read it when |
|---|---|---|
| 1 | [../README.md](../README.md) | You want the shortest path from clone to a running stack. |
| 2 | [ONBOARDING.md](ONBOARDING.md) | Day one. Prerequisites, first run, repository map, first change. |
| 3 | [USER_GUIDE.md](USER_GUIDE.md) | You operate the product: prompts, datasets, judging, retrieval, agents. |
| 4 | [ARCHITECTURE.md](ARCHITECTURE.md) | You need the request path, service boundaries, and scoring rules. |
| 5 | [DATA_MODEL.md](DATA_MODEL.md) | You touch the database, write a migration, or query records. |
| 6 | [DEVELOPMENT.md](DEVELOPMENT.md) | You write code: host setup, layout, conventions, adding a feature end to end. |
| 7 | [API_REFERENCE.md](API_REFERENCE.md) | You call the API from scripts, CI, or another service. |
| 8 | [TESTING.md](TESTING.md) | You run tests, release gates, smoke checks, or CI. |
| 9 | [CONTRIBUTING.md](CONTRIBUTING.md) | You open a change: branch, commit, review checklist, evidence rules. |
| 10 | [DEPLOYMENT.md](DEPLOYMENT.md) | You configure environments, back up data, or debug a running stack. |
| 11 | [VALIDATION.md](VALIDATION.md) | You want evidence of what was actually executed and its limits. |
| 12 | [ROADMAP.md](ROADMAP.md) | You want build stages and declared future extensions. |

## By role

- **Operator / evaluator:** USER_GUIDE → DEPLOYMENT → VALIDATION.
- **Backend developer:** ONBOARDING → DEVELOPMENT → DATA_MODEL → API_REFERENCE → TESTING.
- **Frontend developer:** ONBOARDING → DEVELOPMENT (frontend section) → API_REFERENCE.
- **Reviewer / hiring reader:** README → ARCHITECTURE → VALIDATION → ROADMAP.
- **Infrastructure:** DEPLOYMENT → [../infra/terraform/README.md](../infra/terraform/README.md) → TESTING (CI section).

## Machine-readable evidence files

| File | Content |
|---|---|
| `SMOKE_RESULTS.json` | HTTP smoke run against real local services. |
| `MODEL_QUALITY_RESULT.json` | Real local-model release-gate output. |
| `AGENT_RESULT.json` | One recorded LangGraph agent run with tool steps. |
| `RAGAS_RESULT.json` | RAGAS metric output from local Ollama + local embeddings. |
| `EXPERIMENT_RESULT.json` | Experiment comparison with usage, latency, judge metrics. |
| `DEPENDENCY_AUDIT.json` | Frontend and promptfoo dependency audit summary. |

These are recorded outputs from specific runs, not continuously updated status.
