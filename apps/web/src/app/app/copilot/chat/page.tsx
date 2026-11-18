"use client";

import { ArrowLeft, LoaderCircle, Plus, Send, Square } from "lucide-react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { SafeMarkdown } from "@/components/safe-markdown";
import {
  Button,
  Card,
  ErrorNote,
  Label,
  Skeleton,
  Textarea,
} from "@/components/ui";
import { api, streamEvents } from "@/lib/api";

type Thread = { id: string; title: string };
type Source = { id: string; summary: string };
type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Source[];
  llm?: { citation_valid?: boolean };
};
type Transcript = { id: string; messages: Message[] };

const toolStatus: Record<string, string> = {
  search_policies: "Looking up policy passages",
  sql_query: "Checking finance records",
  graph_query: "Checking vendor relationships",
  list_invoices: "Finding invoices",
  get_invoice: "Reading invoice details",
  explain_decision: "Reading decision history",
};

function ChatMessage({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="ml-auto max-w-[90%] rounded-xl bg-accent/10 px-4 py-3 text-sm whitespace-pre-wrap">
        {message.content}
      </div>
    );
  }
  return (
    <article className="workspace-enter mr-auto w-full rounded-xl border border-border bg-surface-2 p-4">
      <SafeMarkdown>{message.content}</SafeMarkdown>
      {message.citations &&
        message.citations.length > 0 &&
        message.llm?.citation_valid !== false && (
          <details className="mt-3 border-t border-border pt-2 text-sm">
            <summary className="cursor-pointer font-medium">
              Evidence ({message.citations.length})
            </summary>
            <ul className="mt-2 space-y-1 text-muted">
              {message.citations.map((source) => (
                <li key={source.id}>
                  [{source.id}] {source.summary}
                </li>
              ))}
            </ul>
          </details>
        )}
    </article>
  );
}

