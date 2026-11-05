# Data model

PostgreSQL 16 with pgvector. Alembic owns the schema and enables the `vector` extension. Every table uses a 36-character UUID string primary key and an indexed `created_at`; tables in `models/platform.py` inherit both from the `Record` mixin.

## Tables

### traces — `models/records.py`
One captured local generation attempt.

`model`, `prompt`, `system`, `configuration` (JSON), `response`, `status`, `error`, `latency_ms`, `input_tokens`, `output_tokens`. `model` and `status` are indexed. Token counts are nullable because the provider does not always report them. RAG traces keep selected chunks and retrieval configuration in `configuration`. RAGAS LangChain callbacks also persist their internal model calls here.

### evaluation_runs — `models/records.py`
A standalone deterministic check outside any dataset: `name`, optional `trace_id`, `response`, `configuration`, `results` (JSON per rule), `score`, `passed`.

### prompts
`name`, `version`, `system`, `template`, `configuration`. `UniqueConstraint(name, version)`. Immutable: saving an existing name allocates the next version under a PostgreSQL advisory lock.

### evaluation_datasets / evaluation_cases
Dataset: `name`, `description`. Case: `dataset_id`, `question`, optional `expected`, optional stored `response`, `contexts` (JSON list), `checks` (JSON list of rule objects).

### dataset_runs
One batch execution. `dataset_id`, `configuration`, `score`, `passed`, `latency_ms`, `errors`, optional `metrics`, optional self-referencing `baseline_id`, `gate` (JSON thresholds and decision), and `case_snapshot` — the frozen cases as executed. The snapshot is what makes baseline comparison meaningful: changed cases or a different run mode invalidate comparison with an older baseline.

### evaluation_results
Per-case outcome: `run_id`, `case_id`, optional `trace_id`, optional `judge_review_id`, `response`, `score`, `passed`, `latency_ms`, `error`, `results` (per-rule detail).

### regression_tests
One row per dataset (`dataset_id` unique): the selected `baseline_id` and `thresholds`.

### documents / document_chunks
Document: `name`, `sha256` (unique — identical bytes reuse the existing document), extracted `content`, `embedding_model`, `chunk_count`. Chunk: `document_id` (`ON DELETE CASCADE`), `position`, `content`, `embedding` — `Vector(384)` on PostgreSQL, JSON under the SQLite test variant. A null embedding means the chunk is BM25-searchable but not indexed for vector search.

### judge_reviews / human_reviews
Judge review: `question`, `expected`, `response`, `contexts`, `configuration`, `verdict` (JSON), nullable `passed`/`score`, optional `trace_id`, `engine` (`local_judge` or `ragas`), `error`. Nullable score plus a stored error is how an unscored or invalid judgment is represented — no fallback number is written.

Human review: `judge_review_id` (unique — one current consensus rating per judge review), `reviewer`, `passed`, `score`, `feedback`. Reviewer is a recorded label, not an authenticated identity.

### experiments
`name`, `dataset_id`, `configurations` (JSON, 2–5 run configurations), `results` (JSON). Configuration and results are kept together so a comparison stays interpretable later.

### agent_runs
`task`, `configuration`, `steps` (ordered tool records with linked model request IDs), `response`, `metrics`, `passed`.

### failure_events
`event_id` (unique — idempotent ingestion; reuse with different content is a 409), `source`, `question`, `response`, `error`, `metadata_json`, indexed `status` (default `pending`), optional `case_id` once approved into a dataset.

### security_test_runs
`model`, `configuration`, `results` (JSON per attack case), `score`.

### marketing_reviews
`content`, `configuration`, `results`, `score`, `decision` (default `pending`), `reviewer`, `feedback`.

## What is deliberately absent

No users table, no session table, no reviewer identity. `API_KEY` authenticates a trusted shared workspace, not a person. Any claim about who reviewed something is a stored string.

## Migrations

```sh
cd backend && uv run alembic revision -m "<change>"
```

```sh
cd backend && uv run alembic upgrade head
```

Rules:

- Write both `upgrade` and `downgrade`. CI runs upgrade → `alembic check` (drift) → downgrade to base → upgrade again.
- Never edit a migration that has been applied anywhere; add a new one.
- `alembic check` must be clean: models and migrations cannot drift.
- Verify against a disposable database, never the working one:

```sh
python3 scripts/check-migrations.py
```

- Vector dimension changes are breaking. The column is 384-dimensional; changing the embedding model requires a migration plus reindexing every document.
- Back up before migrating a database with data you care about:

```sh
docker compose exec -T db pg_dump -U aura -d aura -Fc > backups/aura.dump
```

## Test storage

Pytest uses isolated SQLite with stubbed model calls, so `Vector(384)` falls back to its JSON variant. Behavior that depends on real pgvector cosine ordering or PostgreSQL advisory locks must also be checked against the live stack — see [TESTING.md](TESTING.md).
