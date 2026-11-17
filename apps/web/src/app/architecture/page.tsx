import Link from "next/link";
import { Card } from "@/components/ui";

export const metadata = {
  title: "Architecture — AURA",
  description:
    "How AURA processes an invoice: multi-agent workflow, hybrid retrieval, a knowledge graph, guardrails and a tamper-evident audit chain, all on free tiers.",
};

const LAYERS = [
  {
    name: "Experience",
    detail:
      "Next.js app (invoice inbox, approvals, exceptions, copilot, graph explorer, quality and observability), the public demo, the challenge page and the eval report. An MCP server exposes the same services to other hosts.",
  },
  {
    name: "Agent runtime",
    detail:
      "LangGraph invoice-to-pay graph with Postgres checkpoints, human approval through interrupts, and a copilot that runs a bounded tool loop. A run survives a redeploy and resumes from its checkpoint.",
  },
  {
    name: "Context",
    detail:
      "Hybrid retrieval (pgvector + Postgres full-text, fused and reranked in-process) over the policy corpus, a Neo4j knowledge graph for relationship checks, and long-term memory written only from human-confirmed corrections.",
  },
  {
    name: "Trust",
    detail:
      "Runtime guardrails on every untrusted-text boundary, deterministic domain rules for matching and approvals, segregation of duties enforced server-side, a hash-chained audit log anchored daily, and eval-gated CI.",
  },
  {
    name: "Data and models",
    detail:
      "Neon Postgres (invoices, vectors, checkpoints, memory, audit), Upstash Redis (rate limits, budgets, token buckets), Vercel Blob (documents), and a model router over Groq, Gemini and a fine-tuned specialist on a free ZeroGPU Space.",
  },
];

const FLOW = [
  ["intake_guard", "Classifies the document, screens for hidden text and injections, inventories PII, and checks for duplicates."],
  ["extract", "Text path for digital PDFs, vision path for scans. Every field carries evidence (page + snippet)."],
  ["validate", "Line arithmetic, subtotal + tax = total, dates, currency and tax-rate sanity."],
  ["vendor_verify", "Resolves the vendor, hash-compares bank details, and runs graph relationship checks."],
  ["match", "Deterministic three-way match per line against the PO and goods receipt, with configured tolerances."],
  ["code_gl", "Assigns GL account and cost center — from the PO line where possible, otherwise the specialist model."],
  ["policy_check", "Applies the approval matrix with policy citations."],
  ["risk_route", "Deterministic score and route: auto-post, approval, or the exception queue."],
  ["human_approval", "Interrupts the graph. Segregation of duties is re-checked at decision time."],
  ["post_and_schedule", "Posts to the ERP through MCP with an idempotency key and a signed, single-use approval token."],
  ["finalize", "Writes the lineage summary, metrics and feedback hooks."],
];

const DECISIONS = [
  ["Deterministic where it matters", "Matching maths, tolerances, approval rules, segregation of duties and routing are plain unit-tested code. Models extract, explain and reason about ambiguity — they never decide a payment."],
  ["One door for models, one for tools", "Every LLM call goes through the router (token buckets, fallbacks, caching, telemetry); every tool call goes through the gateway (schema, roles, approval tokens, rate limits, redaction, audit)."],
  ["Untrusted text stays data", "Document and tool output is delimited and spotlighted at every prompt boundary, not just at intake, because extracted text re-enters later prompts."],
  ["Tamper-evident, not tamper-proof", "The audit chain is append-only and verified on demand, and each day's chain head is committed to the public repository so a full rewrite is detectable."],
  ["Honest measurement", "Public numbers come from stored runs. Unmeasured values stay null and render as \"not measured\". Synthetic data is labelled synthetic."],
];

export default function ArchitecturePage() {
  return (
    <main className="mx-auto max-w-4xl space-y-8 px-4 py-10">
      <div>
        <h1 className="text-3xl font-semibold">How AURA is built</h1>
        <p className="mt-2 text-sm text-muted">
          An accounts-payable workflow that reads an invoice, matches it against the purchase
          order and goods receipt, applies policy, routes it, and leaves a verifiable record of
          why. Everything runs on free tiers, and all data is synthetic.
        </p>
      </div>

      <section>
        <h2 className="text-xl font-semibold">Layers</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {LAYERS.map(({ name, detail }) => (
            <Card key={name}>
              <h3 className="font-semibold">{name}</h3>
              <p className="mt-1 text-sm text-muted">{detail}</p>
            </Card>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-xl font-semibold">One invoice, step by step</h2>
        <ol className="mt-3 space-y-2">
          {FLOW.map(([node, detail], i) => (
            <li key={node} className="flex gap-3 rounded-lg border border-border bg-surface p-3">
              <span className="font-mono text-xs text-muted">{String(i + 1).padStart(2, "0")}</span>
              <div>
                <code className="text-sm font-semibold">{node}</code>
                <p className="mt-0.5 text-sm text-muted">{detail}</p>
              </div>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-sm text-muted">
          Each node streams an SSE event and appends an audit event. Nothing auto-posts on error:
          a non-retryable failure routes to the exception queue with a reason.
        </p>
      </section>

      <section>
        <h2 className="text-xl font-semibold">Decisions worth knowing</h2>
        <dl className="mt-3 space-y-3">
          {DECISIONS.map(([title, detail]) => (
            <div key={title} className="rounded-lg border border-border bg-surface p-4">
              <dt className="font-semibold">{title}</dt>
              <dd className="mt-1 text-sm text-muted">{detail}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section>
        <h2 className="text-xl font-semibold">See it working</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
          <li>
            <Link className="underline" href="/demo">
              Run the demo invoices
            </Link>{" "}
            and watch the graph light up live.
          </li>
          <li>
            <Link className="underline" href="/challenge">
              Attack the guardrails
            </Link>{" "}
            on the challenge page.
          </li>
          <li>
            <Link className="underline" href="/eval-report">
              Read the measured results
            </Link>
            , with the run behind every figure.
          </li>
        </ul>
      </section>
    </main>
  );
}
