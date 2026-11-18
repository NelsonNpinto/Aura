"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { SafeMarkdown } from "@/components/safe-markdown";
import { Badge, Button, Card, ErrorNote, Skeleton, Textarea } from "@/components/ui";
import { api, streamEvents } from "@/lib/api";

type Thread = { id: string; title: string; created_at: string; last_message_at: string | null };
type Source = { id: string; kind: string; tool: string; summary: string };
type Turn = {
  question: string;
  answer: string;
  sources: Source[];
  citationValid: boolean;
  invalid: string[];
  steps: { label: string; tone: "neutral" | "accent" | "ok" }[];
  failed?: string;
};

export default function CopilotChatPage() {
  const qc = useQueryClient();
  const [threadId, setThreadId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const abort = useRef<AbortController | null>(null);

  const threads = useQuery({
    queryKey: ["copilot-threads"],
    queryFn: () => api<{ threads: Thread[] }>("/copilot/threads"),
  });

  async function ask() {
    const q = question.trim();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    setQuestion("");
    const index = turns.length;
    setTurns((t) => [
      ...t,
      { question: q, answer: "", sources: [], citationValid: true, invalid: [], steps: [] },
    ]);
    const controller = new AbortController();
    abort.current = controller;

    const patch = (fn: (turn: Turn) => Turn) =>
      setTurns((all) => all.map((t, i) => (i === index ? fn(t) : t)));

    try {
      await streamEvents(
        "/copilot/chat",
        { method: "POST", body: JSON.stringify({ question: q, thread_id: threadId }) },
        (type, data) => {
          if (type === "copilot.step") {
            patch((t) => ({
              ...t,
              steps: [...t.steps, { label: `step ${data.step}: ${data.action}`, tone: "neutral" }],
            }));
          } else if (type === "tool.called") {
            patch((t) => ({
              ...t,
              steps: [...t.steps, { label: `tool ${String(data.tool)}`, tone: "accent" }],
            }));
          } else if (type === "tool.result") {
            patch((t) => ({
              ...t,
              steps: [...t.steps, { label: `evidence ${String(data.evidence_id)}`, tone: "ok" }],
            }));
          } else if (type === "chat.completed") {
            setThreadId(String(data.thread_id));
            patch((t) => ({
              ...t,
              answer: String(data.answer ?? ""),
              sources: (data.sources as Source[]) ?? [],
              citationValid: Boolean(data.citation_valid),
              invalid: (data.invalid_citations as string[]) ?? [],
            }));
            qc.invalidateQueries({ queryKey: ["copilot-threads"] });
          } else if (type === "chat.failed") {
            patch((t) => ({ ...t, failed: String(data.error ?? "error") }));
          }
        },
        controller.signal,
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      abort.current = null;
    }
  }

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Copilot</h1>
        <p className="mt-1 text-sm text-muted">
          Asks are answered from evidence the copilot gathers with read-only tools: policy search,
          the knowledge graph, SQL templates, invoices and audit lineage. Every sentence cites the
          evidence it used; an answer whose citations do not resolve is withheld, not shown.
        </p>
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Conversation</h2>
          <div className="flex items-center gap-2">
            {threads.data && threads.data.threads.length > 0 && (
              <select
                value={threadId ?? ""}
                onChange={(e) => {
                  setThreadId(e.target.value || null);
                  setTurns([]);
                }}
                className="min-h-10 rounded-lg border border-border bg-surface px-2 py-1 text-sm"
              >
                <option value="">New conversation</option>
                {threads.data.threads.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title || t.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            )}
            <Button
              variant="ghost"
              onClick={() => {
                setThreadId(null);
                setTurns([]);
              }}
            >
              Clear
            </Button>
          </div>
        </div>

        {threads.isPending && <Skeleton className="mt-3 h-8" />}

        <div className="mt-4 space-y-5">
          {turns.length === 0 && (
            <p className="text-sm text-muted">
              Try: &ldquo;Why is INV-1042 on hold?&rdquo;, &ldquo;Which vendors share a bank
              account?&rdquo; or &ldquo;What does policy say about missing purchase orders?&rdquo;
            </p>
          )}
          {turns.map((turn, i) => (
            <div key={i} className="space-y-2 border-t border-border pt-4 first:border-0 first:pt-0">
              <p className="font-medium">{turn.question}</p>
              {turn.steps.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {turn.steps.map((s, j) => (
                    <Badge key={j} tone={s.tone}>
                      {s.label}
                    </Badge>
                  ))}
                </div>
              )}
              {turn.failed && (
                <p className="text-sm text-danger">
                  The copilot failed with {turn.failed}. Nothing was answered.
                </p>
              )}
              {turn.answer && (
                <>
                  <div className="rounded-lg border border-border bg-surface-2 p-3 text-sm">
                    <SafeMarkdown>{turn.answer}</SafeMarkdown>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge tone={turn.citationValid ? "ok" : "danger"}>
                      {turn.citationValid ? "citations verified" : "citations unverified"}
                    </Badge>
                    {turn.invalid.length > 0 && (
                      <span className="text-danger">unresolved: {turn.invalid.join(", ")}</span>
                    )}
                  </div>
                  {turn.sources.length > 0 && (
                    <ul className="space-y-1 text-xs text-muted">
                      {turn.sources.map((s) => (
                        <li key={s.id}>
                          <code>[{s.id}]</code> {s.summary}
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
              {!turn.answer && !turn.failed && busy && i === turns.length - 1 && (
                <Skeleton className="h-16" />
              )}
            </div>
          ))}
        </div>

        <form
          className="mt-5 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            void ask();
          }}
        >
          <Textarea
            rows={3}
            value={question}
            maxLength={1000}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about invoices, policy, vendors or a decision…"
          />
          <div className="flex items-center gap-2">
            <Button type="submit" disabled={busy || question.trim().length < 3}>
              {busy ? "Thinking…" : "Ask"}
            </Button>
            {busy && (
              <Button variant="secondary" type="button" onClick={() => abort.current?.abort()}>
                Stop
              </Button>
            )}
          </div>
          <ErrorNote error={error} />
        </form>
      </Card>
    </div>
  );
}
