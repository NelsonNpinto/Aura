# AURA architecture

## Request path

The React/TypeScript app calls same-origin `/api/v1` endpoints through Nginx (Vite proxy during host development). FastAPI validates requests with Pydantic. Business services handle inference, deterministic evaluation, dataset execution, judging, retrieval, and agent operations. SQLAlchemy persists records in PostgreSQL; Alembic owns schema changes and enables pgvector.

Core services are frontend, backend, PostgreSQL/pgvector, and Ollama. Optional observability services are isolated Langfuse PostgreSQL, Redis, ClickHouse, MinIO, Langfuse web/worker and an OTLP collector. Published ports bind to loopback.

## Data records

- `traces`: each captured local generation attempt, prompt/system/configuration, response/error, latency and actual usage when reported. RAG traces retain selected chunks and retrieval configuration. RAGAS LangChain callbacks persist their internal local model calls as traces too.
- `prompts`: immutable name/version records with system, template and saved settings; unique(name, version). PostgreSQL advisory locks serialize version allocation.
- `evaluation_datasets`, `evaluation_cases`, `dataset_runs`, `evaluation_results`, `regression_tests`: case authoring, frozen snapshots, individual outcomes and optional judge links, observed metrics and quality-gate baselines.
- `documents`, `document_chunks`: extracted text, SHA-256 deduplication, overlapping chunks, local embedding model identifier and nullable 384-dimensional pgvector embeddings.
- `evaluation_runs`: standalone deterministic checks and explanations.
- `judge_reviews`, `human_reviews`: rubric/RAGAS estimates and separately entered human consensus decisions. Each valid review can have one current human rating.
- `experiments`: immutable configuration/result comparisons linked to datasets and individual runs.
- `agent_runs`: task, configuration, ordered tool records, linked model request IDs, final response and evaluation metrics.
- `failure_events`: authenticated incoming event, unique external event ID, status and approved case link.
- `security_test_runs`, `marketing_reviews`: attack/policy results, original inputs, settings and explicit approval decisions.

This is shared-workspace API-key access, not user account authentication; no users table or authenticated reviewer identity is claimed.

## Evidence and scoring

Deterministic checks use explicit string/JSON contracts. JSON Schema uses Draft 2020-12 with references disabled. Phrase checks are case-insensitive substrings; exact answer checks trim outer whitespace and remain case-sensitive. Whole-response JSON checks reject fenced JSON and NaN/Infinity constants.

Case scores are equal-weight fractions of rules passed. Batch score averages those case scores. Optional local judgments remain separate observed metrics. Baseline comparison requires matching frozen cases and run mode; quality, error and relative latency limits are configurable. Release CLIs propagate failures as nonzero exit codes.

The local judge validates every dimension and explanation with Pydantic. The decoder schema sent to Ollama omits large repetition/numeric constraints to avoid a runtime grammar crash in Ollama 0.13; the full application schema still enforces score/length bounds after generation. Faithfulness is unavailable without reference context. Unsupported claims force the local judge's decision to fail.

RAGAS uses local ChatOllama plus Sentence Transformer embeddings, with explicitly supplied references/contexts. Missing/non-finite results stay unscored. Judge agreement is computed only from separately saved valid paired human labels; no reliability claim is inferred from deterministic checks.

## Retrieval and agent execution

BM25 ranks overlapping terms; vector retrieval uses PostgreSQL cosine-distance ordering. Hybrid uses reciprocal rank fusion; optional CrossEncoder reranking operates over candidates. Citation numbers map back to stored chunk evidence and invalid numbers are reported. No citation-grounding guarantee is inferred from mere presence of a citation.

LangGraph iterates a validated tool plan. Tools are explicitly allowlisted. The calculator accepts only bounded arithmetic syntax, KB search uses stored documents, and customer lookup has only labeled mock IDs. A tool budget prevents unbounded calls; a final answer is allowed after the final permitted tool. Expected tool sequences/arguments and exact answer checks provide task-specific evidence; generic semantic success is not invented.

## Operations and limits

Model calls, retrieval and embedding operations produce OpenTelemetry spans. Langfuse receives local observations when configured. Full user prompt/response content is stored locally and omitted from custom telemetry spans by default. Tokens and provider fees are distinguished from unmeasured energy/hardware costs. Monitoring uses the latest 1,000 request records and a nearest-rank P95 calculation.

The API has optional shared Bearer authentication, separate webhook authentication, validation limits and an in-process per-client rate window. Webhook deduplication and approval use database constraints/locking. Interactive batch execution is synchronous and bounded; large distributed jobs and multi-tenant controls are explicit future extensions.
