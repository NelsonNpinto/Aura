# Threat model

Scope: the AURA demo as deployed — a public Next.js app, a FastAPI service, a mock ERP behind
MCP, Neon Postgres, Upstash Redis, Neo4j AuraDB and third-party model providers. All data is
synthetic. There are no real payments, no real ERP and no customer data.

This document maps controls to the OWASP Top 10 for LLM Applications and the OWASP agentic
risks, and then states what is **not** covered.

## Assets

| Asset | Why it matters here |
|---|---|
| Invoice decisions (route, approval, posting) | The thing the agent is trusted to get right |
| Audit chain | The evidence that a decision happened the way it is described |
| Vendor bank details | The target of payment-diversion fraud |
| Tenant isolation | One database, several orgs, a public demo tenant |
| Provider quota and demo budget | A free tier is exhaustible; exhaustion is a denial of service |
| Secrets (provider keys, approval-token secret, webhook secret) | Compromise enables forged approvals or billing abuse |

## Trust boundaries

1. **Visitor → web app.** Anonymous, Turnstile-gated for the guest demo and the challenge page.
2. **Web app → API.** Better Auth JWT verified via JWKS, or a hashed API key.
3. **API → database.** RLS as role `aura_app`, `app.org_id` set per transaction.
4. **Agent → tools.** Everything through the gateway; the ERP is reached only over MCP.
5. **Agent → models.** Everything through the router; no direct provider SDK calls elsewhere.
6. **Uploaded document → prompt.** The most important boundary in the system: document text is
   attacker-controlled and is treated as data everywhere it appears.

## OWASP LLM Top 10

### LLM01 Prompt injection
*Risk.* An invoice tells the agent to approve and pay; a policy chunk or tool result carries
instructions that reach a later prompt (second-order injection).

*Controls.* Instruction-phrase heuristics and invisible-character detection (`guardrails/screen.py`);
hidden-text detection from PDF character metadata; Llama Prompt Guard 2 over overlapping chunks
so text longer than the classifier window is still covered; spotlighting of every untrusted
variable at every prompt boundary, not only at intake; a blocked document routes to exception
and never auto-posts. Decisions are made by deterministic code, so a successful injection cannot
by itself cause a payment.

*Evidence.* `evals/datasets/redteam/v1/attacks.jsonl` (50 attacks, 15 benign controls),
`aura-eval redteam`, the promptfoo pack, and the public challenge page whose misses become
regression cases.

*Residual.* A novel phrasing that passes both the heuristics and the classifier reaches
extraction. It still cannot approve a payment, but it can degrade extraction quality.

### LLM02 Sensitive information disclosure
*Controls.* PII detection and redaction before any provider call, log line or trace export;
bank numbers are stored as a hash plus last four and are never returned in full; output
validation rejects an answer containing bank-like digits that are not in verified data;
free-tier providers receive synthetic data only (their terms permit human review).

*Residual.* Images cannot be redacted, so real documents must never be uploaded to the
free-tier vision path. The upload screen says so and guest uploads are deleted after 72 hours.

### LLM03 Supply chain
*Controls.* Pinned lockfiles; dependency audit and secret scanning in CI; model ids live in
`tasks.yaml`, never in code; the bundle-size gate keeps the serving image small and torch-free.

### LLM04 Data and model poisoning
*Controls.* Long-term memory is written only from human-confirmed corrections or three
consistent observations — never from document text. Memories carry source, confidence and TTL,
are visible to users, and can be deleted. Training data for the specialist comes from the
generator plus open-weight paraphrases, is deduplicated and leakage-checked, and holds its test
split out by vendor.

*Evidence.* `tests/test_memory.py`, `ml/gl_coder/check_dataset.py`, red-team category
`memory_poisoning`.

### LLM05 Improper output handling
*Controls.* Structured outputs validated with Pydantic and repaired once before a clean failure;
citations must resolve to supplied evidence or the answer is withheld; Markdown is sanitised with
no raw HTML and no external images or auto-loading links; CSP restricts `img-src`.

*Evidence.* `safe-markdown.test.tsx` (Markdown exfiltration test), `guardrails/screen.validate_output`.

### LLM06 Excessive agency
*Controls.* The tool registry declares risk, allowed roles and allowed agents per tool. The
copilot has no write tools except `start_invoice_run`, which returns a confirmation request
instead of acting. `schedule_payment` requires a signed, single-use approval token bound to run,
step and approver. Segregation of duties is enforced server-side and re-checked at decision time.
The MCP `approve_invoice` tool asks the host to confirm, or returns a link to confirm in the app.

