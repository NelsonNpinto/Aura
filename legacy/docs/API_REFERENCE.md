# API reference

Base URL: `http://localhost:8200` (direct) or `http://localhost:5273/api/v1/...` same-origin through the frontend. Interactive OpenAPI: `http://localhost:8200/docs`. Every path below is prefixed `/api/v1`.

## Authentication

| Surface | Credential | Behavior |
|---|---|---|
| All `/api/v1` endpoints | `Authorization: Bearer <API_KEY>` | Enforced only when `API_KEY` is set. 401 otherwise: `{"detail": "API key required. Enter it in Settings."}` |
| `GET /health` | none | Always public |
| `POST /webhooks/ai-failure` | `Authorization: Bearer <WEBHOOK_SECRET>` | Separate secret; 503 while the secret is blank |

The workspace key identifies a trusted workspace, not a user. In the browser, enter the key in Settings for the current session. Scripts read `API_KEY` from the environment.

## Middleware behavior

| Condition | Response |
|---|---|
| Body over 12 MB, or missing/non-numeric `Content-Length` | 413 `Request body exceeds 12 MB` |
| More than `REQUEST_LIMIT_PER_MINUTE` (default 120) requests per client in 60 s | 429 with `Retry-After: 60` |
| Unknown record id | 404 `<Model> not found` |
| Pydantic validation failure | 422 with field detail |

Every response carries `X-Request-ID` and `X-Content-Type-Options: nosniff`. List endpoints return the latest 100 records by `created_at` descending.

## Core — `api/routes.py`

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness; public |
| GET | `/models` | Models installed in local Ollama |
| GET | `/overview` | Dashboard counts, scores, latency, usage, failures |
| POST | `/playground/generate` | One local generation; stores a trace |
| GET/POST | `/prompts` | List prompts / save a named prompt (new immutable version) |
| GET/POST | `/evaluations` | List standalone evaluations / run deterministic checks |
| GET | `/traces` | Recent request traces |
| GET | `/traces/{trace_id}` | One trace with configuration, usage, evidence |

**`POST /playground/generate`** — `model` (pattern-restricted, ≤200), `prompt` (1–32000), `system` (≤16000), `temperature` 0–2 (default 0.2), `max_tokens` 1–8192 (default 512), `seed` (default 42), `format` (`"json"` or a JSON Schema object).

**`POST /prompts`** — `name` (1–200), `system` (≤16000), `template` (1–32000), `configuration` (object). Reusing a name creates the next version; existing versions are never edited.

**`POST /evaluations`** — `name`, `response` (≤64000), optional `trace_id`, `checks` (1–30), `threshold` 0–1 (default 1).

### Check object

```json
{"kind": "required_keywords", "values": ["30 days"]}
```

| `kind` | Required field | Semantics |
|---|---|---|
| `non_empty` | — | Output is not blank |
| `valid_json` | — | Whole response parses as JSON; fenced JSON and NaN/Infinity rejected |
| `json_schema` | `schema_definition` | Draft 2020-12, inline only — `$ref`/`$dynamicRef` rejected |
| `required_keywords` | `values` | Case-insensitive substrings, each ≤1000 chars |
| `forbidden_phrases` | `values` | Case-insensitive substrings must be absent |
| `exact_match` | `expected` | Outer whitespace trimmed, case-sensitive |

A case score is the equal-weight fraction of rules passed.

## Datasets, runs, experiments — `api/datasets.py`

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/datasets` | List / create (`name`, `description`) |
| GET/POST | `/datasets/{dataset_id}/cases` | List / add a case |
| PUT | `/cases/{case_id}` | Update a case (invalidates older baseline comparison) |
| POST | `/datasets/{dataset_id}/run` | Execute the dataset |
| PUT | `/datasets/{dataset_id}/baseline` | Select a baseline and thresholds |
| GET | `/dataset-runs`, `/dataset-runs/{run_id}` | Run history / full run with per-case results |
| GET | `/regressions` | Configured baselines and thresholds |
| GET/POST | `/experiments` | List / create a comparison |

**Case input** — `question` (1–32000), optional `expected`, optional stored `response`, `contexts` (≤20), `checks` (1–30, default `non_empty`).

**Run input** — `mode` `stored` | `generate` | `rag` (default `stored`); `model` (required unless `stored`); `system`; `template` (must contain `{question}`); `temperature` 0–2; `max_tokens` 1–4096 (default 256); `seed`; `threshold` 0–1; `retrieval` `bm25` | `vector` | `hybrid`; `top_k` 1–10 (default 4); `prompt_id`; `judge_model` (optional, adds a real model request per response).

**Baseline / gate input** — `baseline_id`, `min_score` (default 0.8), `max_score_drop` (default 0.05), `max_latency_increase` (default 0.5), `max_errors` (default 0). The gate is an extra requirement beside the run's own threshold. Comparison requires matching frozen cases and the same run mode.

**Experiment input** — `name`, `dataset_id`, `configurations`: 2–5 run configurations.

Interactive batches are synchronous and bounded at 50 cases.

## Knowledge base — `api/knowledge.py`

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/documents` | List / upload (multipart; PDF, TXT, Markdown) |
| GET | `/documents/{document_id}/chunks` | Inspect stored chunks |
| POST | `/documents/{document_id}/index` | Create embeddings for an unindexed document |
| DELETE | `/documents/{document_id}` | Delete document and chunks |
| POST | `/knowledge/search` | Retrieval only |
| POST | `/knowledge/ask` | Retrieval plus cited generation |

