# ADR-007: Trust layer — guardrails, evals and honest measurement

- **Status:** accepted
- **Date:** 2026-11-17

## Decision

### One screen for every untrusted-text surface

`app/guardrails/screen.py` holds the instruction heuristics, invisible-character detection, the
Prompt Guard chunking strategy, the PII inventory and the output validators. Invoice intake, the
copilot, the challenge page and the red-team runner all call it, so a control added in one place
applies everywhere. Every verdict is written to `ai.guardrail_events` and is visible in the UI.

The heuristics are the **deterministic floor**: they run with no quota and no provider. The
classifier is an addition, and a classifier failure is recorded but never blocks on its own.

### Gates compare like with like

A regression gate that silently compares different datasets is worse than no gate. A comparison
is valid only when the baseline and the candidate share the same **case snapshot** and the same
**run mode**; otherwise the result is `invalid_comparison` and the gate fails. Two gates are
hard and are never relaxed by thresholds: zero false auto-posts on non-auto cases, and
human-in-the-loop triggered wherever a case requires it.

Moving a baseline requires a written justification, stored with it.

### Determinism in CI without pretending

Three tiers, each honest about what it measures:

| Tier | What runs | What it proves |
|---|---|---|
| PR | fake provider + cassettes, fixture gates, promptfoo | orchestration, routing, guardrails — not model accuracy |
| Nightly | a rotating live slice, throttled | the live path still works and has not regressed |
| Weekly | full golden set, policy QA, trajectories, red team | the numbers published on `/eval-report` |

Cassettes (`app/llm/cassettes.py`) record a provider response once and replay it by a key that
includes the prompt text. Editing a prompt invalidates its cassettes, which is the point: the
recorded answer no longer corresponds to the request. In `replay` mode a missing cassette fails
loudly instead of falling through to the network.

### Unmeasured means unmeasured

Public figures are built from stored `ai.dataset_runs` rows only. A metric with no run behind it
is `null` and renders as "not measured". The judge stores an invalid or failed judgment
**unscored with its error** rather than substituting a number, kappa reads "undefined" when
chance agreement is 1, and no synthetic human labels are ever created.

### Misses become tests

The challenge page runs attacks against a sandbox tenant with no write tools. An attempt that
gets through is filed to the feedback inbox, where triage turns it into a regression case. The
same inbox receives the authenticated webhook (`POST /api/v1/webhooks/ai-failure`), which is
idempotent by `event_id`: the same payload returns the original event, a different payload is a
409.

## Alternatives considered

- **A hosted eval platform.** Costs money beyond a trial, and the point here is that the gates
  are part of the product, not an external dashboard.
- **LLM-judge-only scoring.** Cheap to write, impossible to trust without calibration. The
  deterministic checks carry the gates; the judge adds explanation quality on top, and its
  agreement with human labels is itself measured.
- **Blocking the PR tier on live models.** Flaky and quota-bound. Cassettes plus the fake
  provider give determinism, and the nightly tier covers the live path.

## Consequences

- Cassettes must be re-recorded when prompts change — a deliberate cost.
- The public report can look sparse early on. That is accurate: the alternative is a confident
  number nobody measured.
- Guardrail false positives are measured on benign controls in the same run as the block rate,
  so the block rate cannot be read in isolation.
