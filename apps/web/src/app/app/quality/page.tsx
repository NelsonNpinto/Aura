"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge, Card, ErrorNote, Metric } from "@/components/ui";
import { api } from "@/lib/api";
import { JudgeWorkbench } from "@/components/judge-workbench";
import { MarketingComparison } from "@/components/marketing-comparison";

type Report = {
  id: string;
  dataset: string;
  dataset_version: string;
  provider_mode: string;
  case_count: number;
  created_at: string;
  case_snapshot: string;
  gate_passed: boolean;
  limits: string;
  metrics: {
    pass_rate: number | null;
    errors: number;
    false_auto_posts: number;
    extraction_f1: number | null;
    judge_agreement: number | null;
  };
  results: {
    case_id: string;
    passed: boolean;
    actual_status: string;
    actual_route: string;
    missing_flags?: string[];
    error?: string;
  }[];
};

type FinanceFixtures = {
  gate_passed: boolean;
  case_count: number;
  results: {
    id: string;
    question: string;
    answer: string;
    passed: boolean | null;
    verdict?: {
      claims: { claim: string; verdict: string; reason: string }[];
    };
  }[];
};

export default function QualityPage() {
  const me = useQuery({
    queryKey: ["quality-permissions"],
    queryFn: () => api<{ roles: string[] }>("/me"),
  });
  const query = useQuery({
    queryKey: ["eval-report"],
    queryFn: () => api<{ reports: Report[]; notice: string }>("/eval-report"),
  });
  const finance = useQuery({
    queryKey: ["finance-fixtures"],
    queryFn: () => api<FinanceFixtures>("/quality/finance-fixtures"),
  });
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold">
        AI quality and regression gates
      </h1>
      <p className="text-sm text-muted">
        These reports come from stored runs. Fixture checks exercise the
        workflow using supplied extraction data. They do not establish live
        model accuracy.
      </p>
      <Card className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Finance Copilot regression examples</h2>
          {finance.data && (
            <Badge tone={finance.data.gate_passed ? "ok" : "danger"}>
              {finance.data.gate_passed
                ? "Fixture gate passed"
                : "Fixture gate failed"}
            </Badge>
          )}
        </div>
        <p className="text-sm text-muted">
          Synthetic cases with supplied answers and judge verdicts. Live model
          quality and human agreement are unmeasured.
        </p>
        <ErrorNote error={finance.error} />
        {finance.isPending && (
          <p className="text-sm">Loading finance examples…</p>
        )}
        {finance.data?.results.map((result) => (
          <details
            key={result.id}
            className="rounded-lg border border-border p-3 text-sm"
          >
            <summary className="cursor-pointer">
              {result.question} ·{" "}
              {result.passed === null
                ? "Unscored"
                : result.passed
                  ? "Accepted"
                  : "Rejected"}
            </summary>
            <p className="mt-2">{result.answer}</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">
              {result.verdict?.claims.map((claim, index) => (
                <li key={index}>
                  {claim.verdict.replaceAll("_", " ")} · {claim.reason}
                </li>
              ))}
            </ul>
          </details>
        ))}
      </Card>
      <MarketingComparison />
      <ErrorNote error={query.error} />
      {query.isPending && <p>Loading evaluation evidence…</p>}
      {query.data?.reports.length === 0 && (
        <Card>
          No public evaluation report has been stored in this environment yet.
          CI publishes its report as an artifact. Model extraction quality and
          human agreement are not measured.
        </Card>
      )}
      {query.data?.reports.map((r) => (
        <Card key={r.id} className="space-y-4">
          <div className="flex flex-wrap justify-between gap-2">
            <h2 className="font-semibold">
              {r.dataset} · {r.case_count} cases
            </h2>
            <Badge tone={r.gate_passed ? "ok" : "danger"}>
              {r.gate_passed ? "Gate passed" : "Release blocked"}
            </Badge>
          </div>
          <p className="text-xs text-muted">
            {r.provider_mode === "fake"
              ? "Fixture responses"
              : "Live providers"}{" "}
            · {new Date(r.created_at).toLocaleString()} · dataset{" "}
            {r.dataset_version.slice(0, 12)} · snapshot{" "}
            {r.case_snapshot?.slice(0, 12)}
          </p>
          <div className="grid gap-4 sm:grid-cols-3">
            <Metric
              label="Workflow checks passed"
              value={
                r.metrics.pass_rate === null
                  ? null
                  : `${(r.metrics.pass_rate * 100).toFixed(1)}%`
              }
              source="Expected route, status and flags"
            />
            <Metric
              label="Incorrect auto routes"
              value={r.metrics.false_auto_posts}
              source="Stored per-case outcomes"
            />
            <Metric
              label="Extraction F1"
              value={r.metrics.extraction_f1}
              source="Requires an extraction benchmark"
            />
          </div>
          <p className="text-sm text-muted">{r.limits}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr>
                  <th className="p-2">Case</th>
                  <th className="p-2">Outcome</th>
                  <th className="p-2">Status / route</th>
                  <th className="p-2">Missing evidence</th>
                </tr>
              </thead>
              <tbody>
                {r.results.map((c) => (
                  <tr key={c.case_id} className="border-t border-border">
                    <td className="p-2">{c.case_id}</td>
                    <td className="p-2">
                      <Badge tone={c.passed ? "ok" : "danger"}>
                        {c.passed ? "pass" : "fail"}
                      </Badge>
                    </td>
                    <td className="p-2">
                      {c.actual_status} / {c.actual_route}
                    </td>
                    <td className="p-2">
                      {c.error ?? c.missing_flags?.join(", ") ?? ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
      {me.data?.roles.some((r) =>
        ["admin", "controller", "approver", "auditor"].includes(r),
      ) && <JudgeWorkbench />}
      <Card>
        <h2 className="font-semibold">Remaining quality coverage</h2>
        <p className="mt-2 text-sm text-muted">
          A larger marketing regression dataset and feedback-to-dataset triage
          remain. A passing fixture gate does not certify live model quality.
        </p>
      </Card>
    </div>
  );
}
