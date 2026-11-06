import { ArrowRight, FlaskConical, Inbox, ShoppingBag } from "lucide-react";
import Link from "next/link";
import { Card, Metric } from "@/components/ui";
import { UsagePanel } from "@/components/usage-panel";
import { getViewer } from "@/lib/viewer";

export const metadata = { title: "Dashboard" };

const shortcuts = [
  {
    href: "/app/inbox",
    title: "Invoices",
    detail: "Run a sample invoice and follow its decisions.",
    icon: Inbox,
  },
  {
    href: "/app/procurement",
    title: "Purchasing",
    detail: "Track supplier documents, approvals, and payments.",
    icon: ShoppingBag,
  },
  {
    href: "/app/quality",
    title: "AI quality",
    detail: "Compare judge versions and inspect evaluation results.",
    icon: FlaskConical,
  },
];

export default async function Dashboard() {
  const viewer = await getViewer();
  const vendor = viewer?.roles.includes("vendor");
  return (
    <div className="w-full space-y-8">
      <section className="workspace-hero rounded-2xl p-5 sm:p-8">
        <p className="text-xs font-semibold tracking-wider text-blue-200 uppercase">
          {viewer?.orgName ?? "Finance workspace"}
        </p>
        <h1 className="mt-3 font-semibold">Dashboard</h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-slate-200">
          Review usage and open the tools for your finance workflow.
        </p>
        {viewer?.isGuest && (
          <Link
            href="/app/inbox"
            className="mt-5 inline-flex min-h-10 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-semibold text-accent-fg hover:bg-blue-100"
          >
            Run a demo invoice <ArrowRight size={16} aria-hidden />
          </Link>
        )}
      </section>
      <section aria-labelledby="quick-links" className="space-y-3">
        <h2 id="quick-links" className="font-semibold">
          Quick links
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          {shortcuts
            .filter(({ href }) => !vendor || href === "/app/procurement")
            .map(({ href, title, detail, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="group flex min-w-0 flex-col gap-2 rounded-xl border border-border bg-surface p-4 shadow-xs transition hover:border-accent"
              >
                <div className="flex items-center justify-between gap-3 text-accent">
                  <Icon size={20} aria-hidden />
                  <ArrowRight
                    size={16}
                    aria-hidden
                    className="text-muted group-hover:text-accent"
                  />
                </div>
                <span className="font-semibold">{title}</span>
                <span className="text-sm leading-relaxed text-muted">
                  {detail}
                </span>
              </Link>
            ))}
        </div>
      </section>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <UsagePanel />
        <Card className="space-y-4">
          <h2 className="font-semibold">Workflow metrics</h2>
          <div className="grid grid-cols-2 gap-4">
            <Metric
              label="Straight-through rate"
              value={null}
              source="ai.dataset_runs (none yet)"
            />
            <Metric
              label="Route accuracy"
              value={null}
              source="ai.dataset_runs (none yet)"
            />
            <Metric
              label="Cost per invoice"
              value={null}
              source="ai.llm_calls (no invoice runs yet)"
            />
            <Metric
              label="p95 latency"
              value={null}
              source="ap.runs (none yet)"
            />
          </div>
        </Card>
      </div>
    </div>
  );
}
