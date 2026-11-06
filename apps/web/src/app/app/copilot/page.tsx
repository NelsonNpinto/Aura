"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { SafeMarkdown } from "@/components/safe-markdown";
import { Badge, Button, Card, ErrorNote, Input, Label } from "@/components/ui";

export default function CopilotPage() {
  const [question, setQuestion] = useState("");
  const [caseId, setCaseId] = useState("");
  const cases = useQuery({
    queryKey: ["procurement"],
    queryFn: () =>
      api<{
        roles: string[];
        cases: { id: string; po_number: string; vendor_id: string }[];
      }>("/procurement/cases"),
  });
  const ask = useMutation({
    mutationFn: () =>
      api<{
        answer: string;
        citation_valid: boolean;
        source_only?: boolean;
        needs_more_evidence?: boolean;
        sources: { id: string; evidence: { filename?: string; heading?: string; text?: string } }[];
        llm?: { model: string; latency_ms: number };
      }>("/procurement/copilot/ask", {
        method: "POST",
        body: JSON.stringify({
          question,
          ...(caseId ? { case_id: caseId } : {}),
        }),
      }),
  });
  const result = ask.data;
  const hasSources = Boolean(result?.sources.length);
  const referencesChecked = hasSources && result?.citation_valid && !result.needs_more_evidence;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <h1 className="text-2xl font-semibold">Finance copilot</h1>
      <p className="text-sm text-muted">
        Ask about policy or a purchasing case. Answers use retrieved documents
        or the selected case’s current evidence. Approvals and payments are
        performed on the Purchasing page.
      </p>
      <Card>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            ask.mutate();
          }}
        >
          <Label>
            Evidence scope
            <select
              className="ml-2 rounded border border-border bg-surface px-3 py-2"
              value={caseId}
              onChange={(e) => {
                setCaseId(e.target.value);
                ask.reset();
              }}
            >
              <option value="">Policy knowledge base</option>
              {cases.data?.cases.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.po_number} · {c.vendor_id}
                </option>
              ))}
            </select>
          </Label>
          <Label>
            Question
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Why is this invoice waiting for review?"
              minLength={3}
              maxLength={500}
              required
            />
          </Label>
          <Button disabled={ask.isPending || !question}>
            {ask.isPending ? "Checking evidence…" : "Ask"}
          </Button>
        </form>
        <ErrorNote error={ask.error ?? cases.error} />
      </Card>
      {ask.data && (
        <Card className="space-y-3">
          <Badge tone={referencesChecked ? "ok" : "warn"}>
            {ask.data.source_only ? "Policy search results" : referencesChecked
              ? "Evidence references checked"
              : hasSources ? "More evidence needed" : "No matching evidence"}
          </Badge>
          <SafeMarkdown>{ask.data.answer}</SafeMarkdown>
          {!hasSources && !caseId && (
            <p className="text-sm text-muted">
              Check the indexed documents for this workspace in{" "}
              <Link className="text-accent underline" href="/app/knowledge">Knowledge</Link>.
            </p>
          )}
          {ask.data.llm && (
            <p className="text-xs text-muted">
              {ask.data.llm.model} · {ask.data.llm.latency_ms} ms
            </p>
          )}
          {ask.data.sources.map((s) => (
            <details key={s.id} open={ask.data.source_only || undefined}>
              <summary className="cursor-pointer">
                Source [{s.id}]{s.evidence.filename && ` · ${s.evidence.filename}`}
                {s.evidence.heading && ` · ${s.evidence.heading}`}
              </summary>
              <pre className="overflow-auto whitespace-pre-wrap text-xs">
                {ask.data.source_only ? s.evidence.text : JSON.stringify(s.evidence, null, 2)}
              </pre>
            </details>
          ))}
          {referencesChecked && !ask.data.source_only && <p className="text-xs text-muted">
            A valid reference identifies evidence; check whether it supports the
            answer.
          </p>}
        </Card>
      )}
    </div>
  );
}
