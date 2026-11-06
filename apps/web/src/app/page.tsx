import {
  ArrowRight,
  BookOpen,
  FlaskConical,
  Inbox,
  Layers3,
  ShoppingBag,
} from "lucide-react";
import Link from "next/link";
import { Badge, Card } from "@/components/ui";

const LAYERS = [
  {
    title: "Invoice processing",
    body: "Follow a sample invoice as Aura checks its evidence and decides whether to post it, hold it, or ask for review.",
    icon: Inbox,
  },
  {
    title: "Purchasing",
    body: "Bring orders, supplier invoices, and receipts together for a two-stage review.",
    icon: ShoppingBag,
  },
  {
    title: "Finance copilot",
    body: "Ask a question about a purchasing case or a policy and inspect the evidence behind the answer.",
    icon: BookOpen,
  },
  {
    title: "AI quality",
    body: "Compare judge versions on the same evidence and see which cases would block a release.",
    icon: FlaskConical,
  },
];

export default function Landing() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 pb-12 sm:px-8">
      <nav
        aria-label="Main"
        className="flex flex-wrap items-center justify-between gap-4 py-5 sm:py-7"
      >
        <span className="flex items-center gap-2.5 font-bold tracking-wide">
          <span className="grid size-9 place-items-center rounded-lg bg-accent text-accent-fg">
            <Layers3 size={19} aria-hidden />
          </span>
          AURA
        </span>
        <div className="flex flex-wrap items-center gap-4 text-sm font-medium">
          <Link href="/login" className="hover:text-accent">
            Log in
          </Link>
          <Link href="/signup" className="hover:text-accent">
            Sign up
          </Link>
          <a
            href="https://github.com/NelsonNpinto/Aura"
            className="hover:text-accent"
          >
            GitHub
          </a>
        </div>
      </nav>
      <section className="workspace-hero rounded-2xl px-6 py-12 sm:px-12 sm:py-16 lg:px-16">
        <Badge className="border-blue-200/40 text-blue-100">
          Synthetic data · Simulated payments
        </Badge>
        <h1 className="mt-5 max-w-3xl text-4xl leading-tight font-semibold tracking-tight text-balance sm:text-6xl">
          From invoice to payment, with evidence at every step.
        </h1>
        <p className="mt-5 max-w-xl text-base leading-relaxed text-slate-200 sm:text-lg">
          Aura helps finance teams review supplier invoices, resolve
          discrepancies, and understand the decisions their AI workflow makes.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href="/demo"
            className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2.5 text-sm font-semibold text-accent-fg hover:bg-blue-100"
          >
            Try the demo <ArrowRight size={16} aria-hidden />
          </Link>
          <Link
            href="/signup"
            className="rounded-lg border border-white/30 px-4 py-2.5 text-sm font-semibold hover:bg-white/10"
          >
            Create a workspace
          </Link>
        </div>
      </section>
      <section className="mt-9 space-y-4" aria-labelledby="explore-aura">
        <h2 id="explore-aura" className="text-xl font-semibold tracking-tight">
          Explore Aura
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {LAYERS.map(({ title, body, icon: Icon }) => (
            <Card key={title}>
              <span className="grid size-9 place-items-center rounded-lg bg-accent/10 text-accent">
                <Icon size={18} aria-hidden />
              </span>
              <h3 className="mt-3 font-semibold">{title}</h3>
              <p className="mt-1 text-sm leading-relaxed text-muted">{body}</p>
            </Card>
          ))}
        </div>
      </section>
      <section className="mt-12">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">
          Live metrics
        </h2>
        <p className="mt-2 text-sm text-muted">
          Not measured yet. Metrics appear here only once stored evaluation runs
          exist.
        </p>
      </section>
    </main>
  );
}
