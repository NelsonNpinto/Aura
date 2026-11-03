# Implemented build stages

The original project was built in successive vertical slices:

1. **Foundation:** React UI, FastAPI, PostgreSQL/pgvector, migrations, Docker, actual dashboard data, generation, deterministic checks, saved traces.
2. **Prompt and dataset workflows:** immutable prompt versions, comparison, dataset/case authoring, stored/fresh/RAG runs, case snapshots, baselines and configurable quality gates.
3. **Knowledge Base:** extraction, chunking, local embeddings, vector/BM25/hybrid retrieval, optional reranking, citation inspection and deletion.
4. **Judging:** local rubric judge, Pydantic output validation, unsupported-claim findings, and a local RAGAS adapter.
5. **Human calibration:** human consensus labels, observed agreement, Cohen's kappa, score error, false-pass/fail analysis. No synthetic human labels are seeded into the running workspace.
6. **Experiments:** model/prompt/temperature/retrieval variants, preserved configuration, deterministic and optional judge metrics, token counts and latency.
7. **Agents:** bounded LangGraph tool workflow, arithmetic sandbox, KB search, explicit mock lookup, tool/argument/output evaluation and traces.
8. **Failure intake:** separate webhook authentication, idempotency/conflict handling, inspection and approval into regression datasets.
9. **Observability:** local traces, monitoring signals, OpenTelemetry collector, self-hosted Langfuse v4 and verified observation ingestion.
10. **Specialized packs:** promptfoo and built-in adversarial tests, marketing policy checks, and human approval decisions.
11. **Delivery:** CI tests/lint/builds, migration round-trip checks, deterministic and real-model release gates, local Terraform example, secrets setup, operating guide, and external-drive build helper.

The application now has functional pages/APIs for all original modules. See VALIDATION.md for which paths were exercised and the limits of that evidence.

## Extensions beyond this local portfolio implementation

- Multi-user identities, project-level authorization, and signed/audited reviewer accounts.
- Durable queued jobs, resumable large evaluations, cancellation, and scheduled monitoring.
- Larger representative evaluation datasets and independently collected human labels.
- More attack strategies and tool-enabled security evaluations; passing a finite suite is not a security guarantee.
- Expanded document scale, OCR, incremental reindexing, and a vector ANN index tuned from representative retrieval data.
- Hardened public deployment, managed secrets, tested restores and operational ownership.

These are explicit extensions, not claims about existing production readiness.
