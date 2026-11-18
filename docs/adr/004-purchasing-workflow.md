# ADR-004: A separate purchasing workflow alongside the invoice agent

- **Status:** accepted
- **Date:** 2026-11-05

## Context

The invoice-to-pay agent routes by risk: a clean, low-value invoice auto-posts with no human in the loop. That is the right behaviour for an autonomous AP agent, but it cannot represent a purchasing process where review is mandatory regardless of risk, where an outside vendor supplies their own document, and where the people involved must be demonstrably distinct.

Bolting mandatory stages onto the risk router would have weakened the agent demonstration; adding risk-based skipping to a purchasing flow would have defeated its purpose.

## Decision

Run both, over one runtime.

**Purchasing** uses mandatory L1 approval, then finance approval. Its purchase order, vendor invoice and goods receipt are normalized, human-confirmed and versioned together as one evidence revision. Matching is deterministic on exact item identifiers and exact unit prices; a case holds one invoice per purchase order. Any document edit bumps the revision and invalidates approvals already given. Case creators, uploaders and the two reviewers must all be distinct people, enforced in the API rather than the browser.

Vendor identities are assigned by a workspace administrator to accounts that already exist. Vendor scope is re-checked on list, detail, file and copilot access, and vendor accounts cannot reach the workspace-wide invoice, knowledge or key-management endpoints. Roles are re-read at decision time rather than trusted from an older, broader JWT, and revoked memberships are rejected.

**Invoices** keeps its risk-selected auto / approver / controller policy and its own simulated posting and scheduling, kept separate from Purchasing's explicit payment confirmation so that the clean auto-post path can never bypass a mandatory review stage.

Payment is simulated. Recording it creates an email outbox event in the same transaction. Gmail is an optional free sender adapter, off until configured, with recipient allowlisting to bound the public demo. Preview, failed, uncertain and provider-accepted outcomes are tracked as distinct states; exactly-once inbox delivery is not claimed.

## Consequences

Two workflows mean two mental models for a reader, which the documentation has to make explicit up front. In exchange, each one stays honest about what it is: the agent demonstrates autonomy with guardrails, and purchasing demonstrates controls that do not depend on a model's judgement.

No new runtime dependencies and no paid services. The scoped copilot reuses the existing model router and retrieval over bounded, read-only evidence.

## Alternatives considered

- **One workflow with a configurable policy** — collapses into the risk router with mandatory stages switched on, which makes neither story clear and puts a feature flag between an auditor and the answer to "could this have been paid without review?".
- **Replace the agent workflow with purchasing** — loses the autonomous multi-step demonstration, which is the harder engineering problem of the two.

Graph synchronization, long-term memory, external agent integrations and fine-tuning remain separate later work.
