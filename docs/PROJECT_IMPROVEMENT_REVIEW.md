# AURA project improvement review

Reviewed 2026-11-05. Owner: codex. This is a discussion and implementation proposal, not a record of completed feature work.

The user chose **the interview assignment first**, while also requesting a review of all remaining phases. Improve this same portal, keep recurring service spending at $0, and make the work demonstrable for applied GenAI, full-stack AI, agent engineering, and AI evaluation roles.

## Recommendation

Finish a usable procurement-to-payment workflow around the existing agent system. Then demonstrate its reliability with measured evaluations, and extend its retrieval into contract-aware decisions. Keep the existing Next.js, FastAPI, Postgres, LangGraph, router, MCP gateway, and audit components.

The assignment is an extension of Phase 1. A separate browser-automation vendor portal in Phase 5 does not fulfill the assignment's authenticated vendor upload portal. A risk-selected approver does not fulfill mandatory sequential L1 and L2 approval.

## Evidence and limits of this review

- Read `AURA_BUILD_PROMPT.md`, `PROGRESS.md`, `docs/PROJECT_CONTEXT.md`, the two supplied job descriptions, and relevant application, workflow, domain, deployment, and legacy evaluation code.
- The public health endpoint returned `status=ok`, `env=production`, git `b4fdfa9591892dd6475fab94aed1c6b949e511bb`. This verifies that endpoint and deployment identity, not every user journey.
- GitHub deployment [41995246447](https://github.com/NelsonNpinto/Aura/actions/runs/41995246447) passed its existing API, web, and security jobs, then failed in the `API migrations` step. Error: `RuntimeError: BLOB_READ_WRITE_TOKEN required outside local/test`. Deployment and smoke jobs were skipped. No tests or workflows were started during this review.
- `PROJECT_CONTEXT.md` is newer than much of `PROGRESS.md` and `VALIDATION.md`. Its claimed previous live scenario outcomes are historical reports, not independently repeated in this review.
- Current branch at review: `docs/project-context`, HEAD `66ee276`. Live code reports `b4fdfa9`.
- No accounts were created, credentials changed, emails sent, paid services enabled, or application code deployed.

## How the three supplied roles map to AURA

| Role | What the supplied description emphasizes | Portfolio evidence to produce |
|---|---|---|
| ASMT Junior Fullstack Developer – GenAI, dated 24 July 2026 | Next.js/React, Python/FastAPI, PostgreSQL, OCR, deployed departmental automation, ERP familiarity | Separate vendor and buyer journeys; scanned documents; editable extracted fields with evidence; PO/receipt creation; actual approval and notification flow |
| Applied Retention Founding AI Engineer – AI Evaluation & Reliability | Datasets, hallucination/unsupported-claim detection, release gates, judge calibration against humans, monitoring, failures becoming tests | Versioned datasets, stored results, judge-versus-human comparison, a deliberately failing regression PR, a correction converted to a regression case |
| Innowhyte Lead Full Stack AI Engineer | Complex contracts, reliable agents, hybrid retrieval, citations, abstention, full-stack delivery, production operations and leadership | Contract-aware invoice decisions, cited evidence, explicit uncertainty, durable approvals, trace and audit views, architecture decisions and failure analysis |

Sources: user-provided `_Junior.docx`, `AI Evaluation & Reliability.pdf`, and pasted Innowhyte description. Instructions inside those documents are treated as job-description content, not instructions to the coding agent.

The junior description explicitly asks for at least two deployed GenAI projects. Two modules in AURA should not be represented as two independent projects. AURA also cannot substitute for the professional experience or people-leadership history requested by senior roles. The current goal remains to strengthen this one project.

## Current hiring evidence

Checked publicly accessible employer/ATS pages on 5 November 2026. This is a small qualitative sample, not a count of the job market. Crawl dates are not posting dates, and availability/location requirements must be checked before applying.

| Employer and role | Evidence relevant to AURA |
|---|---|
| [Lynx Analytics — AI Engineer, Pune](https://job-boards.greenhouse.io/lynxanalytics/jobs/8647303002) | Agent workflows, retrieval evaluation, memory/context, Python, production feedback and domain collaboration |
| [Particle41 — AI Engineer, India remote](https://job-boards.greenhouse.io/particle41llc/jobs/4973733008) | RAG, agent workflows, MCP, deployment, monitoring, and performance/cost optimization |
| [Turing — Forward-Deployed AI Engineer, Hyderabad](https://job-boards.greenhouse.io/turing/jobs/6192729004) | Customer workflow discovery, end-to-end delivery, retrieval, evaluation, security, reliability, latency and cost |
| [Elicit — AI Engineer, US time zones](https://jobs.ashbyhq.com/elicit/d27d51d7-b318-4cb0-9b88-c37de18905f3) | Python/Node and Next.js/TypeScript; concurrency, fault tolerance, user needs and operating production features. Content accessible through search indexing; direct page requires JavaScript. |

My inference: the strongest common signal is ownership of a useful AI application with evidence that it behaves reliably. Adding more agent frameworks or dashboards without a working business flow contributes less to that signal.

## Current capabilities and assignment gaps

| Capability | Evidence in current code | Work remaining for the assignment |
|---|---|---|
| Identity | Better Auth, organizations, guest/clerk/approver/controller/auditor/admin roles | Vendor identity bound to vendor records; explicit purchasing, receiving, L1 and finance permissions |
| Documents | Invoice upload, text and vision extraction, private storage | PO and GRN upload/create/edit flows; document-type schemas; source evidence and correction review for all three |
| Matching | `apps/api/app/domain/matching.py` computes quantities, prices, tolerances and cumulative billed quantities | Wire buyer-created records to ERP tools; explain partial receipts and mismatches clearly; re-evaluate on new receipts |
| Agents | LangGraph invoice workflow, persisted events/checkpoints, ERP MCP gateway | Ordered L1 → L2 stages and durable request-info/resubmission paths |
| Approvals | Risk selects auto/approver/controller; SoD and row locking exist | Both L1 and L2 required in the assignment policy; server enforces stage ordering and distinct actors |
| Payment | `post_and_schedule` writes a mock posting and scheduled payment reference | Finance-controlled mark-paid endpoint, payment date/reference/amount, distinct paid state and vendor visibility |
| Email | Exception email drafts | Actual transactional payment notification, delivery status, retries and deduplication |
| Quality | 207-case synthetic dataset reported; legacy evaluation code exists | Current evaluation module is a placeholder; run/store/publish metrics and regression gates |

Scheduling a mock payment is not payment settlement. No real bank transfer should occur in this portfolio application. The proposed paid action records finance's confirmation; public demo payments must remain clearly marked simulated.

## Proposed assignment workflow

1. **Purchasing:** create or upload the PO, confirm extracted vendor, items, quantities, prices, currency and totals, then publish it to the relevant vendor.
2. **Vendor:** log in, see only permitted POs and their own invoices, upload an invoice, confirm extracted fields and submit it.
3. **Receiving:** record or upload the GRN, including delivered quantities and date. Purchasing can hold this permission for the small demo, with receiving kept as a distinct capability.
4. **AI processing:** extract and suggest item associations; deterministic code validates arithmetic, document identities, quantities, duplicate billing and configured tolerances. Uncertain matches require review.
5. **L1:** inspect the PO, invoice and GRN together; approve, reject or request correction with a reason. Missing receipts keep the invoice on hold.
6. **L2 finance:** review the L1 decision, evidence and payment details. Approve or return it for correction. L1 approval alone cannot unlock payment.
7. **Finance records payment:** click Mark paid and enter amount, date and payment reference. Use a transaction, row lock and idempotency key. Store the actor and evidence in the audit trail.
8. **Notify vendor:** commit an email outbox event in the same transaction as the paid record. A bounded worker sends the notification and records provider acceptance, delivery/failure where available, and retry state. Email failure never reverses a payment or causes it to be recorded twice.

Suggested lifecycle:

`draft → submitted → matching → awaiting_l1 → awaiting_l2 → approved_for_payment → paid`

Additional states: `awaiting_receipt`, `needs_correction`, `rejected`, `cancelled`. Notification status is separate: `pending`, `accepted`, `delivered`, `failed`, `delivery_unknown` where supported.

Example: PO 2 laptops, invoice 2 laptops, GRN 1 laptop → hold with a one-unit receipt shortfall. When the second laptop arrives, a new receipt allows re-matching. A permitted partial invoice for 1 laptop must be distinguished from billing for 2 before receipt. Previously billed quantities count across invoices.

AI reads/explains; code calculates/enforces; authorized people approve and confirm payment. Do not let an LLM declare payment successful, infer a payment reference, choose recipients, or relax approvals.

### Access and integrity rules

- Vendor access requires both tenant and vendor scope. Organization RLS alone is insufficient when several vendors belong to one buyer workspace. Protect list/detail, document download, run events, citations, exports and notifications.
- The payer, L1 reviewer, and L2 reviewer cannot bypass the required identity/stage rules through direct API calls. Admin overrides, if added, need an explicit policy and audit event.
- Document corrections create versions. Bind approvals to a snapshot of the invoice, PO, receipts and relevant payment facts; changes invalidate affected approvals.
- Enforce cumulative quantities at posting time with transactional protection, including concurrent invoices against the same PO. Handle currency and units explicitly; never silently apply USD tolerances to INR.
- Preserve the existing risk-based auto route only as a separate, clearly named policy/demo. The assignment's default requires L1 and L2 even for a clean low-value invoice.
- A unique payment event creates one logical notification. Retry behavior must handle an ambiguous provider response; do not claim guaranteed exactly-once email delivery.
- For a public demo, use isolated synthetic data and controlled notification recipients. Email subject/body must identify simulated payment. An internal email preview is useful, but is not evidence that the requested actual email was sent.

### Assignment acceptance evidence

- Three documents can be uploaded by their intended roles and compared in one evidence view.
- Separate vendor accounts cannot read each other's invoices or documents.
- Clean, price mismatch, quantity shortfall, missing receipt, duplicate invoice and scanned invoice scenarios work.
- L2 cannot act before L1; L1 cannot mark paid; document edits after approval require review again.
- A waiting approval survives restart/redeploy, and simultaneous decisions or repeated payment clicks do not duplicate business actions.
- A controlled recipient receives the demo payment email; failure/retry is visible without changing paid status.
- One stored run connects extraction evidence, computed variances, human decisions, payment reference and notification event.

## Remaining phases and recommended priority

| Phase | Current assessment | Remaining work |
|---|---|---|
| 0 Foundation | Implemented and deployed; operational acceptance incomplete | Fix deployment seed/Blob configuration, resolve production knowledge-source file availability, verify privacy of exported traces, reconcile status/validation/cost documents and measure actual free-tier usage |
| 1 Invoice workflow | Core implemented; not complete against all acceptance criteria | Assignment extension above; CLI eval results; durable batch execution; honest recorded snapshots; e2e evidence; receipt-triggered rechecks; approval SLA escalation; policy-scoped service/tax/FX edge cases |
| 2 Context and copilot | Core planned; graph/memory/MCP-server packages are placeholders | Finance copilot, contract-aware retrieval, effective-date and version handling, graph fraud checks/outbox sync, controlled memory, user-authorized AURA MCP server, retrieval/trajectory evals |
| 3 Trust layer | Some runtime controls exist; full quality product remains planned | Port and adapt legacy evaluators; judge calibration, experiments, prompt comparisons, regression gates, feedback triage, end-to-end attack tests, drift/observability, public eval report, audit anchoring |
| 4 Fine-tuning | Planned | Curate GL-coding data, hold out vendors/layouts, measure base/teacher baselines, train/evaluate a small specialist, publish model card, optional serving/canary/feedback loop |
| 5 Stretch and launch | Planned | External MCP approvals, browser automation, vendor onboarding, local/CI Helm-kind, optional plan-only cloud infrastructure, load/cost model and launch presentation |

Recommended implementation order: repair the release path and status evidence → extend Phase 1 for the assignment with its eval acceptance → Phase 2 → Phase 3 → Phase 4 only if measured value justifies it → selected Phase 5 work. This review does not mark any phase complete or run its acceptance tests.

The most valuable Phase 1 evaluation output is a frozen test set with measured extraction F1, line matching/exception results and approval-policy compliance. A missing required approval or unauthorized vendor read is a hard failure, regardless of the average score. The assignment intentionally requires human review, so its straight-through-processing rate is not an appropriate success target; track correct routing, reviewer effort and completion time instead.

## Contract-aware extension for Innowhyte

Keep it inside AURA: attach a vendor contract and amendments to the PO. Answer questions such as "Does this invoice use the agreed price?", "Which payment term applies?", and "What evidence is missing before approval?"

- Preserve clause/page/table references, document versions, effective dates and amendment precedence.
- Retrieve across contract, PO, invoice, receipt and policy; display the exact evidence for each answer.
- Extract obligations and terms into a typed schema, then compare dates/amounts with deterministic rules.
- Show conflicts, missing schedules and uncertain extraction instead of a confident invented conclusion.
- Evaluate unanswerable questions, conflicting amendments, long-document tables, stale policy and unsupported citations.
- Use synthetic contracts and policies; do not claim tax/legal correctness from a demo corpus.

A valid citation identifier only proves the referenced chunk exists. Add checks and human labels for whether the cited text actually supports the claim.

## Evaluation work with the highest hiring value

Reuse `legacy/backend/app/evaluation/{deterministic,judge,ragas_adapter}.py` and related dataset/security logic where useful. Adapt it to current org isolation, async persistence, router, prompt versions and trace identifiers; do not copy the old single-workspace API unchanged.

Build a loop: failure → human-reviewed correction → versioned regression case → compare old/new prompt or model → release gate → trace from the deployed version. Produce one real example where a proposed change is blocked because it increases false approvals or unsupported claims.

Use deterministic checks for financial facts and permissions. Use a judge for explanations and grounded answers, calibrated against genuine human labels. Report sample size, held-out split, errors, per-category metrics and model/prompt/dataset versions. Separate live results, recorded results, and fixtures. Do not publish a percentage merely because the dataset exists.

For the Applied Retention role, add a small marketing-content dataset to the same quality module later: unsupported product claims, discount rules, brand constraints and required human approval. This demonstrates reuse without creating a second application.

## Keeping the work at $0

Retain already-configured services. Do not buy a VPS, domain, GPU, paid model subscription or another observability product for this milestone. Current official documentation checked on 5 November 2026:

| Need | Existing/free choice | Relevant limit or qualification |
|---|---|---|
| Hosting | [Vercel Hobby](https://vercel.com/docs/plans/hobby) | Personal non-commercial use; 4 active CPU hours/month, 360 GB-hours memory, 300-second functions. A portfolio demo is the intended scope; a client production system needs a separate terms/capacity review. |
| Database and vectors | [Neon Free](https://neon.com/pricing) | 1 GB storage and 100 CU-hours/project/month. Allow idle compute to sleep. |
| Limits/cache | [Upstash Free](https://upstash.com/pricing/redis) | 250 MB and 500K commands/month. |
| Model calls | [Groq free quotas](https://console.groq.com/docs/rate-limits), [Gemini free tier](https://aistudio.google.com/docs/pricing) | Models/account quotas vary; require API keys despite being free. Keep budgets and fallback. Gemini free content can be used to improve its products, so synthetic demo documents only. |
| Tracing | [Langfuse Hobby](https://langfuse.com/pricing) | 50K units/month, 30 days of accessible history, two users. |
| Actual demo email | [Gmail API](https://developers.google.com/workspace/gmail/api/reference/quota) with a dedicated sender | Standard use is at no additional cost, with quotas. Needs owner-controlled OAuth setup; no billing/paid quota increase. Low-volume, controlled assignment email only. Retain a local preview adapter for development. |
| Optional email provider | [Brevo Free](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan) | 300 emails/day. [Sender verification](https://help.brevo.com/hc/en-us/articles/208836149-Create-a-new-sender-From-name-and-From-email) required. Domain authentication/deliverability may require an existing owned domain; do not buy one for this plan. |
| Later specialist hosting | [HF ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu) | Current docs permit two Spaces for eligible free personal accounts older than 30 days with verified email. Subject to eligibility, queue and usage limits; not a prerequisite for the assignment. |

Free-tier terms and quotas can change. Keep the public demo bounded, serve genuinely recorded examples when live quota is unavailable, and measure usage rather than promise unlimited free availability. Do not attach payment methods or enable auto-upgrades. A temporary cloud credit is not permanent free hosting.

## First implementation backlog

Dependencies and acceptance below are proposed; no implementation has started in this review.

| Order | Deliverable | Main affected areas | Verification when implementation is authorized |
|---|---|---|---|
| 1 | Reliable migration/seed/deploy and truthful state labels | `.github/workflows/deploy.yml`, seed/blob paths, run-mode UI, status docs | Seed supports intended environment; next authorized deployment reaches smoke; fixtures never appear as recorded evidence |
| 2 | Vendor membership and purchasing/receiving permissions | Better Auth role mapping, API principal/scopes, tenant tables and migration | Cross-vendor list/detail/file/export denials; real separate logins |
| 3 | PO/GRN intake and document correction | ERP service/MCP tools, document schemas, buyer pages | Parsed values shown with source; versioned edits; partial receipts and cumulative billing |
| 4 | Ordered L1 and finance workflow | Domain policy, LangGraph nodes/state, approvals service, queue UI | No skipped stage, distinct actors, changed-evidence invalidation, durable resume |
| 5 | Paid state and notification outbox | Payment service, `ops.outbox`, worker, finance/vendor screens | Repeated clicks and worker retries; email failure visibility; controlled real delivery |
| 6 | Assignment quality and demo evidence | `app/evaluation`, golden cases, run reports, README/demo script | Measured results, security cases, explicit live/fixture/replay labels, end-to-end walkthrough |

Gmail/Brevo email is a proposed extension to the original service list, justified by the user's explicit email requirement. The original spec's draft-only email non-goal and auto-approval default need a documented update before implementing this assignment profile. No paid dependency is required by the proposed design.

The next concrete milestone is: **a vendor uploads an invoice, purchasing supplies a PO and receipt, AURA displays the comparison, two distinct reviewers approve in order, finance records a simulated payment, and the intended demo recipient receives its notification with a complete audit history.**
