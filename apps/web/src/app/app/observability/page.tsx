"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, ErrorNote, Metric, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type Costs = {
  window_days: number;
  by_day: { day: string; calls: number; tokens_in: number; tokens_out: number; cost_microusd: number | null; cache_hits: number; fallbacks: number }[];
  by_task: { task: string; model: string; calls: number; cost_microusd: number | null; p50_ms: number | null; p95_ms: number | null }[];
  avg_cost_microusd_per_run: number | null;
  source: string;
};
type RunMetrics = {
  window_days: number;
  runs: number;
  stp_rate: number | null;
  hitl_rate: number | null;
  by_status: { status: string; route: string | null; n: number; p50_ms: number | null; p95_ms: number | null }[];
  human_overrides: { decisions: number; gl: number; fields: number };
  source: string;
};
type DriftMetric = { name: string; value: number | null; threshold: number; breached: boolean; reason: string };
type DriftReport = {
  id: string;
  window_start: string;
  window_end: string;
  metrics: { metrics: DriftMetric[]; observations: { reference: number; current: number } };
  breaches: string[];
  created_at: string;
};
type Guardrails = { window_days: number; blocks: number; by_check: { surface: string; check: string; verdict: string; n: number }[] };
type Hallucination = {
  window_days: number;
  answers: number;
  with_citations: number;
  citation_rate: number | null;
  output_blocks: number;
  judge_faithfulness: number | null;
  source: string;
};

function usd(microusd: number | null | undefined): string {
  if (microusd === null || microusd === undefined) return "not measured";
  return `$${(microusd / 1_000_000).toFixed(4)}`;
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "not measured" : `${(value * 100).toFixed(1)}%`;
}

export default function ObservabilityPage() {
  const qc = useQueryClient();
  const costs = useQuery({ queryKey: ["obs-costs"], queryFn: () => api<Costs>("/observability/costs") });
  const runs = useQuery({ queryKey: ["obs-runs"], queryFn: () => api<RunMetrics>("/observability/runs") });
  const drift = useQuery({ queryKey: ["obs-drift"], queryFn: () => api<{ reports: DriftReport[] }>("/observability/drift") });
  const guards = useQuery({ queryKey: ["obs-guardrails"], queryFn: () => api<Guardrails>("/guardrails/summary") });
  const halluc = useQuery({
    queryKey: ["obs-hallucination"],
    queryFn: () => api<Hallucination>("/observability/hallucination"),
  });
  const runDrift = useMutation({
    mutationFn: () => api<DriftReport>("/observability/drift/run", { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["obs-drift"] }),
  });

  const latest = drift.data?.reports[0];

  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Observability</h1>
        <p className="mt-1 text-sm text-muted">
          Every figure here comes from stored rows. Where nothing has been measured the value
          reads &quot;not measured&quot; rather than zero. Costs are list-price estimates; the free
          tiers are not billed.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <Metric label="Runs" value={runs.data?.runs ?? null} source="ap.runs" />
        </Card>
        <Card>
          <Metric label="Straight-through rate" value={pct(runs.data?.stp_rate)} source="ap.runs" />
        </Card>
        <Card>
          <Metric label="Human-in-the-loop rate" value={pct(runs.data?.hitl_rate)} source="ap.runs" />
        </Card>
        <Card>
          <Metric
            label="Estimated cost per run"
            value={usd(costs.data?.avg_cost_microusd_per_run)}
            source="ap.runs (list prices)"
          />
        </Card>
      </div>

      <Card>
        <h2 className="font-semibold">Model cost and latency</h2>
        {costs.isPending && <Skeleton className="mt-3 h-24" />}
        <ErrorNote error={costs.error} />
        {costs.data && costs.data.by_task.length === 0 && (
          <p className="mt-2 text-sm text-muted">No model calls recorded in this window.</p>
        )}
        {costs.data && costs.data.by_task.length > 0 && (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-muted">
                <tr>
                  <th className="py-2">Task</th>
                  <th>Model</th>
                  <th>Calls</th>
                  <th>Est. cost</th>
                  <th>p50</th>
                  <th>p95</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {costs.data.by_task.map((t) => (
                  <tr key={`${t.task}-${t.model}`}>
                    <td className="py-2">{t.task}</td>
                    <td className="font-mono text-xs">{t.model}</td>
                    <td>{t.calls}</td>
                    <td>{usd(t.cost_microusd)}</td>
                    <td>{t.p50_ms === null ? "—" : `${t.p50_ms} ms`}</td>
                    <td>{t.p95_ms === null ? "—" : `${t.p95_ms} ms`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">Guardrails</h2>
        {guards.isPending && <Skeleton className="mt-3 h-20" />}
        <ErrorNote error={guards.error} />
        {guards.data && (
          <>
            <p className="mt-2 text-sm">
              <strong>{guards.data.blocks}</strong> block(s) in the last {guards.data.window_days}{" "}
              days.
            </p>
            <ul className="mt-2 flex flex-wrap gap-2 text-xs">
              {guards.data.by_check.map((row) => (
                <li key={`${row.surface}-${row.check}-${row.verdict}`}>
                  <Badge tone={row.verdict === "block" ? "danger" : row.verdict === "flag" ? "warn" : "neutral"}>
                    {row.surface}/{row.check}: {row.verdict} ×{row.n}
                  </Badge>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Drift</h2>
          <Button variant="secondary" onClick={() => runDrift.mutate()} disabled={runDrift.isPending}>
            {runDrift.isPending ? "Computing…" : "Compute now"}
          </Button>
        </div>
        <ErrorNote error={runDrift.error} />
        {drift.isPending && <Skeleton className="mt-3 h-20" />}
        {latest ? (
          <div className="mt-3 space-y-2">
            <p className="text-xs text-muted">
              Window {new Date(latest.window_start).toLocaleDateString()} –{" "}
              {new Date(latest.window_end).toLocaleDateString()} ·{" "}
              {latest.metrics.observations?.current ?? 0} current vs{" "}
              {latest.metrics.observations?.reference ?? 0} reference observations
            </p>
            <ul className="divide-y divide-border text-sm">
              {latest.metrics.metrics?.map((m) => (
                <li key={m.name} className="flex items-center justify-between py-2">
                  <span>{m.name}</span>
                  <span className="flex items-center gap-2">
                    <span className={m.breached ? "text-danger" : ""}>
                      {m.value === null ? "not measured" : m.value}
                    </span>
                    <Badge tone={m.breached ? "danger" : m.value === null ? "neutral" : "ok"}>
                      {m.value === null ? m.reason : m.breached ? "breached" : "ok"}
                    </Badge>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="mt-2 text-sm text-muted">
            No drift report stored yet. The nightly job writes one; you can also compute one now.
          </p>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">Copilot grounding</h2>
        {halluc.isPending && <Skeleton className="mt-3 h-16" />}
        <ErrorNote error={halluc.error} />
        {halluc.data && (
          <div className="mt-3 grid gap-4 sm:grid-cols-4">
            <Metric label="Answers" value={halluc.data.answers} source={halluc.data.source} />
            <Metric label="With citations" value={halluc.data.with_citations} source={halluc.data.source} />
            <Metric label="Citation rate" value={pct(halluc.data.citation_rate)} source={halluc.data.source} />
            <Metric
              label="Judge faithfulness"
              value={halluc.data.judge_faithfulness}
              source="measured only by an eval run"
            />
          </div>
        )}
      </Card>
    </div>
  );
}
