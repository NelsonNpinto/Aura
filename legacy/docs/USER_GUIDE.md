# AURA concepts and workflows

## A response is not a score

A model request produces a response. A trace records its model, prompt, parameters, timing, tokens when available, and any error. An evaluation asks a separate question: does this output meet a defined condition?

AURA uses two measurement types:

- **Deterministic checks:** reproducible rules such as “the response is JSON” or “the answer contains 30 days.” These are useful release contracts and are not factual truth detectors.
- **Model estimates:** an LLM interprets a rubric or RAGAS evaluation prompt. They can assess relevance and support, but can be wrong even with perfectly valid JSON. Human calibration is a separate workflow.

Missing measurements remain unavailable. A local judge's average only uses measured dimensions. Faithfulness is unavailable without reference context.

## Prompt versions and comparisons

Save a named prompt in Playground or Prompt Library. The backend creates the next version; it never edits an old version in place. Library comparison shows instruction differences. Experiments compare their behavior on the same dataset. Saved run configuration includes the effective template/system instructions, prompt version ID, model, temperature, token limit, seed, and retrieval options.

Ollama seeds make runs more reproducible, but different model/runtime/hardware versions can still produce differences. AURA records a model tag, not a guarantee that a tag's contents cannot change. Record model digests from Ollama for strict external reproducibility.

## Knowledge Base

PDFs must contain extractable text; OCR is not included. TXT/Markdown must be UTF-8. Extraction normalizes whitespace, then LangChain's recursive splitter creates overlapping chunks. Duplicate file bytes reuse the existing document.

Uploading with embeddings uses Sentence Transformers `all-MiniLM-L6-v2` on CPU and stores 384-dimensional vectors in pgvector. Uploading without embeddings supports BM25 immediately; index the document later for vector/hybrid search. The configured embedding model must emit 384-dimensional vectors. Do not change models in an existing indexed workspace without reindexing all documents.

BM25 ranks keyword overlap. Vector retrieval ranks cosine similarity in PostgreSQL. Hybrid retrieval combines ranks with reciprocal rank fusion. Optional CrossEncoder reranking rescans the retrieved candidates; the first use downloads that local model. Rank scores are ranking values, not correctness probabilities. Keyword retrieval is limited to 10,000 chunks in this local edition.

Cited generation stores the retrieved chunks/configuration in the trace and maps numeric citations back to sources. AURA reports invalid citation numbers. A citation does not prove that a statement follows from its source: inspect the text and use faithfulness evaluation.

## Evaluation datasets and baselines

A case contains a question, optional expected answer, optional stored response, reference contexts, and explicit pass conditions. Choose stored mode to evaluate supplied outputs without inference, generate mode for fresh model output, or RAG mode for generation using your knowledge base.

A run retains the original case snapshot and individual results. A baseline belongs to the same dataset and must be error-free. Changed questions/answers/contexts/rules invalidate comparison with the old snapshot. A different execution mode also invalidates baseline comparison. Parameters intentionally differ in experiments, but the measured task remains the same.

The gate checks minimum score, maximum absolute score drop, maximum relative latency increase, and error count. It is an additional requirement alongside the run's own threshold. The dataset score is an equal-weight average of per-case rule scores. Optional judging records separate quality, faithfulness, and relevance estimates; they do not silently replace deterministic gate scores.

## Judge reliability

The local rubric judge evaluates correctness, relevance, faithfulness, completeness, and clarity. Unsupported claims force a fail even if the average score clears the threshold. Invalid judge JSON or inference failure is stored as an invalid/unscored review.

The RAGAS adapter uses local Ollama and local embeddings, with reference-based context precision/recall. Those metrics require a question, answer, contexts, and reference. Non-finite or failed metrics are never turned into a passing score.

A human records a separate score, pass/fail decision, explanation, and reviewer/consensus name. Each judge review has one current consensus rating. Agreement and Cohen's kappa compare binary decisions on paired valid reviews. Kappa is unavailable when the distributions make chance-adjusted agreement undefined. False passes are judge passes that a human failed; false fails are the reverse. Neither a small sample nor matching scores proves general reliability. Collect representative, independently labeled cases under consistent rubrics.

## Agent evaluation

The LangGraph agent chooses a tool, receives its result, and can continue until it finishes or exhausts its tool budget. Calculator expressions are parsed as a restricted arithmetic AST, not executed as Python. Knowledge search uses your documents. Customer lookup is synthetic and only accepts demo-001/demo-002.

Supply expected tool order and argument objects to check selection and arguments. Extra repeated/mismatched calls are counted. Exact-answer checks enable an objective task-condition result. Without those reference conditions, semantic task completion stays unmeasured. Multi-step success uses the expected multi-tool sequence plus output checks; inspect the trace for meaning beyond that contract.

## Security and marketing

The injection pack covers instruction overrides, secret disclosure, malicious retrieved instructions, claims of unauthorized tool use, format bypass, and prompt extraction. Its markers are synthetic test strings. The unauthorized-tool case checks output claims; it does not connect a real sensitive tool. The separate agent runner enforces an actual allowlist.

Marketing rules check explicit supplied brand/product/audience terms, banned claims, JSON output, and percentage discounts. Every percentage mention is conservatively treated as a possible discount. Semantic brand suitability and unknown unsupported claims require a person or a separately calibrated judge. Failed checks must be resolved before an approval decision. Approval records who reviewed the content and their feedback.

## Monitoring

AURA stores request traces locally even when export is disabled. Retrieval, generation, judge, and tool planning use operation spans. OpenTelemetry can export to a local collector; Langfuse can receive self-hosted observations. Monitoring shows the latest 1,000 requests, error rates and P95 latency, actual reported tokens, and local provider API fees. No energy/hardware cost estimate is fabricated.
