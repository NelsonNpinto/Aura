"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote, Skeleton, Textarea } from "@/components/ui";
import { api, money } from "@/lib/api";

type Exc = { id: string; run_id: string; type: string; status: string; reason: string; explanation: string | null; drafted_email: string | null;
  created_at: string; vendor_name: string | null; invoice_number: string | null; total_minor: number | null; currency: string | null; run_status: string };

export default function ExceptionsPage() {
  const q = useQuery({ queryKey: ["exceptions"], queryFn: () => api<{ exceptions: Exc[] }>("/exceptions") });
  return (
    <div className="w-full space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Exceptions</h1>
        <p className="mt-1 text-sm text-muted">Invoices the agents could not post, with the computed reason, an explanation and a drafted vendor email (copy only).</p>
      </div>
      <ErrorNote error={q.error} />
      {q.isLoading && <Skeleton className="h-32" />}
      {q.data?.exceptions.length === 0 && <Card className="text-sm text-muted">No open exceptions. Demo invoices B (price variance) and D (injection) create one.</Card>}
      <div className="grid gap-3 xl:grid-cols-2">
        {q.data?.exceptions.map((e) => <ExcCard key={e.id} e={e} />)}
      </div>
    </div>
  );
}

function ExcCard({ e }: { e: Exc }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [copied, setCopied] = useState(false);
  async function resolve(resolution: "resolved" | "dismissed") {
    try {
      await api(`/exceptions/${e.id}/resolve`, { method: "POST", body: JSON.stringify({ resolution, note }) });
      qc.invalidateQueries({ queryKey: ["exceptions"] });
    } catch (err) { setError(err); }
  }
  return (
    <Card className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={e.type === "security" ? "danger" : "warn"}>{e.type.replace(/_/g, " ")}</Badge>
        <span className="font-medium">{e.vendor_name ?? "Unknown vendor"}</span>
        <span className="text-sm text-muted">#{e.invoice_number ?? "?"}</span>
        <span className="ml-auto tabular-nums">{money(e.total_minor, e.currency)}</span>
      </div>
      <p className="text-sm">{e.explanation ?? e.reason}</p>
      {e.drafted_email && (
        <details>
          <summary className="cursor-pointer text-sm text-accent">Drafted vendor email</summary>
          <pre className="mt-2 whitespace-pre-wrap rounded bg-surface-2 p-2 text-xs">{e.drafted_email}</pre>
          <Button className="mt-2" onClick={async () => { await navigator.clipboard.writeText(e.drafted_email ?? ""); setCopied(true); }}>
            {copied ? "Copied" : "Copy email"}
          </Button>
        </details>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <Textarea rows={1} placeholder="Resolution note" value={note} onChange={(ev) => setNote(ev.target.value)} className="flex-1" aria-label="Resolution note" />
        <Button disabled={note.trim().length < 3} onClick={() => resolve("resolved")}>Resolve</Button>
        <Button disabled={note.trim().length < 3} onClick={() => resolve("dismissed")} className="border border-border bg-surface-2 text-text">Dismiss</Button>
      </div>
      <ErrorNote error={error} />
      <Link href={`/app/invoices/${e.run_id}`} className="text-xs text-accent underline">Evidence and lineage →</Link>
    </Card>
  );
}
