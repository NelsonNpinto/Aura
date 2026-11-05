"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote, Label, Skeleton, Textarea } from "@/components/ui";
import { api } from "@/lib/api";

type Task = { task: string; chain: string[]; prompt: { name: string; label: string }; cache: string; temperature: number; structured: boolean };
type Attempt = { model: string; status: string; reason: string | null; latency_ms: number };
type RunRes = { text: string; model: string; prompt: { name: string; version: number }; tokens_in: number; tokens_out: number;
  est_cost_microusd: number; latency_ms: number; cache_hit: boolean; fallback_reason: string | null; attempts: Attempt[]; trace_id: string };

export default function PlaygroundPage() {
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => api<Task[]>("/playground/tasks") });
  const [input, setInput] = useState("Summarise the three-way match in one sentence.");
  const run = useMutation({
    mutationFn: () => api<RunRes>("/playground/run", { method: "POST", body: JSON.stringify({ task: "playground", variables: { input } }) }),
  });

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">Model playground</h1>
      <Card>
        <Label htmlFor="input">Input (task: playground)</Label>
        <Textarea id="input" rows={4} maxLength={4000} value={input} onChange={(e) => setInput(e.target.value)} />
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={() => run.mutate()} disabled={run.isPending || !input.trim()}>{run.isPending ? "Running…" : "Run through router"}</Button>
          <span className="text-xs text-muted">Counts against the daily demo budget.</span>
        </div>
        <div className="mt-3"><ErrorNote error={run.error} /></div>
        {run.data && (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap gap-2">
              <Badge tone="accent">{run.data.model}</Badge>
              <Badge>prompt {run.data.prompt.name} v{run.data.prompt.version}</Badge>
              <Badge>{run.data.tokens_in} in / {run.data.tokens_out} out</Badge>
              <Badge>{run.data.latency_ms} ms</Badge>
              <Badge>est. ${(run.data.est_cost_microusd / 1e6).toFixed(6)} at list price</Badge>
              {run.data.cache_hit && <Badge tone="accent">cache hit</Badge>}
              {run.data.fallback_reason && <Badge tone="warn">fallback: {run.data.fallback_reason}</Badge>}
            </div>
            <pre className="whitespace-pre-wrap rounded-md bg-surface-2 p-3 text-sm">{run.data.text}</pre>
            <details className="text-sm">
              <summary className="cursor-pointer text-muted">Attempts ({run.data.attempts.length}) · trace {run.data.trace_id.slice(0, 12)}</summary>
              <ul className="mt-2 space-y-1 font-mono text-xs">
                {run.data.attempts.map((a, i) => <li key={i}>{a.model} → {a.status}{a.reason ? ` (${a.reason})` : ""} {a.latency_ms} ms</li>)}
              </ul>
            </details>
          </div>
        )}
      </Card>
      <Card>
        <h2 className="font-semibold">Router tasks</h2>
        {tasks.isPending && <Skeleton className="mt-3 h-24" />}
        <ErrorNote error={tasks.error} />
        <table className="mt-3 w-full text-left text-sm">
          <thead className="text-xs uppercase text-muted"><tr><th className="py-1">Task</th><th>Chain</th><th>Prompt</th><th>Cache</th></tr></thead>
          <tbody>
            {tasks.data?.map((t) => (
              <tr key={t.task} className="border-t border-border align-top">
                <td className="py-1.5 font-mono">{t.task}</td>
                <td className="font-mono text-xs">{t.chain.join(" → ")}</td>
                <td className="text-xs">{t.prompt.name}@{t.prompt.label}</td>
                <td className="text-xs">{t.cache}{t.structured ? " · json" : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
