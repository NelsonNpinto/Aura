"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote } from "@/components/ui";
import { api } from "@/lib/api";

type Verdict = {
  id: string;
  passed: boolean | null;
  expected_pass: boolean;
  score?: number;
  unsupported_claims?: string[];
  error?: string;
  model?: string;
  prompt_version?: number;
};

type Report = {
  gate_passed: boolean;
  errors: number;
  false_passes: string[];
  false_fails: string[];
  human_calibration: { agreement: number | null } | null;
  results: Verdict[];
};

type Comparison = {
  dataset_sha256?: string;
  baseline: Report;
  candidate: Report;
  reviews?: Record<string, string>;
};

type Setup = {
  dataset_sha256: string;
  cases: { id: string; facts: string; draft: string }[];
  simulation: Comparison;
  live: {
    models: string[];
    versions: number[];
    current: number | null;
    blocker: string | null;
  } | null;
};

const selectStyle =
  "w-full rounded-md border border-border bg-surface px-3 py-2 text-sm";

function VerdictPanel({ title, verdict }: { title: string; verdict: Verdict }) {
  return (
    <div className="min-w-0 space-y-2 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="font-medium">{title}</h4>
        <Badge
          tone={
            verdict.passed === null ? "warn" : verdict.passed ? "ok" : "danger"
          }
        >
          {verdict.passed === null
            ? "Unscored"
            : verdict.passed
              ? "Approved"
              : "Rejected"}
        </Badge>
      </div>
      {verdict.model && (
        <p className="break-all text-xs text-muted">
          Prompt v{verdict.prompt_version} · {verdict.model}
        </p>
      )}
      {verdict.score !== undefined && (
        <p className="text-sm">
          Rubric score {Math.round(verdict.score * 100)}%
        </p>
      )}
      {verdict.error && (
        <p className="text-sm text-danger">Judge error · {verdict.error}</p>
      )}
      {verdict.unsupported_claims &&
        (verdict.unsupported_claims.length ? (
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
            {verdict.unsupported_claims.map((claim, index) => (
              <li key={index}>{claim}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">
            The judge flagged no unsupported claims.
          </p>
        ))}
    </div>
  );
}

export function MarketingComparison() {
  const setup = useQuery({
    queryKey: ["marketing-comparison"],
    queryFn: () => api<Setup>("/quality/marketing-comparison"),
  });
  const [selectedCase, setSelectedCase] = useState("");
  const [baseline, setBaseline] = useState("");
  const [candidate, setCandidate] = useState("");
  const live = useMutation({
    mutationFn: (body: object) =>
      api<Comparison>("/quality/marketing-comparison", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => setSelectedCase(""),
  });

  const data = setup.data;
  const liveResult =
    live.data?.dataset_sha256 === data?.dataset_sha256 ? live.data : undefined;
  const comparison = liveResult ?? data?.simulation;
  const isLive = Boolean(liveResult);
  const liveOptions = data?.live;
  const options =
    liveOptions?.versions.flatMap((version) =>
      liveOptions.models.map((model) => ({
        key: `${version}:${model}`,
        value: { prompt_version: version, model },
      })),
    ) ?? [];
  const current =
    options.find(
      (option) => option.value.prompt_version === data?.live?.current,
    ) ?? options[0];
  const leftChoice =
    options.find((option) => option.key === baseline) ?? current;
  const rightChoice =
    options.find((option) => option.key === candidate) ??
    options.find((option) => option !== leftChoice);
  const preferred =
    comparison?.candidate.false_passes[0] ??
    comparison?.candidate.false_fails[0];
  const active =
    data?.cases.find((item) => item.id === (selectedCase || preferred)) ??
    data?.cases[0];
  const left = comparison?.baseline.results.find(
    (row) => row.id === active?.id,
  );
  const right = comparison?.candidate.results.find(
    (row) => row.id === active?.id,
  );
  const falsePass = right?.passed === true && !right.expected_pass;

  return (
    <Card className="space-y-5" aria-labelledby="marketing-comparison-title">
      <div className="space-y-2">
        <Badge tone="accent">Marketing evaluation</Badge>
        <h2 id="marketing-comparison-title" className="text-xl font-semibold">
          Compare judge versions
        </h2>
        <p className="text-sm text-muted">
          See what each judge approved, what the source facts support, and which
          case blocked the gate.
        </p>
      </div>
      <ErrorNote error={setup.error} />
      {setup.isPending && (
        <p className="text-sm text-muted">Loading the marketing dataset…</p>
      )}
      {data?.live?.blocker && (
        <p className="text-sm text-muted">{data.live.blocker}</p>
      )}
      {data?.live && !data.live.blocker && (
        <div className="space-y-3 rounded-lg border border-border p-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                ["Current configuration", leftChoice?.key, setBaseline],
                ["Proposed configuration", rightChoice?.key, setCandidate],
              ] as const
            ).map(([label, key, set]) => (
              <label className="space-y-1 text-sm" key={label}>
                <span className="font-medium">{label}</span>
                <select
                  className={selectStyle}
                  value={key ?? ""}
                  disabled={live.isPending}
                  onChange={(event) => set(event.target.value)}
                >
                  {options.map((option) => (
                    <option key={option.key} value={option.key}>
                      v{option.value.prompt_version} · {option.value.model}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              disabled={
                live.isPending ||
                !leftChoice ||
                !rightChoice ||
                leftChoice.key === rightChoice.key
              }
              onClick={() => {
                if (leftChoice && rightChoice)
                  live.mutate({
                    baseline: leftChoice.value,
                    candidate: rightChoice.value,
                    dataset_sha256: data.dataset_sha256,
                  });
              }}
            >
              {live.isPending ? "Comparing judges…" : "Run live comparison"}
            </Button>
            {isLive && (
              <Button
                variant="secondary"
                disabled={live.isPending}
                onClick={() => {
                  live.reset();
                  setSelectedCase("");
                }}
              >
                Show simulation
              </Button>
            )}
            <span className="text-xs text-muted">
              Live runs use provider quota and may take a few minutes.
            </span>
          </div>
          <ErrorNote error={live.error} />
        </div>
      )}
      {comparison && data && active && left && right && (
        <>
          <div
            className="flex flex-wrap items-center gap-2 border-y border-border py-3"
            aria-live="polite"
          >
            <Badge tone={isLive ? "accent" : "warn"}>
              {isLive ? "Live · human reviewed" : "Simulated example"}
            </Badge>
            <Badge tone={comparison.candidate.gate_passed ? "ok" : "danger"}>
              {comparison.candidate.gate_passed
                ? "Proposed gate passed"
                : isLive
                  ? "Proposed gate failed"
                  : "Would block release"}
            </Badge>
            <span className="text-sm text-muted">
              {data.cases.length} cases ·{" "}
              {comparison.candidate.false_passes.length} false approvals ·{" "}
              {comparison.candidate.errors} unscored
            </span>
          </div>
          <p className="text-xs text-muted">
            {isLive
              ? "This comparison evaluates the release rule. Actual deployment status is tracked in GitHub Actions."
              : "Fixture verdicts demonstrate the gate. No provider calls or human labels were used."}
          </p>
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            {(
              [
                ["Current", comparison.baseline],
                ["Proposed", comparison.candidate],
              ] as const
            ).map(([label, report]) => (
              <p key={label} className="text-muted">
                <span className="font-medium">{label}</span> ·{" "}
                {report.gate_passed ? "Gate passed" : "Gate failed"} ·{" "}
                {report.false_passes.length} false approvals
                {report.human_calibration?.agreement != null &&
                  ` · ${Math.round(report.human_calibration.agreement * 100)}% human agreement`}
              </p>
            ))}
          </div>
          <label className="block space-y-1 text-sm">
            <span className="font-medium">Inspect a case</span>
            <select
              className={selectStyle}
              value={active.id}
              onChange={(event) => setSelectedCase(event.target.value)}
            >
              {data.cases.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id.replaceAll("-", " ")}
                  {comparison.candidate.false_passes.includes(item.id)
                    ? " · false approval"
                    : comparison.candidate.false_fails.includes(item.id)
                      ? " · false rejection"
                      : ""}
                </option>
              ))}
            </select>
          </label>
          <div className="grid gap-3 rounded-lg border border-border bg-surface-2 p-4 text-sm sm:grid-cols-2">
            <div>
              <h3 className="font-medium">Source facts</h3>
              <p className="mt-1 text-muted">{active.facts}</p>
            </div>
            <div>
              <h3 className="font-medium">Marketing draft</h3>
              <p className="mt-1">{active.draft}</p>
            </div>
            <p className="sm:col-span-2 text-muted">
              {isLive ? "Human review" : "Fixture expectation"} ·{" "}
              {right.expected_pass ? "Approve" : "Reject"}
              {comparison.reviews?.[active.id]
                ? ` · ${comparison.reviews[active.id]}`
                : ""}
            </p>
          </div>
          {falsePass && (
            <p className="rounded-md border border-danger/40 bg-danger/5 px-3 py-2 text-sm text-danger">
              False approval. The proposed judge approved a draft that should be
              rejected.
            </p>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            <VerdictPanel title="Current judge" verdict={left} />
            <VerdictPanel title="Proposed judge" verdict={right} />
          </div>
        </>
      )}
    </Card>
  );
}
