"use client";

import clsx from "clsx";
import { Check, Circle, Loader2, PauseCircle, ShieldAlert, X } from "lucide-react";
import { Badge } from "@/components/ui";
import type { RunEvent } from "@/lib/api";

export const NODES: { id: string; label: string; hint: string }[] = [
  { id: "intake_guard", label: "Intake guard", hint: "Hidden text, injection, PII" },
  { id: "extract", label: "Extract", hint: "Text or vision extraction" },
  { id: "validate", label: "Validate", hint: "Arithmetic, tax, dates" },
  { id: "vendor_verify", label: "Vendor verify", hint: "Vendor master, bank, duplicates" },
  { id: "match", label: "Three-way match", hint: "PO + goods receipt" },
  { id: "code_gl", label: "GL coding", hint: "Account and cost center" },
  { id: "policy_check", label: "Policy check", hint: "Policy citations" },
  { id: "risk_route", label: "Risk & route", hint: "Deterministic score" },
  { id: "human_approval", label: "Human approval", hint: "SoD-checked decision" },
  { id: "post_and_schedule", label: "Post & pay", hint: "ERP posting, payment" },
  { id: "finalize", label: "Finalize", hint: "Lineage, metrics" },
];

const STATUS_TONE: Record<string, "ok" | "warn" | "danger" | "accent" | "neutral"> = {
  posted: "ok",
  awaiting_approval: "warn",
  exception: "warn",
  blocked: "danger",
  rejected: "danger",
  failed: "danger",
  running: "accent",
  queued: "neutral",
  cancelled: "neutral",
};

export function StatusChip({ status }: { status: string | null | undefined }) {
  const s = status ?? "unknown";
  return <Badge tone={STATUS_TONE[s] ?? "neutral"}>{s.replace(/_/g, " ")}</Badge>;
}

export type NodeState = "idle" | "running" | "done" | "paused" | "error";

export function nodeStates(events: RunEvent[]): Record<string, { state: NodeState; summary?: string; ms?: number; tokens?: number }> {
  const out: Record<string, { state: NodeState; summary?: string; ms?: number; tokens?: number }> = {};
  for (const e of events) {
    if (!e.node) continue;
    if (e.type === "node.started") out[e.node] = { state: "running" };
    if (e.type === "node.completed")
      out[e.node] = {
        state: "done",
        summary: String(e.payload.summary ?? ""),
        ms: Number(e.payload.duration_ms ?? 0),
        tokens: Number(e.payload.tokens ?? 0),
      };
    if (e.type === "interrupt") out[e.node] = { state: "paused", summary: "Waiting for a human decision" };
  }
  if (events.some((e) => e.type === "run.failed")) {
    const running = Object.entries(out).find(([, v]) => v.state === "running");
    if (running) out[running[0]] = { state: "error" };
  }
  return out;
}

export function Pipeline({ events }: { events: RunEvent[] }) {
  const st = nodeStates(events);
  const flagsByNode: Record<string, string[]> = {};
  for (const e of events) if (e.type === "flag.raised" && e.node) (flagsByNode[e.node] ??= []).push(String(e.payload.code));
  return (
    <ol className="space-y-1.5" aria-label="Workflow steps">
      {NODES.map((n) => {
        const s = st[n.id]?.state ?? "idle";
        const Icon = s === "done" ? Check : s === "running" ? Loader2 : s === "paused" ? PauseCircle : s === "error" ? X : Circle;
        return (
          <li key={n.id}
            className={clsx("flex items-start gap-3 rounded-lg border px-3 py-2 transition-colors",
              s === "idle" && "border-border opacity-50",
              s === "running" && "border-accent bg-accent/5",
              s === "done" && "border-border",
              s === "paused" && "border-warn bg-warn/5",
              s === "error" && "border-danger bg-danger/5")}>
            <Icon size={18} className={clsx("mt-0.5 shrink-0", s === "running" && "animate-spin text-accent",
              s === "done" && "text-ok", s === "paused" && "text-warn", s === "error" && "text-danger")} aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{n.label}</span>
                <span className="text-xs text-muted">{n.hint}</span>
                {st[n.id]?.ms !== undefined && <span className="ml-auto text-xs tabular-nums text-muted">{st[n.id]?.ms} ms{st[n.id]?.tokens ? ` · ${st[n.id]?.tokens} tok` : ""}</span>}
              </div>
              {st[n.id]?.summary && <div className="mt-0.5 break-words text-xs text-muted">{st[n.id]?.summary}</div>}
              {flagsByNode[n.id] && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {flagsByNode[n.id].map((f) => (
                    <Badge key={f} tone={/INJECTION|HIDDEN|BANK|DUPLICATE|CONFLICT|OVER/.test(f) ? "danger" : "warn"}>
                      <ShieldAlert size={11} className="mr-1 inline" aria-hidden />{f}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function EventLog({ events }: { events: RunEvent[] }) {
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-border font-mono text-xs">
      {events.map((e) => (
        <div key={e.seq} className="flex gap-2 border-b border-border px-2 py-1 last:border-0">
          <span className="w-8 shrink-0 text-right tabular-nums text-muted">{e.seq}</span>
          <span className="w-32 shrink-0 text-accent">{e.type}</span>
          <span className="w-28 shrink-0 text-muted">{e.node ?? ""}</span>
          <span className="min-w-0 truncate">{summarize(e)}</span>
        </div>
      ))}
    </div>
  );
}

function summarize(e: RunEvent): string {
  const p = e.payload;
  if (e.type === "tool.called") return String(p.tool);
  if (e.type === "tool.result") return `${p.tool} ${p.ok ? "ok" : `error ${p.error}`}${p.latency_ms ? ` · ${p.latency_ms} ms` : ""}`;
  if (e.type === "llm.call") return `${p.task} → ${p.model}${p.cache_hit ? " (cache)" : ""}${p.fallback_reason ? ` · fallback ${p.fallback_reason}` : ""}`;
  if (e.type === "guardrail.verdict") return `${p.check}${p.blocked ? " BLOCK" : ""}`;
  if (e.type === "flag.raised") return `${p.code} (${p.severity}) ${p.message ?? ""}`;
  if (e.type === "node.completed") return String(p.summary ?? "");
  if (e.type === "run.completed") return `route ${p.route}, outcome ${p.outcome}`;
  if (e.type === "interrupt") return "approval required";
  return "";
}
