"use client";

import {
  ArrowRight,
  BookOpen,
  FileCheck2,
  LoaderCircle,
  MessageSquare,
  Send,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { caseStages, documentNames, purchasingCases } from "@/lib/purchasing";
import { SafeMarkdown } from "@/components/safe-markdown";
import {
  Button,
  Card,
  ErrorNote,
  Label,
  Skeleton,
  Textarea,
} from "@/components/ui";

type Topic = "status" | "match" | "payment";
type Source = { id: string; evidence: Record<string, unknown> };
type Answer = {
  answer: string;
  citation_valid: boolean;
  source_only?: boolean;
  fallback?: boolean;
  response_mode?: "case_snapshot";
  sources: Source[];
  snapshot?: Answer;
};

const topics: { id: Topic; label: string; question: string }[] = [
  {
    id: "status",
    label: "Current status",
    question: "What is the current case status?",
  },
  {
    id: "match",
    label: "Document match",
    question: "Do the purchasing documents match?",
  },
  { id: "payment", label: "Payment", question: "Has payment been recorded?" },
];

const sourceNames: Record<string, string> = {
  ...documentNames,
  status: "Case status",
  comparison: "Document comparison",
  correction: "Reviewer note",
  approvals: "Approval history",
  payment: "Payment record",
};

function AnswerCard({ result }: { result: Answer }) {
  const title = result.source_only
    ? "Matching policy passages"
    : result.response_mode === "case_snapshot"
      ? "Case evidence"
      : "Answer";
  return (
    <Card className="workspace-enter space-y-4" aria-live="polite">
      <h2 className="flex items-center gap-2 font-semibold">
        <FileCheck2 className="size-5 text-accent" aria-hidden />
        {title}
      </h2>
      {result.fallback && (
        <p className="text-sm text-muted">
          An AI answer wasn’t available. Here’s the current case status.
        </p>
      )}
      <SafeMarkdown>{result.answer}</SafeMarkdown>
      {result.sources.length > 0 && (
        <div className="space-y-2 border-t border-border pt-3">
          <h3 className="text-sm font-semibold">Sources</h3>
          {result.sources.map(({ id, evidence }) => {
            const filename =
              typeof evidence.filename === "string" ? evidence.filename : null;
            const heading =
              typeof evidence.heading === "string" ? evidence.heading : null;
            const content =
              typeof evidence.text === "string"
                ? evidence.text
                : typeof evidence.comment === "string" && id === "correction"
                  ? evidence.comment
                  : JSON.stringify(evidence, null, 2);
            return (
              <details
                className="rounded-lg border border-border bg-surface-2 px-3 py-2"
                key={id}
                open={result.source_only || undefined}
              >
                <summary className="cursor-pointer text-sm font-medium">
                  [{id}] {filename ?? sourceNames[id] ?? "Evidence"}
                  {heading && ` · ${heading}`}
                </summary>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-muted">
                  {content}
                </p>
              </details>
            );
          })}
        </div>
      )}
    </Card>
  );
}

export default function CopilotPage() {
  return (
    <Suspense fallback={<Skeleton className="h-56" />}>
      <FinanceCopilot />
    </Suspense>
  );
}

function FinanceCopilot() {
  const router = useRouter();
  const params = useSearchParams();
  const cases = useQuery(purchasingCases);
  const isVendor = cases.data?.roles.includes("vendor");
  const caseId =
    params.get("case") || (isVendor ? cases.data?.cases[0]?.id : "") || "";
  const selected = cases.data?.cases.find((item) => item.id === caseId);
  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <header className="workspace-hero flex flex-wrap items-start justify-between gap-4 rounded-2xl p-5 sm:p-7">
        <div>
          <h1 className="font-semibold">Finance Copilot</h1>
          <p className="mt-2 max-w-xl text-sm text-blue-100/90">
            Ask about a purchasing case or look up a finance policy.
          </p>
        </div>
        {cases.data && !isVendor && (
          <Link
            href="/app/copilot/chat"
            className="inline-flex items-center gap-2 rounded-lg border border-white/25 px-3 py-2 text-sm font-medium transition hover:bg-white/10"
          >
            <MessageSquare className="size-4" aria-hidden /> Workspace chat{" "}
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        )}
      </header>
      <Card>
        <Label htmlFor="copilot-scope">Evidence scope</Label>
        <select
          id="copilot-scope"
          className="min-h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm"
          value={caseId}
          disabled={cases.isPending || cases.isError}
          onChange={(event) =>
            router.replace(
              event.target.value
                ? `?case=${encodeURIComponent(event.target.value)}`
                : "/app/copilot",
              { scroll: false },
            )
          }
        >
          {!isVendor && (
            <option value="">
              {cases.isPending
                ? "Loading evidence scopes…"
                : "Policy knowledge base"}
            </option>
          )}
          {isVendor && !caseId && <option value="">No assigned cases</option>}
          {caseId && !selected && (
            <option value={caseId}>Linked purchasing case</option>
          )}
          {cases.data?.cases.map((item) => (
            <option key={item.id} value={item.id}>
              {item.po_number} · {item.vendor_id}
            </option>
          ))}
        </select>
        {selected && (
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
            <span>{caseStages[selected.status]}</span>
            <Link
              className="text-accent underline"
              href={`/app/procurement?case=${caseId}`}
            >
              Open purchasing case
            </Link>
          </div>
        )}
        {cases.error && (
          <div className="mt-3 space-y-2">
            <ErrorNote error={cases.error} />
            <Button variant="secondary" onClick={() => void cases.refetch()}>
              Retry
            </Button>
          </div>
        )}
      </Card>
      {!cases.isError && (
        <AskPanel
          key={caseId}
          caseId={caseId}
          disabled={cases.isPending || Boolean(isVendor && !caseId)}
        />
      )}
    </div>
  );
}

