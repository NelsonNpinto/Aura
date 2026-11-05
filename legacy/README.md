# AURA — AI Reliability & Evaluation Platform

A local-first portfolio application for building, evaluating, debugging, and testing AI applications. React/TypeScript frontend, FastAPI backend, PostgreSQL/pgvector storage, and Ollama inference. No paid API is needed.

## What works

| Module | Working workflow |
|---|---|
| Overview | Real request/run counts, deterministic scores, model latency, usage, failures, and available judge estimates |
| Playground & prompts | Local model discovery, generation settings, responses, token usage, immutable saved prompt versions, side-by-side instruction comparison |
| Knowledge Base | PDF/TXT/Markdown extraction, cleaning/chunking, local Sentence Transformer embeddings, pgvector similarity, BM25/hybrid retrieval, optional CrossEncoder reranking, chunk inspection, deletion, and cited answers |
| Evaluations | JSON/schema validity, required fields/keywords, forbidden phrases, exact answers, and empty-output detection |
| AI Judge | Validated local rubric judgments and RAGAS adapter for faithfulness, relevance, reference-based context precision/recall |
| Judge Reliability | Human consensus rating interface, stored labels, agreement, Cohen's kappa, score error, false passes/fails |
| Experiments | Repeatable model/prompt/temperature/retrieval comparisons, saved configurations, deterministic scores, usage/latency, and optional local judge metrics |
| Agents | Bounded LangGraph workflow with arithmetic, knowledge search, mock customer lookup, tool/argument checks, failure traces, and exact-answer task checks |
| Regression Tests | Datasets/cases, stored or fresh responses, immutable case snapshots, baselines, quality/latency/error thresholds, and CLI release gates |
| Traces & Monitoring | Saved successful/failed calls, request IDs, prompt/configuration/usage, retrieval evidence, tool step links, error rates, latency percentiles, OpenTelemetry and Langfuse export |
| Failure Inbox | Authenticated, deduplicated webhook ingestion, conflict handling, and explicit approval into regression datasets |
| Security | Six local adversarial cases, stored responses/results, plus a matching promptfoo CLI pack |
| Marketing Evaluation | Explicit brand/product/audience/claim/discount/format checks, stored reviews, and a human approval decision |

All sidebar modules have implemented pages and APIs. Unavailable metrics stay unmeasured. An output-rule score is not a factual quality score; a judge estimate is not a verified fact. Security test success is not a security guarantee.

## Start the platform

Prerequisites: Docker Desktop/Engine with Compose, available ports **5273**, **8200**, **5433**, and **11434**, and enough space for images and models. The optional observability stack uses more memory and disk; it is not needed for core workflows.

```sh
python3 scripts/configure-local.py
# Creates .env from .env.example when needed and generates local secrets.
docker compose up --build -d
```

On a macOS external drive, Docker can fail while reading AppleDouble resource metadata. Use the included staging helper; it copies source bytes to an internal cache and builds the same images without xattrs:

```sh
python3 scripts/docker-up.py
```

Open **http://localhost:5273**. API docs: **http://localhost:8200/docs**.

Download a local model explicitly:

```sh
docker compose exec ollama ollama pull qwen2.5:0.5b
# Or a larger model when your hardware allows it:
docker compose exec ollama ollama pull llama3.2:1b
```

The 0.5B model is useful for testing the pipeline, but performs poorly on demanding judgments and adversarial tasks. On macOS, containerized Ollama uses CPU inference. A native Ollama installation can use Apple GPU acceleration; set the backend's `OLLAMA_BASE_URL` to `http://host.docker.internal:11434` when adapting Compose for that setup.

The backend image includes the CPU-only RAG dependencies and applies Alembic migrations before serving requests. Database data, model files, and embedding model caches use persistent volumes. Stop the stack with `docker compose down`; this preserves volumes.

## First useful workflow

1. Open Playground, choose an installed model, and run a prompt.
2. Save a named prompt configuration; changing the same name creates a new immutable version.
3. Choose **Evaluate this response**, select explicit output rules, and inspect the score/explanations.
4. Upload a document in Knowledge Base. Embedding creation downloads a local model on first use.
5. Inspect BM25, vector, and hybrid retrieval before generating a cited answer.
6. Use AI Judge with a question, response, reference answer, context, and rubric. Add genuine human ratings in Judge Reliability before making reliability claims.
7. Create a dataset in Regression Tests, add cases, run it, and select a baseline. New runs show quality-gate results. Changed cases/rules invalidate an older baseline.
8. Compare model or prompt variants in Experiments. Optional judge scoring adds real model requests per response.
9. Inspect agent tools, failures, security cases, and marketing approval queues using their dedicated pages.

Each module contains short explanations of what its measurements mean. See [docs/USER_GUIDE.md](docs/USER_GUIDE.md) for concepts and operating details.

## Local observability

The optional stack includes Langfuse v4 web/worker, its own PostgreSQL, ClickHouse, Redis, object storage, and an OpenTelemetry collector. The topology follows the [official Langfuse Compose example](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml). Credentials are generated into your ignored `.env`, not hardcoded into source.

