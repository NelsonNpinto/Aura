"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote, Input, Label, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type ModelVersion = {
  id: string;
  name: string;
  task: string;
  base_model: string;
  adapter_repo: string;
  adapter_revision: string;
  dataset_version: string;
  metrics: Record<string, unknown>;
  status: "candidate" | "canary" | "production" | "retired";
  canary_percent: number;
  promoted_by: string | null;
  promoted_at: string | null;
  created_at: string;
};
type Models = { versions: ModelVersion[]; serving: { specialist_enabled: boolean; space: string | null } };
type Policies = {
  input: { check: string; action: string; detail?: string }[];
  output: { check: string; action: string }[];
  chunking: { chars: number; stride: number; max_chars: number };
};
type GraphStatus = { configured: boolean; reason: string; templates: { name: string }[] };

const STATUS_TONE: Record<ModelVersion["status"], "ok" | "warn" | "accent" | "neutral"> = {
  production: "ok",
  canary: "warn",
  candidate: "accent",
  retired: "neutral",
};

export default function AdminPage() {
  const qc = useQueryClient();
  const [justification, setJustification] = useState("");

  const models = useQuery({ queryKey: ["models"], queryFn: () => api<Models>("/models") });
  const policies = useQuery({ queryKey: ["guardrail-policies"], queryFn: () => api<Policies>("/guardrails/policies") });
  const graph = useQuery({ queryKey: ["graph-status-admin"], queryFn: () => api<GraphStatus>("/graph/status") });

  const promote = useMutation({
    mutationFn: (args: { id: string; status: ModelVersion["status"]; canary: number }) =>
      api(`/models/${args.id}/promote`, {
        method: "POST",
        body: JSON.stringify({
          status: args.status,
          canary_percent: args.canary,
          justification: justification || "Promoted from the admin page",
        }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["models"] }),
  });

  const syncGraph = useMutation({
    mutationFn: () => api<{ status: string; applied: number; pending: number }>("/graph/sync", { method: "POST" }),
  });

  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Admin</h1>
        <p className="mt-1 text-sm text-muted">
          Prompts, tools, models, guardrails and memory. Every promotion and rollback here is
          audited.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { href: "/app/admin/playground", label: "Prompt playground", detail: "Run any router task" },
          { href: "/app/memories", label: "Agent memory", detail: "See and delete what it knows" },
          { href: "/app/graph", label: "Knowledge graph", detail: "Templates and fraud patterns" },
          { href: "/app/observability", label: "Observability", detail: "Cost, latency, drift" },
        ].map((link) => (
          <Link key={link.href} href={link.href}>
            <Card className="h-full transition hover:border-accent">
              <p className="font-semibold">{link.label}</p>
              <p className="mt-1 text-sm text-muted">{link.detail}</p>
            </Card>
          </Link>
        ))}
      </div>

      <Card>
        <h2 className="font-semibold">Model registry</h2>
        <p className="mt-1 text-sm text-muted">
          A candidate must beat production on the held-out test split and pass the golden-set
          gates before it can run as a canary. Promotion is manual by design.
        </p>
        {models.isPending && <Skeleton className="mt-3 h-20" />}
        <ErrorNote error={models.error} />
        {models.data && (
          <p className="mt-2 text-xs text-muted">
            Specialist serving:{" "}
            {models.data.serving.specialist_enabled ? (
              <>enabled ({models.data.serving.space ?? "no space configured"})</>
            ) : (
              "disabled (ENABLE_SPECIALIST=false); the router uses the general chain"
            )}
          </p>
        )}
        {models.data?.versions.length === 0 && (
          <p className="mt-2 text-sm text-muted">
            No model versions registered yet. The retrain workflow registers candidates.
          </p>
        )}
        {models.data && models.data.versions.length > 0 && (
          <>
            <div className="mt-3">
              <Label htmlFor="justification">Justification (recorded in the audit chain)</Label>
              <Input
                id="justification"
                value={justification}
                onChange={(e) => setJustification(e.target.value)}
                placeholder="Beats production by 6 points on held-out test"
              />
            </div>
            <ul className="mt-3 divide-y divide-border text-sm">
              {models.data.versions.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Badge tone={STATUS_TONE[v.status]}>{v.status}</Badge>
                      <code className="text-xs">{v.name}</code>
                      <span className="text-xs text-muted">{v.task}</span>
                    </div>
                    <p className="mt-1 text-xs text-muted">
                      {v.base_model} · adapter {v.adapter_revision || "—"} · dataset{" "}
                      {v.dataset_version ? v.dataset_version.slice(0, 10) : "—"}
                      {v.canary_percent ? ` · canary ${v.canary_percent}%` : ""}
                    </p>
                    <p className="mt-1 text-xs text-muted">
                      {Object.keys(v.metrics).length === 0
                        ? "no eval metrics stored"
                        : JSON.stringify(v.metrics)}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      onClick={() => promote.mutate({ id: v.id, status: "canary", canary: 20 })}
                      disabled={promote.isPending || v.status === "canary"}
                    >
                      Canary 20%
                    </Button>
                    <Button
                      onClick={() => promote.mutate({ id: v.id, status: "production", canary: 0 })}
                      disabled={promote.isPending || v.status === "production"}
                    >
                      Promote
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => promote.mutate({ id: v.id, status: "retired", canary: 0 })}
                      disabled={promote.isPending || v.status === "retired"}
                    >
                      Retire
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
            <ErrorNote error={promote.error} />
          </>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">Guardrail policies in force</h2>
        {policies.isPending && <Skeleton className="mt-3 h-20" />}
        <ErrorNote error={policies.error} />
        {policies.data && (
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <div>
              <h3 className="text-sm font-semibold">Input</h3>
              <ul className="mt-1 space-y-1 text-sm">
                {policies.data.input.map((p) => (
                  <li key={p.check}>
                    <Badge tone={p.action === "block" ? "danger" : "warn"}>{p.action}</Badge>{" "}
                    <code className="text-xs">{p.check}</code>
                    {p.detail ? <span className="text-muted"> — {p.detail}</span> : null}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 className="text-sm font-semibold">Output</h3>
              <ul className="mt-1 space-y-1 text-sm">
                {policies.data.output.map((p) => (
                  <li key={p.check}>
                    <Badge tone="danger">{p.action}</Badge> <code className="text-xs">{p.check}</code>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted">
                Classifier chunking: {policies.data.chunking.chars} chars, stride{" "}
                {policies.data.chunking.stride}, up to {policies.data.chunking.max_chars}.
              </p>
            </div>
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">Knowledge-graph projection</h2>
        <p className="mt-1 text-sm text-muted">
          Writes queue in the outbox and are applied as idempotent MERGEs. Drain it here or let
          the nightly reconcile do it.
        </p>
        <p className="mt-2 text-xs text-muted">
          Status: {graph.data ? (graph.data.configured ? "available" : `unavailable (${graph.data.reason})`) : "…"}
        </p>
        <Button className="mt-3" variant="secondary" onClick={() => syncGraph.mutate()} disabled={syncGraph.isPending}>
          {syncGraph.isPending ? "Syncing…" : "Drain the outbox"}
        </Button>
        <ErrorNote error={syncGraph.error} />
        {syncGraph.data && (
          <p className="mt-2 text-sm">
            {syncGraph.data.status === "ok"
              ? `Applied ${syncGraph.data.applied} message(s).`
              : `Graph unavailable; ${syncGraph.data.pending} message(s) left queued.`}
          </p>
        )}
      </Card>
    </div>
  );
}