function AskPanel({ caseId, disabled }: { caseId: string; disabled: boolean }) {
  const [question, setQuestion] = useState("");
  const ask = useMutation({
    mutationFn: ({ question, topic }: { question: string; topic?: Topic }) =>
      api<Answer>("/procurement/copilot/ask", {
        method: "POST",
        body: JSON.stringify({
          question,
          case_id: caseId || undefined,
          case_topic: topic,
        }),
      }),
  });
  return (
    <>
      <Card>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (question.trim().length >= 3 && !disabled && !ask.isPending)
              ask.mutate({ question: question.trim() });
          }}
        >
          <Label htmlFor="copilot-question">Question</Label>
          <Textarea
            id="copilot-question"
            rows={3}
            maxLength={500}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={
              caseId
                ? "Why is this invoice waiting for review?"
                : "Who reviews changes to a supplier’s bank details?"
            }
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="submit"
              disabled={disabled || ask.isPending || question.trim().length < 3}
            >
              <Send className="size-4" aria-hidden /> Ask Copilot
            </Button>
            {caseId &&
              topics.map((topic) => (
                <Button
                  key={topic.id}
                  variant="secondary"
                  type="button"
                  disabled={disabled || ask.isPending}
                  onClick={() =>
                    ask.mutate({ question: topic.question, topic: topic.id })
                  }
                >
                  {topic.label}
                </Button>
              ))}
          </div>
          <ErrorNote error={ask.error} />
        </form>
      </Card>
      {ask.isPending && (
        <Card role="status" className="workspace-enter space-y-3">
          <p className="flex items-center gap-2 text-sm text-muted">
            <LoaderCircle
              className="size-4 motion-safe:animate-spin"
              aria-hidden
            />{" "}
            Checking evidence…
          </p>
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </Card>
      )}
      {ask.data && <AnswerCard result={ask.data} />}
      {ask.data?.snapshot && <AnswerCard result={ask.data.snapshot} />}
      {ask.data && !caseId && !ask.data.sources.length && (
        <Link
          className="inline-flex items-center gap-2 text-sm text-accent underline"
          href="/app/knowledge"
        >
          <BookOpen className="size-4" aria-hidden /> View indexed documents
        </Link>
      )}
    </>
  );
}