```sh
python3 scripts/configure-local.py --observability
python3 scripts/docker-up.py --observability
# On a normal filesystem, the equivalent command is:
docker compose -f docker-compose.yml -f docker-compose.observability.yml --profile observability up --build -d
```

Langfuse: **http://localhost:3300**. The local account email is `developer@aura.local`; its generated password is `LF_ADMIN_PASSWORD` in your `.env`. A project is initialized with the generated local SDK keys. Prompts/responses remain in AURA's database; custom export spans omit their full content by default. Monitoring distinguishes configuration from confirmed delivery. This build was also checked for actual observation receipt.

To stop the complete optional stack:

```sh
docker compose -f docker-compose.yml -f docker-compose.observability.yml --profile observability down
```

## Deploying to Vercel

The repository root carries a `vercel.json` that runs the API and the interface
as two Vercel services on one origin, so no CORS configuration is involved.
Ollama cannot run there: point `OLLAMA_BASE_URL` at a reachable model host, or
every model-backed page returns a connection error while evaluations, datasets,
traces, and the dashboard keep working. The deployed bundle omits the `rag`
extra, which takes the function from roughly 1.5 GB to 134 MB; vector search
then embeds through Ollama instead of local weights.

`docs/VERCEL.md` covers the database, migrations, environment variables, and
exactly what degrades without a model.

## API access and failure webhook

AURA publishes ports on loopback. Set `API_KEY` to require a workspace Bearer key for API endpoints; enter it in Settings for the current browser session. Health remains public. Webhooks use their separate `WEBHOOK_SECRET` and remain disabled when that secret is blank.

```text
POST /api/v1/webhooks/ai-failure
Authorization: Bearer <WEBHOOK_SECRET>
Content-Type: application/json

{
  "event_id": "unique-event-id",
  "source": "support-assistant",
  "question": "What is the refund window?",
  "response": "An unsupported answer",
  "error": "Policy violation",
  "metadata": {"environment": "development"}
}
```

The same ID/payload returns the original event. Conflicting ID reuse returns 409. Approval into a dataset is idempotent. Keep `.env` and Terraform state private. Passwords containing URL-reserved characters need URL encoding in database connection strings; generated hexadecimal secrets avoid that issue.

## Development and verification

Use Python 3.12+ and Node 22.12+. Dependencies are locked in `backend/uv.lock`, `frontend/package-lock.json`, and the promptfoo pack's lockfile.

```sh
cd backend
uv sync --extra rag --python 3.12
# Set DATABASE_URL/OLLAMA_BASE_URL from the root .env for host development.
uv run --extra rag alembic upgrade head
uv run --extra rag uvicorn app.main:app --reload --port 8200
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

On external filesystems, keep the Python environment on an internal disk with `UV_PROJECT_ENVIRONMENT=/path/to/internal/venv` and `UV_LINK_MODE=copy`. Before host Alembic commands on macOS, `python3 scripts/clean-macos-metadata.py` removes only AppleDouble metadata in project sources. Prefer Docker for the complete runtime.

```sh
cd backend
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_quality.py ../data/regression.json
```

From the root:

```sh
npm --prefix frontend run build
python3 scripts/smoke.py
# Optional real RAGAS smoke check:
python3 scripts/smoke.py --ragas
```

The smoke script creates clearly named integration-test records in the running workspace. It never creates automated labels that pretend to be human reviews. Unit/API tests use isolated SQLite storage and controlled model stubs; real Docker/PostgreSQL/Ollama checks are recorded separately in [docs/VALIDATION.md](docs/VALIDATION.md).

## Release gates and security pack

```sh
# Real local-model output quality gate:
cd backend
uv run python scripts/run_local_quality.py ../data/model-regression.json --model qwen2.5:0.5b --threshold 1

# Gate against a saved API dataset and its baseline:
# From the repository root:
python3 scripts/run-dataset.py <dataset-id> --mode generate --model <installed-model>

# Prompt injection checks, from the repository root:
npm --prefix security/promptfoo ci
npm --prefix security/promptfoo test
```

These commands return nonzero for failed gates. The always-on CI runs Python tests/lint, frontend compilation, Docker builds, PostgreSQL migration upgrade/downgrade/drift checks, a configurable deterministic gate, and Terraform validation. `model-evaluation.yml` supports manual runs and reusable workflow calls with real Ollama inference. Add it as a required release job/branch check in your GitHub repository; no repository was created or pushed automatically.

The Terraform example provisions only a separate local Docker database if you explicitly apply it. `python3 scripts/check-terraform.py` validates it without provisioning. See [infra/terraform/README.md](infra/terraform/README.md).

## Scope and limits

This is an implemented single-workspace local platform, not a hosted multi-tenant product. API keys identify a trusted workspace, not individual users. Human review names are recorded labels, not authenticated identities. Interactive batches are synchronous and limited to 50 cases; use smaller datasets for local CPU models. There is no distributed job queue or automatic production deployment. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) before adapting it to a shared environment.

Semantic brand fit, factual truth, security, and judge reliability require evidence beyond deterministic keyword rules. Agent exact-answer/tool checks establish only the specified task conditions. Local inference has no provider API fee, but electricity/hardware cost is not estimated.
