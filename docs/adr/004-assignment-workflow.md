# Assignment procurement policy

The user authorized extending AURA to satisfy a vendor/purchasing interview assignment and asked to prioritize this work while completing remaining phases at $0.

The Purchasing surface uses mandatory L1 then finance approval. Its normalized, human-confirmed PO, invoice and goods receipt are versioned together. Confirmed item identifiers and exact prices are matched deterministically. A case currently holds one invoice per PO. Document edits invalidate approvals. Case creators/uploaders/reviewers must be distinct as enforced by the API.

The original Invoices agent demonstration retains its risk-selected auto/approver/controller policy. Its mock posting/scheduling is separate from Purchasing's explicit paid confirmation. This prevents the original clean auto-post scenario from silently bypassing the assignment's required review stages.

Vendor identities are assigned by a workspace administrator to existing accounts. Vendor scope is checked on list/detail/file/copilot access. Vendor accounts cannot use older workspace-wide invoice, knowledge or key-management endpoints. Assignment roles are re-read rather than trusting an older, broader JWT; revoked registered memberships are rejected.

Payment is simulated. Recording it creates an email outbox event transactionally. The user's explicit real-email requirement supersedes the original draft-only non-goal. Gmail is an optional free sender adapter, off until configured. Recipient allowlisting bounds the public demo. Preview, failed, uncertain and provider-accepted outcomes are distinct. No guarantee of exactly-once inbox delivery is claimed.

No new runtime dependencies or paid services were added. The focused copilot uses bounded read-only evidence and the existing model router/RAG. Graph synchronization, long-term memory, advanced external-agent integrations and training remain separate later work.
