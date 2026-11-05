"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { StatusChip } from "@/components/runs";
import { Badge, Button, Card, ErrorNote, Skeleton } from "@/components/ui";
import { api, apiToken, money } from "@/lib/api";
import { getPersona } from "@/lib/persona";

type Line = { line_no: number; description: string; quantity: string; uom: string; unit_price_minor: number | null; amount_minor: number | null;
  gl_account: string | null; cost_center: string | null; gl_confidence: string | null; match_outcome: string | null };
type MatchLine = { index: number; outcome: string; po_number: string | null; po_line: number | null; invoice_unit_price_minor: number;
  po_unit_price_minor: number | null; price_diff_minor: number; price_tolerance_minor: number; invoice_qty: string; available_qty: string | null };
type Detail = {
  run: { id: string; status: string; route: string | null; document_id: string; mime: string; filename: string;
    hidden_text_findings: { page: number; reason: string; text: string }[];
    state: { match?: { lines: MatchLine[]; po?: { po_number?: string; receipts?: string[] } }; risk?: { reasons: string[] };
      policy_findings?: { topic: string; document: string; heading: string; snippet: string; chunk_id?: string }[];
      gl_coding?: { line_index: number; rationale: string; source: string }[] } };
  invoice: { vendor_name: string | null; vendor_id: string | null; invoice_number: string | null; invoice_date: string | null; due_date: string | null;
    currency: string | null; subtotal_minor: number | null; tax_minor: number | null; total_minor: number | null; po_number: string | null; bank_last4: string | null } | null;
  lines: Line[];
  flags: { code: string; severity: string; message: string; evidence: Record<string, unknown> }[];
  extraction: { path: string; confidence: Record<string, number>; data: { unverified: string[] } } | null;
};
type AuditEv = { seq: number; ts: string; actor_type: string; actor_id: string; action: string; tool: string | null; decision: string | null;
  details: { summary?: string }; hash: string; prev_hash: string };
type Audit = { events: AuditEv[]; verification: { verified: boolean; events_checked: number; first_broken: { seq: number; reason: string } | null } };

