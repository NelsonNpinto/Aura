# Deploying AURA on Vercel

Both the API and the interface run in one Vercel project using
[Services](https://vercel.com/docs/services). `vercel.json` at the repository
root defines them: `backend/` (FastAPI, entrypoint `app.main:app`) receives
`/api/*`, and `frontend/` (Vite) receives everything else. Services share one
origin, so no CORS configuration is involved.

## What does not run on Vercel

**Ollama.** Vercel runs request-scoped functions with no GPU and no persistent
process, so the model server must live elsewhere. Set `OLLAMA_BASE_URL` to a
reachable Ollama host. Until you do, Playground, AI Judge, Agents, Security, and
Marketing return connection errors. Evaluations, Datasets, Regression tests,
Traces, Failure inbox, and the dashboard work without any model.

**Local embedding weights.** The deployed bundle omits the `rag` optional
dependency group (torch, sentence-transformers, RAGAS, langchain-huggingface),
which keeps the function at roughly 134 MB instead of 1.5 GB. Vector search
still works by embedding through Ollama: set `EMBEDDING_PROVIDER=ollama` and
`EMBEDDING_MODEL=all-minilm`. The chunk column is `Vector(384)`, so the model
must emit 384 dimensions — `all-minilm` does, `nomic-embed-text` does not.

Reranking and RAGAS scoring have no Ollama equivalent and return HTTP 503 when
requested. BM25 retrieval is pure Python and is unaffected.

## Steps

### 1. Create the database

In the Vercel dashboard, open **Storage → Create → Neon**. Neon includes
pgvector. Copy the **pooled** connection string: serverless functions open many
short-lived connections, and the engine uses `NullPool` when `VERCEL` is set.

Convert the scheme for SQLAlchemy — Neon gives `postgresql://`, the application
needs `postgresql+psycopg://`:

```sh
postgresql+psycopg://USER:PASSWORD@HOST-pooler.REGION.aws.neon.tech/DB?sslmode=require
```

### 2. Apply migrations

Vercel has no release phase, so run Alembic once from your machine against the
same URL. The deployed function never migrates.

```sh
cd backend
DATABASE_URL='postgresql+psycopg://...' uv run alembic upgrade head
```

### 3. Set environment variables

Project **Settings → Environment Variables**:

| Variable | Value | Required |
|---|---|---|
| `DATABASE_URL` | Neon pooled URL, `postgresql+psycopg://` scheme | yes |
| `API_KEY` | a long random string | yes — the API is public |
| `OLLAMA_BASE_URL` | your Ollama host | for any model feature |
| `EMBEDDING_PROVIDER` | `ollama` | for vector search |
| `EMBEDDING_MODEL` | `all-minilm` | for vector search |
| `VITE_API_TIMEOUT_MS` | `55000` | recommended |
| `WEBHOOK_SECRET` | random string | for failure ingestion |

`API_KEY` matters more here than locally. Compose binds to loopback; a Vercel
deployment is reachable by anyone. With it set, every route except `/health`
and the signed webhook requires `Authorization: Bearer <key>`. Enter the same
value in the app's Settings page, which stores it in `sessionStorage`.

`VITE_API_TIMEOUT_MS` must stay below the function's `maxDuration`, which
`vercel.json` sets to 60 seconds. Hobby and Pro plans cap duration differently;
raise both together if generation needs longer, or expect long requests to be
cut off mid-flight.

### 4. Import the repository

On the Vercel import screen, pick the repository root — **not** "Import single
project" on `backend` or `frontend`. The root `vercel.json` already describes
both services, so the multi-service prompt needs no further input.

### 5. Verify

```sh
curl https://YOUR-DEPLOYMENT.vercel.app/api/v1/health
```

Then open the deployment, enter the API key in Settings, and run the evaluation
workflow from the README. It needs no model and exercises the database path
end to end.

## Rate limiting caveat

`app/core/middleware.py` keeps its request window in a module-level dictionary.
Each function instance has its own, so the effective limit scales with instance
count rather than being a global ceiling. It is a local-development guard, not
a production control; put a real limiter in front of the deployment if abuse
matters.
