# Development guide

Docker is the reference runtime. Host development is for fast iteration on one layer at a time.

## Host backend

```sh
cd backend
uv sync --extra rag --python 3.12
```

Set `DATABASE_URL` and `OLLAMA_BASE_URL` from the root `.env` (host values: PostgreSQL on port 5433, Ollama on 11434). Then:

```sh
cd backend && uv run --extra rag alembic upgrade head
```

```sh
cd backend && uv run --extra rag uvicorn app.main:app --reload --port 8200
```

Omit `--extra rag` only if you are not touching embeddings, reranking, or RAGAS; those imports fail without it.

On an external filesystem, keep the virtual environment on an internal disk:

```sh
export UV_PROJECT_ENVIRONMENT=/path/to/internal/venv UV_LINK_MODE=copy
```

On macOS, run `python3 scripts/clean-macos-metadata.py` before host Alembic commands; it removes only AppleDouble `._` files.

## Host frontend

```sh
cd frontend && npm ci
```

```sh
cd frontend && npm run dev
```

Vite proxies `/api/v1` to the backend during development; in Docker the same path is served same-origin through Nginx. Never hardcode an absolute API host in a component.

## Settings

All settings come from `backend/app/core/config.py` (Pydantic `BaseSettings`, `.env`, unknown keys ignored).

| Setting | Default | Notes |
|---|---|---|
| `database_url` | local PostgreSQL | Compose injects its own internal URL |
| `ollama_base_url` | `http://localhost:11434` | `http://ollama:11434` inside Compose |
| `ollama_timeout_seconds` | 180 | Raise for slow CPU inference |
| `embedding_provider` | `sentence-transformers` | Or `ollama` |
| `embedding_model` | `sentence-transformers/all-MiniLM-L6-v2` | Must emit 384 dimensions |
| `reranker_model` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Downloaded on first rerank |
| `api_key` | empty | Shared workspace Bearer key when set |
| `webhook_secret` | empty | Webhook ingestion disabled while blank |
| `otel_endpoint`, `langfuse_*` | empty / local | Optional observability export |
| `request_limit_per_minute` | 120 | Per-client in-process window |

The chunk column is `Vector(384)`. An Ollama embedding model must emit 384 dimensions (`all-minilm` does, `nomic-embed-text` does not). Changing the embedding model in an indexed workspace requires reindexing every document.

Adding a setting to the root `.env` does not reach a container unless Compose passes it through — add it to the service `environment:` block too.

## Request path

Browser → Nginx (or Vite proxy) → FastAPI middleware (`safeguards`) → router → service → SQLAlchemy → PostgreSQL. `safeguards` enforces a 12 MB body limit, the optional Bearer key (health and the webhook are exempt — the webhook has its own secret), a 60-second rate window per client, and adds `X-Request-ID` and `X-Content-Type-Options`.

Routers live in `backend/app/api/` and all declare `APIRouter(prefix="/api/v1")`; `main.py` includes them. Shared helpers in `api/common.py`: `DB` (session dependency), `serialize`, `require` (404 on missing), `recent` (latest 100 by `created_at`), `save`.

## Adding a feature end to end

Work in this order; each step is independently testable.

1. **Migration** — `cd backend && uv run alembic revision -m "<change>"`, write explicit `upgrade`/`downgrade`. Never edit an applied migration.
2. **Model** — add or extend a class in `app/models/platform.py`. Inherit `Record` for the standard `id` + indexed `created_at`.
3. **Schema** — add the Pydantic input in `app/schemas/platform.py` with explicit bounds (`min_length`, `max_length`, `ge`, `le`) and `model_validator` for cross-field rules. Bounds are the API contract, not decoration.
4. **Service** — put logic in `app/services/` or the matching domain package (`evaluation/`, `rag/`, `agents/`). Routers stay thin.
5. **Route** — add the endpoint to the right router; return serialized records.
6. **Test** — add Pytest cases in `backend/tests/`; the suite runs on isolated SQLite with stubbed model calls.
7. **Types and client** — extend `frontend/src/types/` and `frontend/src/services/api.ts`.
8. **Page** — one page component per sidebar module in `frontend/src/pages/`; read with `useApi`, write with `useMutation`.
9. **Docs** — update [API_REFERENCE.md](API_REFERENCE.md), [DATA_MODEL.md](DATA_MODEL.md), [USER_GUIDE.md](USER_GUIDE.md) as applicable.

## Conventions

**Python.** Ruff with `line-length = 100`, target `py312`, rules `E4, E7, E9, F, I, UP`. Run `uv run ruff check .` and `uv run ruff format --check .`. Type-annotate with modern syntax (`str | None`). Comments explain why, not what; the existing code is comment-sparse.

**Pydantic.** Validate at the boundary and bound every field. Reject rather than coerce. JSON Schema checks use Draft 2020-12 with `$ref`/`$dynamicRef` rejected — schemas are inlined, never resolved over network or filesystem.

**SQLAlchemy.** `Mapped[...]` with `mapped_column`. Enforce invariants in the database (`UniqueConstraint`, foreign keys, `ondelete="CASCADE"` on chunks) rather than only in Python. Prompt version allocation uses a PostgreSQL advisory lock.

**TypeScript/React.** Strict build (`tsc -b && vite build`). Function components, Tailwind v4 utilities, shared primitives in `components/ui`. Keep types in `src/types/` aligned with backend schemas.

**Measurement honesty.** Deterministic rule results, model estimates, and human labels are three separate record types and must stay separate in the UI as well. A failed or non-finite metric is stored unscored with its error — never defaulted to a passing value. Do not introduce code paths that create human-looking labels.

**Agent safety.** Tools are allowlisted (`calculator`, `knowledge_search`, `customer_lookup`). The calculator parses a restricted arithmetic AST and never executes Python. Customer lookup accepts only the labeled mock IDs. A tool budget bounds the loop.

## Local verification before pushing

```sh
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
```

```sh
npm --prefix frontend run build
```

```sh
python3 scripts/smoke.py
```

Full test and gate detail is in [TESTING.md](TESTING.md).
