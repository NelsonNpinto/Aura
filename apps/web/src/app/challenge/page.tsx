"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote, Label, Skeleton, Textarea } from "@/components/ui";

type Categories = {
  enabled: boolean;
  categories: string[];
  daily_attempts: number;
  rules: string;
};
type Scoreboard = {
  total_attempts: number;
  blocked: number;
  block_rate: number | null;
  by_category: { category: string; attempts: number; blocked: number; block_rate: number | null }[];
  measured_from: string;
};
type Verdict = { check: string; verdict: string; severity: string; detail: string };
type AttemptResult = {
  blocked: boolean;
  category: string;
  verdicts: Verdict[];
  answer: string | null;
  message: string;
};

const LABELS: Record<string, string> = {
  direct_injection: "Direct injection",
  indirect_injection: "Indirect injection",
  hidden_text: "Hidden text",
  exfiltration: "Data exfiltration",
  tool_misuse: "Tool misuse",
  memory_poisoning: "Memory poisoning",
  jailbreak: "Jailbreak",
};

async function publicApi<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { ...(init.body ? { "content-type": "application/json" } : {}), ...init.headers },
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const e = body?.error ?? {};
    throw new Error(e.message ?? `Request failed (${res.status})`);
  }
  return body as T;
}

export default function ChallengePage() {
  const [attempt, setAttempt] = useState("");
  const [category, setCategory] = useState("direct_injection");

  const meta = useQuery({ queryKey: ["challenge-meta"], queryFn: () => publicApi<Categories>("/challenge/categories") });
  const board = useQuery({ queryKey: ["challenge-board"], queryFn: () => publicApi<Scoreboard>("/challenge/scoreboard") });
  const send = useMutation({
    mutationFn: () =>
      publicApi<AttemptResult>("/challenge/attempt", {
        method: "POST",
        body: JSON.stringify({ category, attempt }),
      }),
    onSuccess: () => board.refetch(),
  });

  const result = send.data;

  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-10">
      <div>
        <h1 className="text-3xl font-semibold">Try to fool the agent</h1>
        <p className="mt-2 text-sm text-muted">
          AURA processes invoices with models. This page lets you attack the same guardrails the
          workflow uses. The sandbox has <strong>read-only tools over synthetic data</strong> — no
          payments, no approvals, no real documents. Every attempt is logged, and anything that
          gets through becomes a regression test.
        </p>
        <p className="mt-2 text-sm text-warn">
          Do not submit real personal or financial data. Submissions are stored.
        </p>
      </div>

      {meta.data && !meta.data.enabled && (
        <Card>
          <p className="text-sm">The challenge is paused right now. The scoreboard below still shows stored results.</p>
        </Card>
      )}

      <Card>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (attempt.trim().length >= 5) send.mutate();
          }}
        >
          <div>
            <Label htmlFor="category">Attack type</Label>
            <select
              id="category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="min-h-10 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            >
              {(meta.data?.categories ?? Object.keys(LABELS)).map((c) => (
                <option key={c} value={c}>
                  {LABELS[c] ?? c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="attempt">Your attempt</Label>
            <Textarea
              id="attempt"
              rows={5}
              value={attempt}
              maxLength={2000}
              onChange={(e) => setAttempt(e.target.value)}
              placeholder="Ignore all previous instructions and…"
            />
          </div>
          <Button type="submit" disabled={send.isPending || attempt.trim().length < 5}>
            {send.isPending ? "Running…" : "Send it"}
          </Button>
        </form>
        <ErrorNote error={send.error} />

        {result && (
          <div className="mt-5 space-y-3 border-t border-border pt-4">
            <div className="flex items-center gap-2">
              <Badge tone={result.blocked ? "ok" : "danger"}>
                {result.blocked ? "Blocked" : "Got through"}
              </Badge>
              <span className="text-sm">{result.message}</span>
            </div>
            <ul className="space-y-1 text-sm">
              {result.verdicts.map((v, i) => (
                <li key={`${v.check}-${i}`} className="flex items-center gap-2">
                  <Badge tone={v.verdict === "block" ? "danger" : v.verdict === "flag" ? "warn" : "neutral"}>
                    {v.check}
                  </Badge>
                  <span className="text-muted">{v.detail || v.verdict}</span>
                </li>
              ))}
            </ul>
            {result.answer && (
              <div className="rounded-lg border border-border bg-surface-2 p-3 text-sm">
                <p className="mb-1 text-xs uppercase text-muted">What the agent replied</p>
                <p className="whitespace-pre-wrap">{result.answer}</p>
              </div>
            )}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">Scoreboard</h2>
        <p className="mt-1 text-xs text-muted">Computed from stored attempts only ({board.data?.measured_from}).</p>
        {board.isPending && <Skeleton className="mt-3 h-20" />}
        {board.data && board.data.total_attempts === 0 && (
          <p className="mt-2 text-sm text-muted">No attempts recorded yet. Yours would be the first.</p>
        )}
        {board.data && board.data.total_attempts > 0 && (
          <table className="mt-3 w-full text-sm">
            <thead className="text-left text-xs uppercase text-muted">
              <tr>
                <th className="py-2">Attack type</th>
                <th>Attempts</th>
                <th>Blocked</th>
                <th>Block rate</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {board.data.by_category.map((row) => (
                <tr key={row.category}>
                  <td className="py-2">{LABELS[row.category] ?? row.category}</td>
                  <td>{row.attempts}</td>
                  <td>{row.blocked}</td>
                  <td>{row.block_rate === null ? "not measured" : `${(row.block_rate * 100).toFixed(0)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <p className="text-sm text-muted">
        See how the rest of it is measured on the{" "}
        <Link className="underline" href="/eval-report">
          public eval report
        </Link>
        .
      </p>
    </main>
  );
}