### LLM07 System prompt leakage
*Controls.* Prompts live in the registry, contain no secrets, and the exfiltration red-team
category probes for leakage. Leaked prompt text would not grant any capability: authorisation is
server-side.

### LLM08 Vector and embedding weaknesses
*Controls.* Chunks carry `org_id` and RLS applies to the vector store; retrieval filters by doc
type and effective date; citations map back to chunk ids and invalid ones are reported.

### LLM09 Misinformation
*Controls.* Answers are grounded in retrieved evidence and must cite it; "not in the data" is an
explicit, preferred outcome; extraction values must be found in the source text or are marked
unverified with lowered confidence; the eval report publishes measured numbers only.

### LLM10 Unbounded consumption
*Controls.* Redis token buckets per provider-model, per-user and per-org daily quotas, a global
daily budget, a reserved eval budget, request rate limits with `Retry-After`, a 12 MB body limit,
page and size limits on documents, and replay mode when the budget is exhausted. The router never
waits more than ~3 s on an empty bucket; it falls back or enqueues.

## OWASP agentic risks

| Risk | Control |
|---|---|
| Memory poisoning | Write policy above; memories visible and deletable; lineage records every memory used |
| Tool misuse | Gateway is the single enforcement point: schema, role, agent, approval token, rate limit, redaction, audit |
| Privilege compromise | Roles come from the verified JWT or a hashed API key; a revoked membership fails closed; permissions are re-checked at decision time, not at assignment |
| Cascading hallucination | Deterministic facts (match results, totals) are computed, not generated; the model only explains them |
| Agent orchestration abuse | Step and tool-call budgets; a denied tool returns a structured error that is logged and audited |
| Identity spoofing | Approval tokens are HMAC-signed, single-use and bound to run, step and approver |
| Untraceable actions | Every tool call, guardrail verdict and decision appends to the hash-chained audit log |

## Platform threats

- **Cross-tenant read.** RLS with transaction-local `app.org_id`; a test runs two orgs
  concurrently through the pooled connection and proves no leakage. Transaction-level advisory
  locks only — a session-level lock would leak across pooled requests.
- **Generated Cypher widening tenant scope.** Tenant data is reachable only through
  parameterised templates; free-form generated Cypher is confined to the synthetic demo org,
  validated, executed in a READ transaction with a timeout, and any row whose `org_id` differs
  from the caller's is dropped.
- **Webhook replay.** HMAC over `timestamp.body`, five-minute tolerance, plus `event_id`
  idempotency (same payload returns the original; different payload is a 409).
- **Spoofed client IP.** Only Vercel-provided headers are trusted for rate limiting.
- **Audit tampering.** Append-only trigger plus an app role without UPDATE/DELETE; one chain per
  org with the head row locked on append; daily anchoring of each chain head to the public repo.
- **Public endpoints used as a free LLM proxy.** Fixed prompts, structured outputs, no free-text
  echo, Turnstile and rate limits on public surfaces.

## Residual risks (accepted)

1. **Database-owner compromise.** Someone with owner access could rewrite the entire chain so it
   verifies internally. The daily anchor makes this detectable, not impossible. The log is
   **tamper-evident, not tamper-proof**.
2. **Model quality.** Extraction and GL coding are measured on synthetic data. Real-world
   accuracy is unknown and is not claimed.
3. **Mock ERP.** `post_invoice` and `schedule_payment` write to a mock. No control here has been
   validated against a real ERP's semantics.
4. **Provider-side retention.** Free tiers may retain and human-review prompts. Only synthetic
   data is sent, and EEA/Switzerland/UK visitors are routed away from Gemini's free tier.
5. **Single region, no SLA.** Everything runs in one region on free tiers that can pause or
   throttle. The app degrades visibly rather than pretending to be available.
6. **Guest demo is shared.** The demo workspace is common to all visitors and resets nightly;
   anything a visitor enters there is visible to other visitors.

## Testing

Security-relevant tests live beside the code they protect: RLS isolation, SoD enforcement,
approval-token replay, webhook idempotency, Cypher rejection, Markdown exfiltration, geo-routing,
and the red-team suite. The weekly workflow runs the full attack corpus live and opens an issue
if any attack succeeds.
