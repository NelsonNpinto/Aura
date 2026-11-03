# Testing and release gates

Four layers, each with different evidence value: unit/API tests, real-service smoke checks, release gates, and the adversarial pack. None of them establishes factual accuracy or security.

## 1. Unit and API tests

```sh
cd backend && uv run pytest -q
```

Isolated SQLite storage and controlled model stubs, so the suite is fast, offline and deterministic. Files: `backend/tests/conftest.py`, `test_platform.py`, `test_evaluations.py`, `test_playground.py`.

Covered: deterministic checks and strict JSON, request validation, trace storage and errors, immutable prompt versions, dataset snapshots and baseline drift, generation failures, experiments, document extraction including real PDF bytes, duplicate documents, vector/hybrid/scoped retrieval, judge validation, unsupported claims, absent-context faithfulness, human agreement and kappa, calculator restrictions, bounded agent completion, webhook authentication/idempotency/conflict/approval, API access control, marketing approval gates, rate limits, release-gate exit codes, RAGAS callback usage tracing.

Limits of this layer: SQLite substitutes JSON for `Vector(384)`, model calls are stubbed, and PostgreSQL advisory-lock behavior is not exercised. Anything depending on real pgvector ordering, real inference, or locking needs layer 2.

Lint and format must also pass:

```sh
cd backend && uv run ruff check . && uv run ruff format --check .
```

Frontend compilation is the frontend gate:

```sh
npm --prefix frontend run build
```

## 2. Real-service smoke checks

Requires the Docker stack running with a pulled model.

```sh
python3 scripts/smoke.py
```

```sh
python3 scripts/smoke.py --ragas
```

Options: `--base-url` (default `http://127.0.0.1:5273`), `--model` (default `qwen2.5:0.5b`), `--ragas` to include a real RAGAS run.

It exercises generation, standalone evaluation, prompt saving, datasets, baseline comparison, experiments, upload and indexing, chunk inspection, BM25/vector/hybrid search, cited answers, judging, agent execution, security tests, marketing reviews, authenticated webhook ingestion and duplicates, monitoring and trace detail, and writes `docs/SMOKE_RESULTS.json`.

It creates clearly named integration records in the running workspace. It never writes a label that pretends to be a human review.

## 3. Migration round trip

```sh
python3 scripts/check-migrations.py
```

Creates a disposable database, runs upgrade → `alembic check` → downgrade → upgrade → `alembic check`, then drops it. The application database is untouched. CI runs the same sequence against a `pgvector/pgvector:pg16` service.

## 4. Release gates

Deterministic gate — no inference, suitable for every push:

```sh
cd backend && uv run python scripts/check_quality.py ../data/regression.json
```

Real local-model gate — pulls real output through the rules:

```sh
cd backend && uv run python scripts/run_local_quality.py ../data/model-regression.json --model qwen2.5:0.5b --threshold 1
```

Saved-dataset gate against its baseline, over HTTP:

```sh
python3 scripts/run-dataset.py <dataset-id> --mode generate --model qwen2.5:0.5b
```

All three exit nonzero on failure. `AURA_MIN_SCORE` configures the deterministic threshold in CI.

A gate failure is a result. Do not relax a threshold to make a run pass without recording why.

## 5. Adversarial pack

```sh
npm --prefix security/promptfoo ci
```

```sh
npm --prefix security/promptfoo test
```

Six local cases: instruction override, secret disclosure, malicious retrieved instructions, claimed unauthorized tool use, format bypass, prompt extraction. Markers are synthetic test strings; the unauthorized-tool case inspects output claims and connects no real sensitive tool.

Recorded result: 2 passing, 4 failing with the small model and zero provider errors — detected weaknesses, not a security assessment. Also check `.promptfoo-audit.json` and `docs/DEPENDENCY_AUDIT.json` for dependency audits.

## 6. Terraform

```sh
python3 scripts/check-terraform.py
```

`fmt -check`, `init -backend=false`, `validate` in Docker. Nothing is provisioned. `--fix` applies formatting.

## CI

`.github/workflows/ci.yml`, on every push and pull request:

| Job | Steps |
|---|---|
| `backend` | `uv sync --frozen`, ruff check, ruff format check, pytest, deterministic gate |
| `database-migrations` | pgvector service; upgrade, `alembic check`, downgrade to base, upgrade |
| `frontend` | `npm ci`, `npm run build` |
| `containers` | `docker compose build` |
| `terraform` | fmt check, init, validate |

`.github/workflows/model-evaluation.yml` — manual `workflow_dispatch` or reusable `workflow_call`, inputs `model` (default `qwen2.5:0.5b`) and `threshold` (default `1`). It starts `ollama/ollama:0.13.5`, pulls the model, runs `run_local_quality.py`, and uploads `quality-result.json`. Add it as a required release check in your repository; nothing is pushed or required automatically.

Lockfiles are authoritative: `backend/uv.lock` (`uv sync --frozen`), `frontend/package-lock.json` (`npm ci`), and the promptfoo lockfile.

## Pre-push sequence

```sh
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
```

```sh
npm --prefix frontend run build
```

```sh
python3 scripts/check-migrations.py
```

```sh
python3 scripts/smoke.py
```

Skip steps 3 and 4 only when no schema and no runtime behavior changed. Record what you actually ran — [VALIDATION.md](VALIDATION.md) is evidence, not a wish list.