export default function CopilotChatPage() {
  const qc = useQueryClient();
  const [threadId, setThreadId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [turn, setTurn] = useState<Message | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState<unknown>(null);
  const abort = useRef<AbortController | null>(null);
  const threadListKey = ["copilot-threads"] as const;
  const threads = useQuery({
    queryKey: threadListKey,
    queryFn: ({ signal }) =>
      api<{ threads: Thread[] }>("/copilot/threads", { signal }),
  });
  const transcript = useQuery({
    queryKey: ["copilot-thread", threadId],
    queryFn: ({ signal }) =>
      api<Transcript>(`/copilot/threads/${threadId}`, { signal }),
    enabled: threadId !== null,
  });

  useEffect(() => () => abort.current?.abort(), []);

  function selectThread(id: string | null) {
    setThreadId(id);
    setQuestion("");
    setError(null);
    setStatus("");
  }

  async function ask() {
    const text = question.trim();
    if (text.length < 3 || abort.current || (threadId && !transcript.data))
      return;
    const controller = new AbortController();
    abort.current = controller;
    const user: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    setQuestion("");
    setTurn(user);
    setError(null);
    setStatus("Checking workspace evidence");
    let complete = false;
    try {
      await streamEvents(
        "/copilot/chat",
        {
          method: "POST",
          body: JSON.stringify({ question: text, thread_id: threadId }),
        },
        (type, data) => {
          if (type === "tool.called") {
            setStatus(toolStatus[String(data.tool)] ?? "Gathering evidence");
          } else if (type === "tool.result") {
            setStatus("Reviewing the evidence");
          } else if (type === "chat.failed") {
            throw new Error(
              String(data.error ?? "Copilot could not complete this answer."),
            );
          } else if (type === "chat.completed") {
            const id = String(data.thread_id);
            const assistant: Message = {
              id: crypto.randomUUID(),
              role: "assistant",
              content: String(data.answer ?? ""),
              citations: (data.sources as Source[]) ?? [],
              llm: { citation_valid: Boolean(data.citation_valid) },
            };
            qc.setQueryData<Transcript>(["copilot-thread", id], {
              id,
              messages: [...(transcript.data?.messages ?? []), user, assistant],
            });
            qc.setQueryData<{ threads: Thread[] }>(
              threadListKey,
              (previous) => ({
                threads: [
                  previous?.threads.find((item) => item.id === id) ?? {
                    id,
                    title: text.slice(0, 80),
                  },
                  ...(previous?.threads.filter((item) => item.id !== id) ?? []),
                ],
              }),
            );
            setThreadId(id);
            setTurn(null);
            complete = true;
            void qc.invalidateQueries({ queryKey: threadListKey });
            void qc.invalidateQueries({ queryKey: ["copilot-thread", id] });
          }
        },
        controller.signal,
      );
      if (!complete)
        throw new Error(
          "The response was interrupted. Send your question again.",
        );
    } catch (err) {
      if (!complete) {
        setQuestion(text);
        if (!controller.signal.aborted) setError(err);
        else setStatus("Response stopped.");
      }
    } finally {
      setTurn(null);
      if (!controller.signal.aborted) setStatus("");
      abort.current = null;
    }
  }

  const loading = threadId !== null && transcript.isPending;
  const messages = transcript.data?.messages ?? [];
  const busy = turn !== null;
  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header>
        <Link
          className="mb-3 inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
          href="/app/copilot"
        >
          <ArrowLeft className="size-4" aria-hidden /> Finance Copilot
        </Link>
        <h1 className="font-semibold">Workspace chat</h1>
        <p className="mt-2 text-sm text-muted">
          Ask about invoices, policies, supplier relationships, or a past
          decision.
        </p>
      </header>
      <Card className="space-y-4">
        <div className="flex flex-wrap items-end gap-3 border-b border-border pb-4">
          <div className="grow">
            <Label htmlFor="copilot-conversation">Conversation</Label>
            <select
              id="copilot-conversation"
              value={threadId ?? ""}
              disabled={busy || threads.isPending}
              onChange={(event) => selectThread(event.target.value || null)}
              className="mt-1 block min-h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm"
            >
              <option value="">
                {threads.isPending
                  ? "Loading conversations…"
                  : "New conversation"}
              </option>
              {threads.data?.threads.map((thread) => (
                <option key={thread.id} value={thread.id}>
                  {thread.title}
                </option>
              ))}
            </select>
          </div>
          <Button
            variant="secondary"
            disabled={busy || threadId === null}
            onClick={() => selectThread(null)}
          >
            <Plus className="size-4" aria-hidden /> New chat
          </Button>
        </div>
        {threads.error && (
          <div className="space-y-2">
            <ErrorNote error={threads.error} />
            <Button variant="secondary" onClick={() => void threads.refetch()}>
              Retry conversations
            </Button>
          </div>
        )}
        {loading && (
          <div
            role="status"
            aria-label="Loading messages"
            className="space-y-3"
          >
            <Skeleton className="ml-auto h-10 w-2/5" />
            <Skeleton className="h-20 w-4/5" />
          </div>
        )}
        {transcript.error && (
          <div className="space-y-2">
            <ErrorNote error={transcript.error} />
            <Button
              variant="secondary"
              onClick={() => void transcript.refetch()}
            >
              Reload messages
            </Button>
          </div>
        )}
        <div
          className="space-y-3"
          role="log"
          aria-label="Conversation messages"
        >
          {messages.map((message) => (
            <ChatMessage key={message.id} message={message} />
          ))}
          {turn && <ChatMessage message={turn} />}
        </div>
        {status && (
          <p
            className="flex items-center gap-2 text-sm text-muted"
            role="status"
          >
            {busy && (
              <LoaderCircle
                className="size-4 motion-safe:animate-spin"
                aria-hidden
              />
            )}
            {status}
            {busy ? "…" : ""}
          </p>
        )}
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            void ask();
          }}
        >
          <Label htmlFor="workspace-question">Question</Label>
          <Textarea
            id="workspace-question"
            rows={3}
            value={question}
            disabled={busy}
            maxLength={1000}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Which invoices are waiting for review?"
          />
          <div className="flex items-center gap-2">
            <Button
              type="submit"
              disabled={
                busy ||
                loading ||
                Boolean(transcript.error) ||
                question.trim().length < 3
              }
            >
              <Send className="size-4" aria-hidden /> Send
            </Button>
            {busy && (
              <Button
                variant="secondary"
                type="button"
                onClick={() => abort.current?.abort()}
              >
                <Square className="size-4" aria-hidden /> Stop
              </Button>
            )}
          </div>
          <ErrorNote error={error} />
        </form>
      </Card>
    </div>
  );
}
