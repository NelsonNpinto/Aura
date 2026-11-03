# Incremental roadmap

Each milestone should end with an actual usable workflow, meaningful tests, and an explanation of the new concepts.

1. **Foundation — implemented:** Compose, PostgreSQL/pgvector, Alembic, API, UI shell, local generation, deterministic evaluations, saved traces, real dashboard, initial CI.
2. **Prompt versions and evaluation datasets:** saved prompt configurations, immutable versions, datasets/cases, repeatable batch runs, baseline selection, configurable score/latency regression gates. Extend GitHub Actions to block regressions with deterministic datasets first.
3. **Knowledge base and RAG:** PDF/TXT/Markdown extraction, cleaning/chunking, local Sentence Transformer embeddings in pgvector, BM25/hybrid retrieval, chunk inspection, deletion, and cited answers. Measure retrieval against labeled cases before adding reranking.
4. **Local AI judge and RAG scoring:** validated rubric and judge JSON, supporting evidence, correctness/relevance/completeness/clarity dimensions, appropriate RAGAS integration. Keep deterministic results distinct from judge estimates. Record model/prompt/rubric configuration.
5. **Human review and judge calibration:** human labels, paired judge results, agreement, Cohen's kappa with explicit label definitions, false passes/fails, sample size and uncertainty. Never assert reliability without labeled data.
6. **Experiments:** model, prompt, temperature, and retrieval comparison with immutable configurations, quality and latency/token history.
7. **Agents:** LangGraph agent with KB search, safe calculator, and clearly marked mock customer lookup. Record tool calls/arguments, expected tool paths, failures, unnecessary calls, and task completion.
8. **Failure intake:** authenticated webhook, idempotent event ingestion, failure inspection, human approval into datasets. Add FailureEvent and regression relationships via migration.
9. **Observability:** instrument model/retrieval/evaluation/tool operations with OpenTelemetry and optional self-hosted Langfuse. Introduce Langfuse's full service dependencies only when this module is implemented.
10. **Security and marketing packs:** promptfoo adversarial datasets, unauthorized tool/output/prompt-extraction tests, brand/product/claim/discount policy checks, and approval workflow. Passing a finite test suite does not guarantee security.
11. **Deployment practice:** authentication and project boundaries, request size/rate controls, retention, backups, container hardening, Terraform examples, release checks, and deployment instructions.

Do not pre-install every AI dependency in milestone 1. LangChain, LangGraph, Sentence Transformers, RAGAS, Langfuse, and promptfoo will be added when their features are built, with compatible pinned versions and tests. This keeps installation light and makes each addition understandable.