function Doc({ runId, docId, mime }: { runId: string; docId: string; mime: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let obj: string | null = null;
    (async () => {
      const t = await apiToken();
      const r = await fetch(`/api/v1/documents/${docId}/file`, { headers: { authorization: `Bearer ${t}`, "x-aura-persona": getPersona() } });
      if (r.ok) { obj = URL.createObjectURL(await r.blob()); setUrl(obj); }
    })();
    return () => { if (obj) URL.revokeObjectURL(obj); };
  }, [docId, runId]);
  if (!url) return <Skeleton className="h-[600px]" />;
  return mime === "application/pdf"
    ? <iframe src={url} title="Invoice document" className="h-[640px] w-full rounded-lg border border-border bg-white" />
    // eslint-disable-next-line @next/next/no-img-element -- private blob: URL, nothing for next/image to optimise
    : <img src={url} alt="Scanned invoice" className="w-full rounded-lg border border-border" />;
}

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const q = useQuery({ queryKey: ["run", id], queryFn: () => api<Detail>(`/runs/${id}`) });
  const audit = useQuery({ queryKey: ["audit", id], queryFn: () => api<Audit>(`/audit/runs/${id}`) });
  const d = q.data;
  if (q.isLoading) return <Skeleton className="h-96" />;
  if (!d) return <ErrorNote error={q.error} />;
  const inv = d.invoice;
  const conf = d.extraction?.confidence ?? {};
  const unverified = new Set(d.extraction?.data?.unverified ?? []);
  const fields: [string, string, string | null][] = [
    ["Vendor", "vendor_name", inv?.vendor_name ?? null], ["Invoice number", "invoice_number", inv?.invoice_number ?? null],
    ["Invoice date", "invoice_date", inv?.invoice_date ?? null], ["Due date", "due_date", inv?.due_date ?? null],
    ["PO number", "po_number", inv?.po_number ?? null], ["Currency", "currency", inv?.currency ?? null],
    ["Subtotal", "subtotal", money(inv?.subtotal_minor, inv?.currency)], ["Tax", "tax", money(inv?.tax_minor, inv?.currency)],
    ["Total", "total", money(inv?.total_minor, inv?.currency)], ["Bank account", "bank_account", inv?.bank_last4 ? `··${inv.bank_last4}` : null],
  ];
  const matchLines = d.run.state?.match?.lines ?? [];
  return (
    <div className="w-full space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">{inv?.vendor_name ?? d.run.filename}</h1>
        <StatusChip status={d.run.status} />
        {d.extraction && <Badge>{d.extraction.path} extraction</Badge>}
        <Link href={`/app/runs/${id}`} className="ml-auto text-sm text-accent underline">Replay run →</Link>
      </div>
      <div className="grid gap-5 xl:grid-cols-2">
        <div className="space-y-3">
          <Doc runId={id} docId={d.run.document_id} mime={d.run.mime} />
          {d.run.hidden_text_findings?.length > 0 && (
            <Card className="border-danger/40 text-sm">
              <div className="font-medium text-danger">Hidden text found in the document</div>
              {d.run.hidden_text_findings.map((h, i) => <p key={i} className="mt-1"><Badge tone="danger">{h.reason}</Badge> p.{h.page}: “{h.text}”</p>)}
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card className="p-0">
            <table className="w-full text-sm"><tbody>
              {fields.map(([label, key, val]) => (
                <tr key={key} className="border-b border-border last:border-0">
                  <td className="w-40 px-3 py-1.5 text-muted">{label}</td>
                  <td className="px-3 py-1.5">{val ?? "—"}</td>
                  <td className="w-40 px-3 py-1.5 text-right text-xs">
                    {unverified.has(key) ? <Badge tone="warn">not found in source</Badge> :
                      conf[key] !== undefined ? <span className={conf[key] < 0.6 ? "text-warn" : "text-muted"}>conf {conf[key].toFixed(2)}</span> : null}
                  </td>
                </tr>
              ))}
            </tbody></table>
          </Card>
          <Card className="overflow-x-auto p-0">
            <div className="px-3 pt-3 text-sm font-medium">Three-way match {d.run.state?.match?.po?.po_number && <span className="text-muted">· {d.run.state.match.po.po_number} · {(d.run.state.match.po.receipts ?? []).join(", ") || "no receipts"}</span>}</div>
            <table className="mt-2 w-full text-sm">
              <thead className="border-y border-border text-left text-xs uppercase text-muted"><tr>
                <th className="px-3 py-1.5">#</th><th className="px-3 py-1.5">Description</th><th className="px-3 py-1.5 text-right">Qty / received</th>
                <th className="px-3 py-1.5 text-right">Price / PO</th><th className="px-3 py-1.5">Outcome</th><th className="px-3 py-1.5">GL · CC</th></tr></thead>
              <tbody>
                {d.lines.map((l, i) => {
                  const m = matchLines[i];
                  const bad = m && m.outcome !== "matched";
                  return (
                    <tr key={l.line_no} className={bad ? "bg-warn/10" : ""}>
                      <td className="px-3 py-1.5">{l.line_no}</td>
                      <td className="px-3 py-1.5">{l.description}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{l.quantity} / {m?.available_qty ?? "—"}</td>
                      <td className="px-3 py-1.5 text-right tabular-nums">{money(l.unit_price_minor, inv?.currency)} / {money(m?.po_unit_price_minor, inv?.currency)}</td>
                      <td className="px-3 py-1.5"><Badge tone={bad ? "warn" : "ok"}>{(m?.outcome ?? l.match_outcome ?? "—").replace(/_/g, " ")}</Badge></td>
                      <td className="px-3 py-1.5 text-xs">{l.gl_account ?? "?"} · {l.cost_center ?? "?"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
          {d.flags.length > 0 && (
            <Card className="space-y-1.5">
              <div className="text-sm font-medium">Flags</div>
              {d.flags.map((f) => (
                <div key={f.code} className="text-sm"><Badge tone={f.severity === "HIGH" ? "danger" : f.severity === "MEDIUM" ? "warn" : "neutral"}>{f.code}</Badge> {f.message}</div>
              ))}
            </Card>
          )}
          {(d.run.state?.policy_findings ?? []).filter((p) => p.chunk_id).length > 0 && (
            <Card className="space-y-2">
              <div className="text-sm font-medium">Policy citations</div>
              {(d.run.state.policy_findings ?? []).filter((p) => p.chunk_id).map((p, i) => (
                <div key={i} className="text-sm"><span className="font-medium">[{i + 1}] {p.document}{p.heading ? ` — ${p.heading}` : ""}</span>
                  <p className="text-xs text-muted">{p.snippet}</p></div>
              ))}
            </Card>
          )}
        </div>
      </div>
      <Lineage audit={audit.data} error={audit.error} runId={id} />
    </div>
  );
}

function Lineage({ audit, error, runId }: { audit?: Audit; error: unknown; runId: string }) {
  if (error) return <ErrorNote error={error} />;
  if (!audit) return <Skeleton className="h-40" />;
  const v = audit.verification;
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(audit, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `aura-lineage-${runId}.json`;
    a.click();
  };
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">Decision lineage</h2>
        {v.verified
          ? <Badge tone="ok"><ShieldCheck size={12} className="mr-1 inline" aria-hidden />chain verified · {v.events_checked} events</Badge>
          : <Badge tone="danger"><ShieldX size={12} className="mr-1 inline" aria-hidden />broken at seq {v.first_broken?.seq}: {v.first_broken?.reason}</Badge>}
        <span className="text-xs text-muted">Tamper-evident hash chain (SHA-256), anchored daily.</span>
        <Button className="ml-auto" onClick={exportJson}>Export JSON</Button>
      </div>
      <ol className="space-y-1 border-l border-border pl-4">
        {audit.events.map((e) => (
          <li key={e.seq} className="text-sm">
            <span className="mr-2 font-mono text-xs text-muted">#{e.seq}</span>
            <Badge tone={e.actor_type === "human" ? "accent" : "neutral"}>{e.actor_type}</Badge>{" "}
            <span className="font-medium">{e.action}</span>
            {e.tool && <span className="text-muted"> · {e.tool}</span>}
            {e.decision && <span className="text-muted"> · {e.decision}</span>}
            {e.details?.summary && <span className="text-muted"> — {e.details.summary}</span>}
            <span className="ml-2 font-mono text-[10px] text-muted">{e.hash.slice(0, 12)}…</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}
