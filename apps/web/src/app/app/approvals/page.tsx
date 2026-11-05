"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorNote, Skeleton, Textarea } from "@/components/ui";
import { api, money, streamEvents } from "@/lib/api";
import { PERSONAS, usePersona } from "@/lib/persona";

type Approval = {
  run_id: string; step: number; required_role: string; packet_hash: string; due_at: string; created_at: string; started_by: string;
  vendor_name: string | null; invoice_number: string | null; total_minor: number | null; currency: string | null; risk_level: string | null;
  role_ok: boolean; is_preparer: boolean; packet: { flags: string[]; bank_last4: string | null; match: string[] };
};
type Check = { allowed: boolean; violations: { code: string; message: string }[]; required_role: string };

export default function ApprovalsPage() {
  const [persona] = usePersona();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["approvals", persona], queryFn: () => api<{ approvals: Approval[]; actor: { name: string } }>("/approvals") });
  const [sel, setSel] = useState(0);
  const items = q.data?.approvals ?? [];
  const me = PERSONAS.find((p) => p.key === persona);

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "TEXTAREA") return;
      if (e.key === "j") setSel((s) => Math.min(s + 1, items.length - 1));
      if (e.key === "k") setSel((s) => Math.max(s - 1, 0));
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [items.length]);

  return (
    <div className="w-full space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Approvals</h1>
        <p className="mt-1 text-sm text-muted">
          Acting as <strong>{me?.name} ({me?.role})</strong>. Switch persona in the sidebar. The server re-checks segregation
          of duties, role and limits on every decision. Shortcuts: <kbd>j</kbd>/<kbd>k</kbd> move, <kbd>a</kbd> approve, <kbd>r</kbd> reject.
        </p>
      </div>
      <ErrorNote error={q.error} />
      {q.isLoading && <Skeleton className="h-40" />}
      {!q.isLoading && items.length === 0 && (
        <Card className="text-sm text-muted">Nothing waiting. Run demo invoice C (bank change) or E (scan) from <Link className="text-accent underline" href="/app/inbox">Invoices</Link>.</Card>
      )}
      <div className="space-y-3">
        {items.map((a, i) => (
          <ApprovalCard key={`${a.run_id}-${a.step}-${persona}`} a={a} selected={i === sel} onSelect={() => setSel(i)}
            onDone={() => qc.invalidateQueries({ queryKey: ["approvals"] })} />
        ))}
      </div>
    </div>
  );
}

function ApprovalCard({ a, selected, onSelect, onDone }: { a: Approval; selected: boolean; onSelect: () => void; onDone: () => void }) {
  const [persona] = usePersona();
  const check = useQuery({ queryKey: ["check", a.run_id, persona], queryFn: () => api<Check>(`/runs/${a.run_id}/approval-check`) });
  const [comment, setComment] = useState("");
  const [callback, setCallback] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<string | null>(null);
  const bank = a.packet.flags.includes("BANK_ACCOUNT_MISMATCH");
  const allowed = check.data?.allowed ?? false;

  async function act(decision: "approve" | "reject" | "request_info") {
    setBusy(true); setError(null);
    let outcome = "";
    try {
      await streamEvents(`/runs/${a.run_id}/resume`, { method: "POST", body: JSON.stringify({ decision, comment, callback_verified: callback, packet_hash: a.packet_hash }) },
        (type, data) => { if (type === "run.completed") outcome = String((data as { payload: { outcome: string } }).payload.outcome); });
      setResult(outcome || decision);
      setTimeout(onDone, 1500);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  useEffect(() => {
    if (!selected) return;
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "TEXTAREA" || busy || !allowed) return;
      if (e.key === "a") act("approve");
      if (e.key === "r") act("reject");
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  return (
    <Card onClick={onSelect} className={clsx("space-y-3", selected && "ring-2 ring-accent/50")}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium">{a.vendor_name ?? "Unknown vendor"}</span>
        <span className="text-sm text-muted">#{a.invoice_number}</span>
        <Badge tone={a.required_role === "controller" ? "danger" : "warn"}>needs {a.required_role}</Badge>
        {a.packet.flags.map((f) => <Badge key={f} tone="danger">{f}</Badge>)}
        <span className="ml-auto text-lg tabular-nums">{money(a.total_minor, a.currency)}</span>
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-muted">
        <span>Submitted by {a.started_by.replace("persona:", "")}</span>
        <span>Due {new Date(a.due_at).toLocaleString()}</span>
        {a.packet.bank_last4 && <span>Bank on invoice ··{a.packet.bank_last4}</span>}
        <Link className="text-accent underline" href={`/app/invoices/${a.run_id}`}>Evidence →</Link>
      </div>
      {check.data && !allowed && (
        <div className="rounded-md border border-danger/40 p-2 text-sm text-danger" role="note">
          You can&apos;t approve this: {check.data.violations.map((v) => v.message).join("; ") || "not pending"}.
        </div>
      )}
      {result ? (
        <p className="text-sm text-ok">Decision recorded. Outcome: {result}.</p>
      ) : (
        <>
          <Textarea placeholder="Comment (required for flagged invoices, rejections and requests)" value={comment}
            onChange={(e) => setComment(e.target.value)} rows={2} aria-label="Decision comment" />
          {bank && (
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" checked={callback} onChange={(e) => setCallback(e.target.checked)} className="mt-1" />
              I called the vendor on a phone number already on file and confirmed the new bank details.
            </label>
          )}
          <ErrorNote error={error} />
          <div className="flex flex-wrap gap-2">
            <Button disabled={!allowed || busy} onClick={() => act("approve")}>{busy ? "Working…" : "Approve"}</Button>
            <Button disabled={!allowed || busy} onClick={() => act("reject")} className="bg-danger hover:bg-danger/90">Reject</Button>
            <Button disabled={!allowed || busy} onClick={() => act("request_info")} className="border border-border bg-surface-2 text-text hover:bg-surface">Request info</Button>
          </div>
        </>
      )}
    </Card>
  );
}
