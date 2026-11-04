# Validation — 3 November 2026

## Automated checks

- **53 Pytest cases passed.** Coverage includes deterministic checks and strict JSON, validation, trace storage/errors, immutable prompt versions, dataset snapshots and baseline drift, generation failures, experiments, document extraction (including real PDF bytes), duplicate documents, vector/hybrid/scoped retrieval, judge validation, unsupported claims, absent-context faithfulness, human agreement/kappa, calculator restrictions, bounded agent completion, webhook authentication/idempotency/conflicts/approval, API access, marketing approval gates, rate limits, release-gate exit codes, and RAGAS callback usage tracing.
- Ruff lint and formatting passed for backend and operational Python scripts.
- TypeScript and Vite production builds passed.
- Frontend and promptfoo dependency audits reported zero known vulnerabilities after compatible dependency overrides. See DEPENDENCY_AUDIT.json.
- Backend/frontend Docker images built successfully. The backend runs as an unprivileged user.
- A disposable PostgreSQL/pgvector database passed Alembic upgrade, drift check, downgrade, re-upgrade, and a second drift check. The application database was preserved.
- Terraform init, formatting and validation passed using Terraform 1.13.4 in Docker. No Terraform resources were applied.
- The deterministic release gate passed. The real local-model gate passed all three configured output-contract cases; see MODEL_QUALITY_RESULT.json. Unit tests separately confirm that failing outputs produce a nonzero release-gate exit.

## Real service checks

The core frontend, API, PostgreSQL/pgvector and Ollama services are running. Optional Langfuse v4 web/worker, its PostgreSQL/ClickHouse/Redis/object storage, and the OpenTelemetry collector are running too. All configured health checks pass. Other projects' containers remain stopped; no unrelated volumes/images were deleted.

Using actual local qwen2.5:0.5b inference, HTTP smoke checks exercised generation, standalone evaluation, prompt saving, datasets, baseline comparisons, experiments, upload/indexing, chunk inspection, BM25/vector/hybrid search, cited answers, judging, agent execution, security tests, marketing reviews, authenticated webhook ingestion/duplicates, monitoring and trace detail. The calls are recorded in SMOKE_RESULTS.json; clearly named smoke records remain in the local workspace.

Additional checks after initial fixes:

- Structured local judging returned valid Pydantic output. Decoder schemas omit constraints that triggered an Ollama 0.13 grammar crash, while full response validation retains the constraints.
- A LangGraph agent called the calculator for 19*7, received 133, finished with 133, and passed its expected-tool/exact-output conditions. See AGENT_RESULT.json.
- Sentence Transformer embedding generation and actual PostgreSQL cosine-distance search worked. Optional CrossEncoder reranking also returned a valid result.
- RAGAS produced finite faithfulness, relevance, reference precision and recall estimates using Ollama/local embeddings. Its seven internal model calls were captured as local traces with usage. See RAGAS_RESULT.json.
- Experiments recorded actual token usage, latency and optional judge estimates. Without source context, faithfulness correctly remained unavailable. The stored-response baseline correctly rejected comparison with generated-response mode even when its output checks passed. See EXPERIMENT_RESULT.json.
- Langfuse's observations API returned ingested observations under the initialized local project. The OpenTelemetry collector logged received span batches.
- The promptfoo pack completed six local cases with **2 passing and 4 failing**, with zero provider errors in that run. The built-in pack also recorded genuine failures. These results demonstrate detected weaknesses in the small model, not a secure model or a complete adversarial assessment.

## Browser checks

The live Docker-backed application was inspected in the browser. Verified hybrid retrieval without a selected model, saved dataset selection/case controls, a stored-response run passing its baseline from the UI, experiment usage/judge metrics, successful/failed agent history, attack coverage/results, and the empty human-calibration state. The responsive shell was checked during implementation. Records and form errors are real API states; no dashboard sample metrics are seeded.

## Evidence limits

No automated test creates a live rating that pretends to be a genuine human review. Judge reliability therefore remains unmeasured until the user supplies labels. Human-rating and approval mechanics are tested in isolated databases.

The tiny model's scores vary and its adversarial behavior is weak. Passing output contracts does not establish factual accuracy, semantic task completion, judge reliability, marketing suitability, or security.

GitHub workflows are configured locally but have not run in a remote repository. No public deployment, account-based multi-tenancy, distributed job queue, or infrastructure apply is claimed.

## Reproduce

```sh
python3 scripts/docker-up.py --observability
python3 scripts/check-migrations.py
python3 scripts/smoke.py --ragas
python3 scripts/check-terraform.py
```

The smoke script writes clearly named integration fixtures to the workspace. Migrations are checked in a freshly created disposable database and do not downgrade the application database.
