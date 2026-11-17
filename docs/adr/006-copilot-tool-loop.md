# ADR-006: A bounded tool loop for the copilot, not a framework agent

- **Status:** accepted
- **Date:** 2026-11-17

## Context

The spec suggests LangChain 1.x `create_agent` with middleware for summarisation, PII redaction,
model/tool-call limits and human-in-the-loop. AURA already owns three things that such a
framework would otherwise own: the model router (prompts, chains, token buckets, fallbacks,
caching, telemetry), the tool gateway (schema, roles, approval tokens, rate limits, redaction,
audit), and the guardrail layer.

## Decision

The copilot is a bounded loop written in `app/agents/copilot/agent.py` over those existing
components, rather than a second agent runtime.

Each step asks the router for a structured `CopilotStep` (`tool` or `answer`). A `tool` step is
executed through the gateway with `agent="copilot"`, and its result becomes numbered evidence.
An `answer` step must cite evidence ids that resolve; if any citation does not resolve the answer
is **withheld**, not shown with a warning.

The "middleware" is explicit:

| Concern | Where |
|---|---|
| PII redaction | `redact()` on the question and on tool arguments before any provider call |
| Injection screening | `guardrails/screen.py` on input, and tool output is spotlighted as untrusted at every boundary |
| Model-call limit | `MAX_STEPS = 5` |
| Tool-call limit | `MAX_TOOL_CALLS = 6` |
| Summarisation | threads over 8 messages are compacted by `copilot_summary` |
| Human-in-the-loop | write tools return `confirmation_required` instead of acting |

The invoice-to-pay workflow stays on LangGraph: it needs durable checkpoints, interrupts and
resume-after-redeploy. The copilot needs none of that — a chat turn either completes or is
retried.

## Alternatives considered

- **`create_agent` with middleware.** Adds a dependency that duplicates the router and gateway,
  and makes "every LLM call goes through the router, every tool call through the gateway" harder
  to guarantee — the rule that keeps telemetry, budgets and audit complete.
- **LangGraph for the copilot too.** Checkpoint machinery for a stateless chat turn, plus a
  second place where tool policy could drift from the gateway.

## Consequences

- The loop is ours to maintain, including the step schema and the repair path.
- Streaming is at event granularity (steps, tool calls, evidence, final answer), not token
  granularity. Tool progress is what a finance user actually wants to see.
- Every copilot tool call appears in `ai.llm_calls`, the audit chain and the tool registry with
  no extra wiring, because it uses the same two doors as everything else.
