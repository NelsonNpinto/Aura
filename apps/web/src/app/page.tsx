import Link from "next/link";
import { Badge, Card } from "@/components/ui";

const LAYERS = [
  ["Invoice-to-pay agents", "LangGraph workflow: intake guard, extraction, three-way match, GL coding, policy check, risk routing, human approval, posting."],
  ["Finance copilot", "Cited answers over policies, invoices, a knowledge graph and the audit trail."],
  ["Trust layer", "Runtime guardrails, eval-gated CI, tracing, segregation of duties and a hash-chained audit log."],
  ["$0 free-tier stack", "Vercel, Neon, Upstash, AuraDB Free, Langfuse Hobby, Groq and Gemini free tiers."],
];

export default function Landing() {
  return (
    <main className="mx-auto max-w-5xl px-4 py-12 sm:px-6">
      <nav className="mb-16 flex items-center justify-between">
        <span className="text-lg font-semibold tracking-tight">AURA</span>
        <div className="flex items-center gap-4 text-sm">
          <Link href="/login" className="hover:underline">Log in</Link>
          <Link href="/signup" className="hover:underline">Sign up</Link>
          <a href="https://github.com/NelsonNpinto/Aura" className="hover:underline">GitHub</a>
        </div>
      </nav>
      <Badge tone="warn">Demo on synthetic data · no real payments</Badge>
      <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">
        Auditable, Unified, Reliable Agents for accounts payable.
      </h1>
      <p className="mt-4 max-w-2xl text-lg text-muted">
        Watch AI agents process invoices end to end, see exactly why each one was paid or held, and
        inspect the evals, guardrails and audit chain that keep them honest.
      </p>
      <div className="mt-8 flex flex-wrap gap-3">
        <Link href="/demo" className="rounded-md bg-accent px-4 py-2.5 font-medium text-accent-fg hover:opacity-90">
          Try the live demo
        </Link>
        <Link href="/signup" className="rounded-md border border-border bg-surface px-4 py-2.5 font-medium hover:bg-surface-2">
          Create a workspace
        </Link>
      </div>
      <section className="mt-16 grid gap-4 sm:grid-cols-2">
        {LAYERS.map(([title, body]) => (
          <Card key={title}>
            <h2 className="font-semibold">{title}</h2>
            <p className="mt-1 text-sm text-muted">{body}</p>
          </Card>
        ))}
      </section>
      <section className="mt-12">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">Live metrics</h2>
        <p className="mt-2 text-sm text-muted">
          Not measured yet. Metrics appear here only once stored evaluation runs exist (build phase 0 of 5).
        </p>
      </section>
    </main>
  );
}
