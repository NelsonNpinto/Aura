"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, Play } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { StatusChip } from "@/components/runs";
import { Badge, Button, Card, ErrorNote, Skeleton } from "@/components/ui";
import { api, money } from "@/lib/api";

type Demo = { key: string; title: string; expect: string; file: string; expected_status: string };
type Run = {
  id: string; status: string; route: string | null; mode: string; created_at: string; latency_ms: number | null;
  filename: string; demo_key: string | null; vendor_name: string | null; invoice_number: string | null;
  total_minor: number | null; currency: string | null; risk_level: string | null; started_by: string;
};

export default function InboxPage() {
  const router = useRouter();
  const demos = useQuery({ queryKey: ["demo"], queryFn: () => api<{ invoices: Demo[] }>("/demo/invoices") });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<{ runs: Run[] }>("/runs?limit=100"), refetchInterval: 5000 });

  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Invoices</h1>
        <p className="mt-1 text-sm text-muted">
          Pick a scripted demo invoice and watch the agents process it live. All documents are synthetic.
        </p>
      </div>

      <section aria-labelledby="demo-h">
        <h2 id="demo-h" className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">Demo invoices</h2>
        <ErrorNote error={demos.error} />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {demos.isLoading && Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-40" />)}
          {demos.data?.invoices.map((d) => (
            <Card key={d.key} className="flex flex-col">
              <div className="flex items-center gap-2">
                <Badge tone="accent">{d.key.toUpperCase()}</Badge>
                <span className="text-sm font-medium">{d.title}</span>
              </div>
              <p className="mt-2 flex-1 text-xs text-muted">Expected: {d.expect}</p>
              <div className="mt-3 flex items-center gap-2">
                <Button className="flex-1" onClick={() => router.push(`/app/runs/new?demo=${d.key}`)}>
                  <Play size={14} className="mr-1 inline" aria-hidden /> Run
                </Button>
                <a href={`/demo-files/${d.file}`} className="rounded p-2 text-muted hover:bg-surface-2" title="View the invoice file"
                   target="_blank" rel="noreferrer"><FileText size={16} aria-label="View file" /></a>
              </div>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="runs-h">
        <h2 id="runs-h" className="mb-3 text-sm font-medium uppercase tracking-wide text-muted">Runs</h2>
        <ErrorNote error={runs.error} />
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="border-b border-border text-left text-xs uppercase text-muted">
              <tr><th className="px-3 py-2">Started</th><th className="px-3 py-2">Vendor</th><th className="px-3 py-2">Invoice</th>
                <th className="px-3 py-2 text-right">Amount</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Risk</th>
                <th className="px-3 py-2">Mode</th><th className="px-3 py-2">By</th></tr>
            </thead>
            <tbody>
              {runs.isLoading && <tr><td colSpan={8} className="p-3"><Skeleton className="h-6" /></td></tr>}
              {runs.data?.runs.length === 0 && (
                <tr><td colSpan={8} className="p-6 text-center text-muted">No runs yet. Run a demo invoice above to start.</td></tr>
              )}
              {runs.data?.runs.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0 hover:bg-surface-2">
                  <td className="px-3 py-2 tabular-nums"><Link className="underline-offset-2 hover:underline" href={`/app/runs/${r.id}`}>{new Date(r.created_at).toLocaleString()}</Link></td>
                  <td className="px-3 py-2">{r.vendor_name ?? <span className="text-muted">{r.filename}</span>}</td>
                  <td className="px-3 py-2">{r.invoice_number ?? "—"}{r.demo_key && <Badge className="ml-2">demo {r.demo_key}</Badge>}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{money(r.total_minor, r.currency)}</td>
                  <td className="px-3 py-2"><StatusChip status={r.status} /></td>
                  <td className="px-3 py-2 text-muted">{r.risk_level ?? "—"}</td>
                  <td className="px-3 py-2">{r.mode === "live" ? <span className="text-muted">live</span> : <Badge tone="warn">{r.mode === "replay" ? "recorded run" : r.mode}</Badge>}</td>
                  <td className="px-3 py-2 text-muted">{r.started_by.replace("persona:", "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>
    </div>
  );
}
