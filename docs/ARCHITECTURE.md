# Architecture notes

## First vertical slice

The browser calls a same-origin `/api/v1` API through Nginx (or the Vite development proxy). FastAPI validates payloads with Pydantic. The Ollama adapter talks only to a configured server; users cannot supply arbitrary inference endpoint URLs. SQLAlchemy stores traces and evaluation runs in PostgreSQL. Alembic owns schema changes; startup does not call `create_all`.

### Trace

A UUID identifies one generation attempt. Store model, prompt, system instructions, generation options, response or error, end-to-end application latency, and actual token counts if returned. Latency includes connection/model load time and is not just token-generation time. Missing token counts remain null. Both successful and failed attempts count toward total requests; model latency comparison includes successful attempts only. Generation is synchronous from the user's perspective and has a configurable 180-second provider timeout.

### Evaluation run

A run stores the original response, all checks, configured pass threshold, per-check explanations, a score, and the final pass/fail decision. Each rule has equal weight. A threshold of 1 means all rules must pass. Keyword/phrase matching is case-insensitive substring matching; exact answer matching trims outer whitespace but remains case-sensitive. JSON checks require the entire response to be JSON. JSON Schema uses Draft 2020-12, with references deliberately disabled. A linked trace must exist and its response must match; editing the output creates an independent evaluation.

Results currently live in a JSON column within each run. A later dataset/batch-run migration will introduce cases and individual result rows, preserving existing runs. Tables for unbuilt features are added with their modules, rather than created as unused scaffolding.

### Honest reporting

No seeded dashboard data. Average check score is calculated across saved runs. Failed evaluations and request transport errors are different signals. Faithfulness, relevance, hallucination detection, and monetary cost remain unavailable. Local inference has no cloud provider token charge, but that does not mean electricity and hardware have zero cost. Human judge agreement requires paired labels and cannot be inferred from output-rule checks.

## Boundaries and next steps

This first version assumes a trusted local user. Before public deployment it needs user/project authorization, workload/request limits, durable background job handling, structured application logs, privacy/retention controls, and operational alerting. The health endpoint checks database connectivity; Ollama availability is reported separately so deterministic evaluation remains usable without models. Failure requests are captured as traces, but there is no automated retry of inference to avoid duplicated requests.

The shared database is initialized with the vector extension for milestone 3. No document or embedding table exists until its corresponding migration is introduced. API docs are available at `/docs` on the backend port.
