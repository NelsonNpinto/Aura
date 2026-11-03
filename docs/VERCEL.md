# From nothing to live

Everything AURA needs, what each piece costs, and the order to do it in. Part 1
gets it running on your machine. Part 2 is the decision that governs how much
of the app works once deployed. Part 3 puts it on the internet.

## What the application actually requires

| Piece | Why | Can it be skipped |
|---|---|---|
| PostgreSQL with pgvector | every trace, evaluation, dataset, and chunk | no — the API will not start usefully |
| An Ollama server | all generation, the judge, agents, security and marketing packs | yes, and roughly half the app goes with it |
| An embedding model | vector and hybrid retrieval | yes — BM25 retrieval still works |
| Node 22.12+, Python 3.12+ | building each half | only if you deploy without building locally |
| Docker with Compose | the local stack | yes, if you run both halves on the host |

No paid model API is required anywhere. There is no OpenAI, Anthropic, or
Gemini key in this codebase. The one unavoidable cost of a live deployment is
somewhere to run Ollama, and only if you want the model-backed half.

## Part 1 — Run it locally

Ports 5273, 8200, 5433, and 11434 must be free.

```sh
cp .env.example .env
python3 scripts/configure-local.py
docker compose up --build -d
docker compose exec ollama ollama pull llama3.2:1b
```

Open http://localhost:5273. `configure-local.py` writes a random
`POSTGRES_PASSWORD` and `WEBHOOK_SECRET` without printing them or overwriting
values you already set.

`llama3.2:1b` is the smallest model worth judging anything with. `qwen2.5:0.5b`
is faster and fine for checking that the pipeline moves, but it fails most of
its own evaluations — that is the model, not a bug.

To confirm the whole path end to end, open Evaluations before any model is
installed, paste `Refunds are available within 30 days.`, select **Non-empty
response** and **Required keywords** with `refunds, 30 days`, and run at a 100%
threshold. Both checks pass. Remove `30 days` and it scores 50% and fails. That
exercises the API and the database without touching inference.

## Part 2 — Decide where inference runs

This is the decision that determines how much of the deployed app works. Vercel
runs request-scoped functions with no GPU and no persistent process, so Ollama
cannot live there. Pick one.

### Option A — Self-hosted Ollama

A small CPU VPS or a Fly.io machine running the `ollama/ollama` image. RAM is
the binding constraint, not CPU: a 256 MB instance cannot hold any usable
model, so budget a few GB. Expect somewhere between $5 and $25 a month
depending on provider and size.

This is the only option where **everything** works, because you control which
models are pulled — including `all-minilm` for embeddings, which keeps vector
search alive.

An Ollama server open to the internet is free compute for anyone who finds it,
and Ollama has no authentication of its own. Setting `OLLAMA_API_KEY` alone
changes nothing on a self-hosted server: the application sends the bearer
token, and a plain `ollama serve` ignores it.

Something in front has to check it. Run Ollama bound to loopback or a private
network and put nginx, Caddy, or a Cloudflare Tunnel ahead of it, rejecting any
request whose `Authorization` header does not match. Then set the same value as
`OLLAMA_API_KEY` here.

Ollama also refuses requests whose `Host` header is not localhost, as DNS
rebinding protection, so the proxy must rewrite `Host` or the external name
must be added to `OLLAMA_ORIGINS`. Without that the proxy returns 403 and the
cause is not obvious.

Binding Ollama straight to `0.0.0.0` with no proxy is the mistake to avoid; it
is why scans keep finding open Ollama servers.

### Option B — Hosted Ollama

`OLLAMA_BASE_URL=https://ollama.com` with an `OLLAMA_API_KEY` from
ollama.com/settings/keys. Pay per token, no infrastructure.

Two caveats worth testing before committing: the hosted API documents
`/api/chat`, while this application calls `/api/generate`, and the cloud model
catalogue is built around large models, so a 384-dimension embedding model such
as `all-minilm` may not be offered. If `/api/generate` is unavailable the
adapter in `app/services/ollama.py` needs a small change; if embeddings are
unavailable, vector search stays on BM25.

Verify both before relying on it:

```sh
curl -H "Authorization: Bearer $OLLAMA_API_KEY" https://ollama.com/api/tags
```

### Option C — No inference

Free. Deploy with `OLLAMA_BASE_URL` unset.

