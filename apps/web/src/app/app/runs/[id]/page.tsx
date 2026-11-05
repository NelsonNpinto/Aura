"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { EventLog, Pipeline, StatusChip } from "@/components/runs";
import { Badge, Card, ErrorNote } from "@/components/ui";
import { api, money, type RunEvent, streamEvents } from "@/lib/api";

type Detail = {
  run: { id: string; status: string; route: string | null; mode: string; latency_ms: number | null; tokens: number;
         est_cost_microusd: number; document_id: string; demo_key: string | null; error: string | null;
         state: { risk?: { score: number; level: string; reasons: string[]; required_role: string | null }; policy_findings?: { topic: string; document: string; heading: string; snippet: string }[] } };
  invoice: { vendor_name: string | null; invoice_number: string | null; total_minor: number | null; currency: string | null } | null;
  flags: { code: string; severity: string; message: string }[];
  exception: { type: string; reason: string; explanation: string | null; drafted_email: string | null } | null;
  posting: { erp_ref: string; payment_ref: string | null } | null;
  approvals: { step: number; required_role: string; status: string; decision: string | null; decided_by: string | null; comment: string | null }[];
};

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const search = useSearchParams();
  const demo = search.get("demo");
  const [runId, setRunId] = useState<string | null>(id === "new" ? null : id);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [mode, setMode] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [live, setLive] = useState(true);
  const started = useRef(false);

  const detail = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api<Detail>(`/runs/${runId}`),
    enabled: Boolean(runId) && !live,
  });

  useEffect(() => {
    // Start exactly once. React dev mode mounts effects twice; aborting on that first cleanup
    // would cancel the POST that starts the run, so the stream is left to finish on its own.
    if (started.current) return;
    started.current = true;
    const ctrl = new AbortController();
    const onEvent = (type: string, data: Record<string, unknown>) => {
      if (type === "run.created") {
        setRunId(String(data.run_id));
        setMode(String(data.mode));
        window.history.replaceState(null, "", `/app/runs/${data.run_id}`);
        return;
      }
      setEvents((prev) => (prev.some((e) => e.seq === (data as RunEvent).seq) ? prev : [...prev, data as RunEvent]));
    };
    const go = id === "new" && demo
      ? streamEvents("/runs", { method: "POST", body: JSON.stringify({ demo_key: demo }) }, onEvent, ctrl.signal)
      : streamEvents(`/runs/${id}/events`, { method: "GET" }, onEvent, ctrl.signal);
    go.catch((e) => { if ((e as Error).name !== "AbortError") setError(e); }).finally(() => setLive(false));
  }, [id, demo]);

  const d = detail.data;
  const last = events[events.length - 1];
  const waiting = events.some((e) => e.type === "interrupt") && !events.some((e) => e.type === "run.completed");
  return (
    <div className="w-full space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Run</h1>
        {d && <StatusChip status={d.run.status} />}
        {live && <Badge tone="accent">live</Badge>}
        {(mode ?? d?.run.mode) === "replay" && <Badge tone="warn">recorded run · demo budget used up, no live model calls</Badge>}
        {(mode ?? d?.run.mode) === "fake" && <Badge tone="warn">fixture mode</Badge>}
        {runId && <span className="font-mono text-xs text-muted">{runId}</span>}
        {runId && !live && <Link href={`/app/invoices/${runId}`} className="ml-auto text-sm text-accent underline-offset-2 hover:underline">Invoice, evidence and lineage →</Link>}
      </div>
      <ErrorNote error={error} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <div><Pipeline events={events} /></div>
        <div className="space-y-4">
          {!live && d && <Outcome d={d} />}
          {live && !waiting && <Card className="text-sm text-muted">Processing… {last ? `last event: ${last.type}${last.node ? ` (${last.node})` : ""}` : "starting"}</Card>}
          {waiting && live && <Card className="text-sm">Paused for a human decision.</Card>}
          <div>
            <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-muted">Event log</h2>
            <EventLog events={events} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Outcome({ d }: { d: Detail }) {
  const risk = d.run.state?.risk;
  const pending = d.approvals.find((a) => a.status === "pending");
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="text-lg font-semibold">{d.invoice?.vendor_name ?? "Unknown vendor"}</span>
        <span className="text-sm text-muted">#{d.invoice?.invoice_number ?? "?"}</span>
        <span className="ml-auto text-lg tabular-nums">{money(d.invoice?.total_minor, d.invoice?.currency)}</span>
      </div>
      <div className="grid grid-cols-3 gap-3 text-sm">
        <div><div className="text-xs text-muted">Route</div>{d.run.route ?? "—"}</div>
        <div><div className="text-xs text-muted">Risk</div>{risk ? `${risk.score} (${risk.level})` : "—"}</div>
        <div><div className="text-xs text-muted">Latency · tokens</div>{d.run.latency_ms ?? "—"} ms · {d.run.tokens}</div>
      </div>
      {risk?.reasons?.length ? <ul className="list-disc space-y-0.5 pl-5 text-sm">{risk.reasons.map((r) => <li key={r}>{r}</li>)}</ul> : null}
      {d.flags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {d.flags.map((f) => <Badge key={f.code} tone={f.severity === "HIGH" ? "danger" : f.severity === "MEDIUM" ? "warn" : "neutral"} title={f.message}>{f.code}</Badge>)}
        </div>
      )}
      {d.run.status === "posted" && d.posting && (
        <p className="text-sm text-ok">Posted to ERP as {d.posting.erp_ref}{d.posting.payment_ref ? `, payment ${d.posting.payment_ref} scheduled` : ""}.</p>
      )}
      {d.run.status === "blocked" && <p className="text-sm text-danger">Blocked: the document contains hidden text or instructions addressed to an AI system. Logged for controller review.</p>}
      {pending && (
        <p className="text-sm">Needs <strong>{pending.required_role}</strong> approval. <Link className="text-accent underline" href="/app/approvals">Open approvals →</Link></p>
      )}
      {d.exception && (
        <div className="space-y-2 rounded-lg border border-warn/40 p-3">
          <div className="text-sm font-medium">Exception: {d.exception.type.replace(/_/g, " ")}</div>
          {d.exception.explanation && <p className="text-sm">{d.exception.explanation}</p>}
          {d.exception.drafted_email && (
            <details>
              <summary className="cursor-pointer text-sm text-accent">Drafted vendor email (copy only, never sent)</summary>
              <pre className="mt-2 whitespace-pre-wrap rounded bg-surface-2 p-2 text-xs">{d.exception.drafted_email}</pre>
            </details>
          )}
        </div>
      )}
      {d.approvals.filter((a) => a.status === "decided").map((a) => (
        <p key={a.step} className="text-sm text-muted">Step {a.step}: {a.decision} by {a.decided_by?.replace("persona:", "")} — “{a.comment}”</p>
      ))}
      {d.run.error && <p className="text-sm text-danger">{d.run.error}</p>}
    </Card>
  );
}
