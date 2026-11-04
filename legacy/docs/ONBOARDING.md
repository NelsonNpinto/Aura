# Onboarding — first day on AURA

Goal of this page: a running stack, a map of the repository, and one verified change.

## 1. Prerequisites

| Need | Version / note |
|---|---|
| Docker Desktop or Engine with Compose | Required for the complete runtime |
| Free ports | 5273 (web), 8200 (API), 5433 (PostgreSQL), 11434 (Ollama) |
| Disk | Images plus model weights; a 0.5B model is small, larger models are not |
| Python | 3.12+ only if you develop the backend on the host |
| Node | 22.12+ only if you develop the frontend on the host |
| `uv` | Backend dependency manager; `backend/uv.lock` is authoritative |

No paid API key is needed anywhere. Inference is local Ollama; embeddings are local Sentence Transformers.

## 2. Start the stack

```sh
python3 scripts/configure-local.py
```

```sh
docker compose up --build -d
```

On a macOS external drive (ExFAT/HFS with AppleDouble `._` files), Docker can fail reading resource-fork metadata. Use the staging helper instead; it copies source bytes to an internal cache and builds identical images:

```sh
python3 scripts/docker-up.py
```

Pull a model explicitly — nothing downloads a model behind your back:

```sh
docker compose exec ollama ollama pull qwen2.5:0.5b
```

Open http://localhost:5273. API docs: http://localhost:8200/docs. Health: `curl http://localhost:8200/api/v1/health`.

The 0.5B model exercises the pipeline. It is weak at judging and at adversarial prompts; treat its scores as pipeline evidence, not model quality evidence.

## 3. Repository map

```
backend/
  app/
    main.py               FastAPI app, middleware wiring, telemetry lifespan
    core/config.py        Pydantic settings (env-driven)
    core/middleware.py    Body-size limit, Bearer key, rate window, request IDs
    api/                  Routers, all under prefix /api/v1
      routes.py           Health, models, playground, prompts, evaluations, traces, overview
      datasets.py         Datasets, cases, runs, baselines, experiments, regressions
      knowledge.py        Documents, chunks, indexing, search, cited answers
      reviews.py          Judge reviews, human ratings, reliability, security, marketing, agents
      failures.py         Failure webhook, inbox, approval into datasets
      monitoring.py       Monitoring aggregates
      common.py           DB dependency, serialize/require/recent/save helpers
    services/             generation, datasets, ollama client, analytics
    evaluation/           deterministic checks, local rubric judge, RAGAS adapter
    rag/retrieval.py      BM25, pgvector cosine, hybrid RRF, optional CrossEncoder rerank
    agents/runner.py      Bounded LangGraph tool loop with an explicit allowlist
    security/packs.py     Six local adversarial cases
    models/               SQLAlchemy tables (records.py, platform.py)
    schemas/              Pydantic request/response contracts
    monitoring/           OpenTelemetry spans, Langfuse, LangChain trace capture
  alembic/                Migration environment and versions
  scripts/                check_quality.py, run_local_quality.py (release gates)
  tests/                  Pytest suite on isolated SQLite with stubbed models
frontend/
  src/pages/              One file per sidebar module
  src/services/api.ts     Axios client, base URL, API key header
  src/hooks/              useApi (fetch), useMutation (write)
  src/components/         Shared UI, platform widgets
  src/layouts/Workspace   Shell and navigation
scripts/                  Operational Python helpers (see below)
data/                     Release-gate fixtures (regression.json, model-regression.json)
infra/                    OTel collector config, Terraform example
security/promptfoo/       Prompt-injection CLI pack
docs/                     This documentation set
.github/workflows/        ci.yml (always on), model-evaluation.yml (manual/callable)
```

## 4. Operational scripts

| Script | Purpose |
|---|---|
| `scripts/configure-local.py [--observability]` | Create `.env` from the example and generate missing secrets. Never overwrites existing values. |
| `scripts/docker-up.py [--observability] [--build-only]` | Build from a metadata-free staging context, then start services. |
| `scripts/clean-macos-metadata.py` | Delete only AppleDouble `._` files inside project sources. |
| `scripts/smoke.py [--base-url] [--model] [--ragas]` | HTTP smoke run against the live stack; writes clearly named records. |
| `scripts/check-migrations.py` | Alembic upgrade/check/downgrade/re-upgrade in a disposable database. |
| `scripts/check-terraform.py [--fix]` | Terraform fmt/init/validate in Docker, provisioning nothing. |
| `scripts/run-dataset.py <dataset-id> [--mode] [--model] [--base-url]` | Run a saved dataset and exit nonzero on gate failure. |
| `backend/scripts/check_quality.py <fixture>` | Deterministic release gate, no inference. |
| `backend/scripts/run_local_quality.py <fixture> --model --threshold` | Real local-model release gate. |

## 5. First change, end to end

1. Branch: `git switch -c <topic>`.
2. Make the change (see [DEVELOPMENT.md](DEVELOPMENT.md) for the layer order).
3. Backend checks:

```sh
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

4. Frontend check:

```sh
npm --prefix frontend run build
```

5. If a schema changed, add a migration and verify the round trip:

```sh
python3 scripts/check-migrations.py
```

6. If behavior changed, run the smoke script against the live stack:

```sh
python3 scripts/smoke.py
```

7. Update the documents your change invalidates. [VALIDATION.md](VALIDATION.md) records what was actually executed — do not add claims you did not run.

## 6. Rules that are easy to get wrong here

- A deterministic rule score is not a factual quality score. A judge estimate is not a verified fact. Security tests passing is not a security guarantee. Keep that distinction in code, UI copy, and documents.
- Never seed synthetic "human" reviews. Human calibration tables are for real entered labels only.
- Unmeasured stays unmeasured. Do not substitute a fallback number for a failed judge or a non-finite metric.
- Prompt versions are immutable. Saving an existing name creates the next version.
- `.env`, Terraform state, and database dumps are private: they contain secrets, prompts, responses, and reviewer names.