Working: Evaluations, Datasets, Regression tests, Traces, Failure inbox,
Overview, Settings. These are the deterministic core of the project.

Not working: Playground, AI Judge, Agents, Security, Marketing. Each returns a
connection error rather than failing silently.

## Part 3 — Deploy

### 3.1 Create the database

Vercel dashboard → **Storage → Create → Neon**. pgvector is included.

Copy the **pooled** connection string — its hostname contains `-pooler`.
Serverless opens many short-lived connections, which is why the engine switches
to `NullPool` when `VERCEL` is set. The direct string will exhaust its
connection limit.

Paste it as-is. `postgresql://`, `postgres://`, and `postgresql+psycopg://` are
all accepted; the first two are rewritten to psycopg 3, which is the driver
this project installs.

Skip the integration's "Connect a Project" step. It writes a `STORAGE_URL`
variable, while the application reads `DATABASE_URL`.

### 3.2 Apply migrations

Vercel has no release phase, and the deployed function never migrates. Run
Alembic once from your machine against the same URL:

```sh
cd backend
DATABASE_URL='postgresql+psycopg://...' uv run alembic upgrade head
```

### 3.3 Set environment variables

Project **Settings → Environment Variables**:

| Variable | Value | When |
|---|---|---|
| `DATABASE_URL` | Neon pooled URL, `postgresql+psycopg://` scheme | always |
| `API_KEY` | a long random string | always |
| `OLLAMA_BASE_URL` | your Ollama host | options A and B |
| `OLLAMA_API_KEY` | key your proxy or host validates | options A and B |
| `EMBEDDING_PROVIDER` | `ollama` | for vector search |
| `EMBEDDING_MODEL` | `all-minilm` | for vector search |
| `VITE_API_TIMEOUT_MS` | `55000` | recommended |
| `WEBHOOK_SECRET` | random string | for failure ingestion |

`API_KEY` matters far more here than locally. Compose binds every port to
loopback; a Vercel deployment answers anyone. With it set, every route except
`/api/v1/health` and the signed webhook requires `Authorization: Bearer <key>`.
Enter the same value in the app's Settings page, which holds it in
`sessionStorage`.

`VITE_API_TIMEOUT_MS` must stay below the function's `maxDuration`, which
`vercel.json` sets to 60 seconds. Raise both together if generation needs
longer, or long requests are cut off mid-flight.

`EMBEDDING_MODEL` must emit 384 dimensions, because the chunk column is
`Vector(384)`. `all-minilm` does. `nomic-embed-text` is 768 and will fail on
insert.

### 3.4 Import the repository

On the Vercel import screen, choose the **repository root**. Do not use "Import
single project" on `backend` or `frontend` — the root `vercel.json` already
describes both services and the routing between them.

### 3.5 Verify

```sh
curl https://YOUR-DEPLOYMENT.vercel.app/api/v1/health
```

Then open the deployment, enter the API key in Settings, and run the Part 1
evaluation workflow. It needs no model and proves the database path.

## How the deployment is put together

`vercel.json` defines two services on one origin. `backend/` is a FastAPI
service with entrypoint `app.main:app` and takes `/api/*`; `frontend/` is a
Vite build and takes everything else. Vercel hands the service the original
request path, so `/api/v1/health` arrives intact at the existing `/api/v1`
router prefix. One origin means no CORS configuration exists or is needed.

The deployed bundle omits the `rag` optional dependency group — torch,
sentence-transformers, RAGAS, langchain-huggingface — which is the difference
between a 1.5 GB function and a 134 MB one. Vercel installs optional groups
only when asked, so this needs no configuration.

Consequences, all of them deliberate:

- Vector search embeds through Ollama rather than local weights.
- Reranking returns HTTP 503. There is no Ollama equivalent.
- RAGAS scoring returns HTTP 503.
- BM25 retrieval is pure Python and is unaffected.

## Two things that are not production-grade

**Rate limiting.** `app/core/middleware.py` keeps its window in a module-level
dictionary. Every function instance has its own, so the effective ceiling
scales with instance count instead of being global. It is a development guard.
Put a real limiter in front of the deployment if abuse is a concern.

**Scoring.** An output-check score is the fraction of explicit deterministic
rules that passed. It is not a measure of factual quality, and a small model is
not a trustworthy judge of anything, including itself.
