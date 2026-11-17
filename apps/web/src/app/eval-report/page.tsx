"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Badge, Card, Skeleton } from "@/components/ui";

type Figure = {
  value: number | null;
  status: "measured" | "not measured";
  run_id: string | null;
  dataset?: string;
  dataset_version?: string | null;
  provider_mode?: string;
  measured_at?: string;
};
type Report = {
  slug: string;
  git_sha: string | null;
  published_at: string;
  generated_at: string;
  headline: Record<string, Figure>;
  runs: {
    id: string;
    dataset: string;
    dataset_version: string;
    mode: string;
    provider_mode: string;
    case_count: number;
    git_sha: string | null;
    metrics: Record<string, number | null>;
    measured_at: string;
    limits: string | null;
  }[];
  notes: string[];
};

const LABELS: Record<string, string> = {
  workflow_pass_rate: "Workflow pass rate",
  false_auto_posts: "False auto-posts (hard gate: 0)",
  extraction_f1: "Extraction F1",
  stp_rate: "Straight-through processing",
  attack_success_rate: "Attack success rate",
  guardrail_false_positive_rate: "Guardrail false positives on clean input",
  copilot_citation_validity: "Copilot citation validity",
  rag_faithfulness: "RAG faithfulness (offline)",
  trajectory_accuracy: "Copilot trajectory accuracy",
  cost_microusd_per_case: "Estimated cost per case",
  p95_latency_ms: "p95 latency",
  judge_kappa: "Judge/human agreement (kappa)",
};

const RATE_KEYS = new Set([
  "workflow_pass_rate",
  "stp_rate",
  "attack_success_rate",
  "guardrail_false_positive_rate",
  "copilot_citation_validity",
  "rag_faithfulness",
  "trajectory_accuracy",
  "extraction_f1",
]);

function render(key: string, figure: Figure): string {
  if (figure.value === null || figure.status !== "measured") return "not measured";
  if (RATE_KEYS.has(key)) return `${(figure.value * 100).toFixed(1)}%`;
  if (key === "cost_microusd_per_case") return `$${(figure.value / 1_000_000).toFixed(4)}`;
  if (key === "p95_latency_ms") return `${Math.round(figure.value)} ms`;
  return String(figure.value);
}

async function publicApi<T>(path: string): Promise<T> {
  const res = await fetch(`/api/v1${path}`);
  if (res.status === 404) throw new Error("not-published");
  if (!res.ok) throw new Error(`Request failed (${res.status})`);
  return (await res.json()) as T;
}

export default function EvalReportPage() {
  const report = useQuery({
    queryKey: ["eval-report"],
    queryFn: () => publicApi<Report>("/eval-report"),
    retry: false,
  });

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-4 py-10">
      <div>
        <h1 className="text-3xl font-semibold">Eval report</h1>
        <p className="mt-2 text-sm text-muted">
          Published from stored evaluation runs. Every number links back to the run that produced
          it, with its dataset version and the date it was measured. Anything not measured says so.
        </p>
      </div>

      {report.isPending && <Skeleton className="h-40" />}

      {report.isError && (
        <Card>
          <p className="text-sm">
            No report has been published yet. The weekly evaluation publishes one; until then this
            page shows nothing rather than a placeholder figure.
          </p>
        </Card>
      )}

      {report.data && (
        <>
          <p className="text-xs text-muted">
            Published {new Date(report.data.published_at).toLocaleString()} · git{" "}
            <code>{(report.data.git_sha ?? "unknown").slice(0, 8)}</code>
          </p>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(report.data.headline).map(([key, figure]) => (
              <Card key={key}>
                <p className="text-xs uppercase tracking-wide text-muted">{LABELS[key] ?? key}</p>
                <p className="mt-1 text-2xl font-semibold">{render(key, figure)}</p>
                <p className="mt-2 text-xs text-muted">
                  {figure.status === "measured" ? (
                    <>
                      {figure.dataset} · {figure.provider_mode} ·{" "}
                      {figure.measured_at ? new Date(figure.measured_at).toLocaleDateString() : ""}
                      {figure.run_id ? (
                        <>
                          {" "}
                          · run <code>{figure.run_id.slice(0, 8)}</code>
                        </>
                      ) : null}
                    </>
                  ) : (
                    "no stored run behind this figure yet"
                  )}
                </p>
              </Card>
            ))}
          </div>

          <Card>
            <h2 className="font-semibold">Runs behind these figures</h2>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase text-muted">
                  <tr>
                    <th className="py-2">Dataset</th>
                    <th>Version</th>
                    <th>Mode</th>
                    <th>Cases</th>
                    <th>Measured</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {report.data.runs.map((r) => (
                    <tr key={r.id}>
                      <td className="py-2">{r.dataset}</td>
                      <td className="font-mono text-xs">{r.dataset_version?.slice(0, 10)}</td>
                      <td>
                        <Badge tone={r.provider_mode === "live" ? "ok" : "neutral"}>
                          {r.mode}/{r.provider_mode}
                        </Badge>
                      </td>
                      <td>{r.case_count}</td>
                      <td>{new Date(r.measured_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="mt-3 space-y-1 text-xs text-muted">
              {report.data.runs
                .filter((r) => r.limits)
                .map((r) => (
                  <li key={`${r.id}-limit`}>
                    <strong>{r.dataset}:</strong> {r.limits}
                  </li>
                ))}
            </ul>
          </Card>

          <Card>
            <h2 className="font-semibold">How to read this</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted">
              {report.data.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </Card>
        </>
      )}

      <p className="text-sm text-muted">
        Want to test the guardrails yourself?{" "}
        <Link className="underline" href="/challenge">
          Try the challenge
        </Link>
        .
      </p>
    </main>
  );
}