**Search input** — `question` (1–4000), `strategy` `bm25` | `vector` | `hybrid` (default hybrid), `top_k` 1–10, `document_ids` (≤50 to scope), `rerank` (CrossEncoder over candidates; first use downloads a local model).

**Ask input** — search fields plus `model`, `temperature` (default 0.1), `max_tokens` (default 512). The response maps citation numbers back to chunks and reports invalid citation numbers. A citation is a pointer, not proof of grounding.

PDFs must contain extractable text (no OCR). TXT/Markdown must be UTF-8. Identical file bytes reuse the existing document. Keyword retrieval is bounded at 10,000 chunks.

## Judging, human review, agents, security, marketing — `api/reviews.py`

| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/judge/reviews` | List / create a judgment |
| PUT | `/judge/reviews/{review_id}/human` | Record the human consensus rating |
| GET | `/judge/reliability` | Agreement, Cohen's kappa, score error, false passes/fails |
| GET | `/human-reviews` | Stored human labels |
| GET/POST | `/agents/runs` | List / execute a bounded agent task |
| GET | `/security/cases` | The six local adversarial cases |
| GET/POST | `/security/runs` | List / execute the pack against a model |
| GET/POST | `/marketing/reviews` | List / run policy checks |
| PUT | `/marketing/reviews/{review_id}/decision` | Record approval or rejection |

**Judge input** — `model`, `question`, optional `expected`, `response`, `contexts` (≤20), `rubric`, `threshold` (default 0.7), `engine` `local_judge` | `ragas`.

The local judge scores correctness, relevance, faithfulness, completeness, clarity, each `{score, explanation}`, plus `unsupported_claims`. Unsupported claims force a fail. Invalid JSON or an inference failure is stored as an unscored review with its error. Faithfulness is unavailable without reference context. RAGAS requires question, answer, contexts and reference; non-finite results stay unscored.

**Human input** — `reviewer` (1–100), `passed`, `score` 0–1, `feedback`. One current rating per judge review. Kappa is unavailable when chance-adjusted agreement is undefined.

**Agent input** — `task`, `model`, `expected_tools` (from `calculator`, `knowledge_search`, `customer_lookup`), `expected_arguments`, `checks`, `max_steps` 1–5 (default 4). Customer lookup accepts only `demo-001` / `demo-002`.

**Marketing input** — `content`, `brand_keywords`, `product_facts`, `forbidden_claims`, `audience_keywords`, `allowed_discounts`, `require_json`. Every percentage mention is treated conservatively as a possible discount. **Decision input** — `decision` `approved` | `rejected`, `reviewer`, `feedback`.

## Failure intake — `api/failures.py`

| Method | Path | Purpose |
|---|---|---|
| POST | `/webhooks/ai-failure` | Authenticated ingestion (separate secret) |
| GET | `/failures` | Inbox |
| POST | `/failures/{failure_id}/approve` | Approve into a dataset as a case |

```http
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

| Status | Meaning |
|---|---|
| 200/201 | Stored, or the original event returned for an identical replay |
| 409 | Same `event_id` reused with different content |
| 503 | `WEBHOOK_SECRET` is blank |

Approval takes `dataset_id`, `checks` (1–30), optional `expected`, and is idempotent.

## Monitoring — `api/monitoring.py`

`GET /monitoring` returns error rate, nearest-rank P95 latency, reported token usage and provider fees over the latest 1,000 request records. Energy and hardware cost are not estimated.

## Scripted access

```sh
API_KEY=<key> python3 scripts/run-dataset.py <dataset-id> --mode generate --model qwen2.5:0.5b
```

Exits nonzero when the quality gate fails, which is what makes it usable as a release job.
