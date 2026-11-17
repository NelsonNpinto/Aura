# ADR-005: Knowledge graph and long-term memory

- **Status:** accepted
- **Date:** 2026-11-17

## Decision

### Graph (Neo4j AuraDB Free)

Relationship questions that SQL answers badly — "do these two vendors share a bank account?",
"was this invoice split under the approval limit?" — go to a small property graph projected from
Postgres.

- **Projection, not dual writes.** The owning transaction appends to `ops.outbox`; a consumer
  (`app/graph/sync.py`) applies idempotent `MERGE`s. A paused AuraDB therefore cannot fail an
  invoice run, and nothing is lost: unprocessed rows are retried by the nightly reconcile.
- **Unavailable is a verdict, not a gap.** When the driver is missing, credentials are absent or
  the instance is paused, `vendor_verify` raises `GRAPH_UNAVAILABLE` (MEDIUM) and the invoice
  goes to human review. A graph check never reports a silent pass.
- **Backoff.** After a failure the graph is treated as unavailable for 60 s, so a paused instance
  does not add its resume time to every request.
- **Tenant isolation never depends on the model.** Tenant data is reachable only through the
  parameterised templates in `app/graph/queries.py`. Free-form generated Cypher runs only against
  the synthetic `demo` org, is validated (`app/graph/guard.py`), executes inside `execute_read`
  with a transaction timeout — so a write fails at the database even if validation misses it —
  and any returned row whose `org_id` differs from the caller's is dropped.
- **The driver is an optional import.** `neo4j` is not in the serving dependency set; the code
  degrades when it is absent. That keeps the Vercel bundle small and makes the graph genuinely
  optional for anyone running the project without an AuraDB instance.

### Memory (Postgres, not a vector service)

Long-term memory lives in `ai.memories`, namespaced `(org_id, kind, subject_id)` with
`kind ∈ {vendor, user}`, embedded with the same in-process fastembed model used for RAG.

- **Write policy.** Only a human-confirmed correction, or three consistent observations of the
  same normalised fact. **Never from document text** — that is attacker-controlled (§B11 memory
  poisoning).
- **Forgetting.** TTL (180 days by default), confidence decay after 60 days unused, hard delete
  on request, and a page where users see and delete everything the agent knows.
- **Lineage.** Every memory used in a run is recorded in `memories_used` and shown in the run's
  lineage, so a surprising decision can be traced to the note that shaped it.

## Alternatives considered

- **Postgres recursive CTEs instead of Neo4j.** Cheaper and one less service, but the fraud
  queries are genuinely path-shaped and the graph explorer is part of what this project is
  demonstrating. The degrade path means the system still works without it.
- **Writing to Neo4j inline.** Simpler, but it couples invoice processing to a service that
  pauses when idle on the free tier.
- **A managed vector store for memory.** Another service and another free tier to respect;
  pgvector is already there and memory volume is small.

## Consequences

- One more service to keep alive (a daily ping; never Neon, which must be allowed to sleep).
- Graph answers can lag Postgres by one sync cycle. The reconcile bounds the lag; the UI says
  when the projection is behind.
- Text-to-Cypher is a demo capability confined to synthetic data, not a tenant-facing feature.
