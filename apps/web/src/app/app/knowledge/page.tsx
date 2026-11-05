"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { SafeMarkdown } from "@/components/safe-markdown";
import { Badge, Button, Card, ErrorNote, Input, Label, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type Doc = { id: string; filename: string; doc_type: string; chunk_count: number; created_at: string; synthetic: boolean };
type Hit = { chunk_id: string; filename: string; heading: string; text: string; page: number | null; rrf: number;
  vector_rank: number | null; keyword_rank: number | null; rerank_score: number | null; n?: number };
type AskRes = { answer: string; sources: Hit[]; citations: { used: number[]; invalid: number[]; uncited: boolean; valid: boolean };
  llm: { model: string; latency_ms: number; tokens_in: number; tokens_out: number; fallback_reason: string | null; cache_hit: boolean } | null };

export default function KnowledgePage() {
  const qc = useQueryClient();
  const docs = useQuery({ queryKey: ["kb-docs"], queryFn: () => api<Doc[]>("/knowledge/documents") });
  const [query, setQuery] = useState("");
  const upload = useMutation({
    mutationFn: (fd: FormData) => api<{ document_id: string; duplicate: boolean; chunk_count: number }>("/knowledge/documents", { method: "POST", body: fd }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["kb-docs"] }),
  });
  const search = useMutation({
    mutationFn: (q: string) => api<{ hits: Hit[] }>("/knowledge/search", { method: "POST", body: JSON.stringify({ query: q }) }),
  });
  const ask = useMutation({
    mutationFn: (q: string) => api<AskRes>("/knowledge/ask", { method: "POST", body: JSON.stringify({ question: q }) }),
  });

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold">Knowledge base</h1>
      <Card>
        <h2 className="font-semibold">Upload a policy document</h2>
        <p className="mt-1 text-sm text-warn">Do not upload real documents. PDF (with a text layer), Markdown or text, up to 10 MB.</p>
        <form className="mt-3 flex flex-wrap items-end gap-3" action={(fd) => upload.mutate(fd)}>
          <div>
            <Label htmlFor="file">File</Label>
            <input id="file" name="file" type="file" required accept=".pdf,.md,.markdown,.txt" className="text-sm" />
          </div>
          <div>
            <Label htmlFor="doc_type">Type</Label>
            <select id="doc_type" name="doc_type" className="rounded-md border border-border bg-surface px-2 py-2 text-sm">
              {["policy", "approval_matrix", "tax_guide", "contract", "chart_of_accounts", "faq", "general"].map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <Button type="submit" disabled={upload.isPending}>{upload.isPending ? "Indexing…" : "Upload"}</Button>
        </form>
        <div className="mt-2"><ErrorNote error={upload.error} /></div>
        {upload.data && <p className="mt-2 text-sm text-ok">{upload.data.duplicate ? "Already indexed (same SHA-256)." : `Indexed ${upload.data.chunk_count} chunks.`}</p>}
      </Card>

      <Card>
        <h2 className="font-semibold">Documents</h2>
        {docs.isPending && <Skeleton className="mt-3 h-10" />}
        <ErrorNote error={docs.error} />
        {docs.data?.length === 0 && <p className="mt-2 text-sm text-muted">No documents yet. Upload a policy above to start.</p>}
        <ul className="mt-2 divide-y divide-border text-sm">
          {docs.data?.map((d) => (
            <li key={d.id} className="flex items-center justify-between py-2">
              <span>{d.filename} {d.synthetic && <Badge>synthetic</Badge>}</span>
              <span className="text-muted">{d.doc_type} · {d.chunk_count} chunks</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <h2 className="font-semibold">Search and ask</h2>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (query.trim().length > 2) search.mutate(query); }}>
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. who approves a bank detail change?" maxLength={500} aria-label="Question" />
          <Button type="submit" variant="secondary" disabled={search.isPending}>Search</Button>
          <Button type="button" disabled={ask.isPending || query.trim().length < 3} onClick={() => ask.mutate(query)}>Ask</Button>
        </form>
        <div className="mt-2 space-y-2"><ErrorNote error={search.error} /><ErrorNote error={ask.error} /></div>
        {ask.data && (
          <div className="mt-4 rounded-md border border-border p-4">
            <div className="mb-2 flex flex-wrap gap-2">
              <Badge tone={ask.data.citations.valid ? "ok" : "danger"}>
                {ask.data.citations.valid ? "citations valid" : ask.data.citations.invalid.length ? `invalid citations: ${ask.data.citations.invalid.join(", ")}` : "uncited answer"}
              </Badge>
              {ask.data.llm && <Badge>{ask.data.llm.model} · {ask.data.llm.latency_ms} ms</Badge>}
              {ask.data.llm?.fallback_reason && <Badge tone="warn">fallback: {ask.data.llm.fallback_reason}</Badge>}
              {ask.data.llm?.cache_hit && <Badge tone="accent">cache hit</Badge>}
            </div>
            <SafeMarkdown>{ask.data.answer}</SafeMarkdown>
            <ol className="mt-3 space-y-2 text-xs text-muted">
              {ask.data.sources.map((s) => (
                <li key={s.chunk_id}><strong>[{s.n}]</strong> {s.filename}{s.heading ? ` — ${s.heading}` : ""}{s.page ? `, p.${s.page}` : ""}</li>
              ))}
            </ol>
            <p className="mt-2 text-xs text-muted">A citation is a pointer to evidence, not proof. Check the source.</p>
          </div>
        )}
        {search.data && (
          <ul className="mt-4 space-y-3">
            {search.data.hits.length === 0 && <li className="text-sm text-muted">No matches.</li>}
            {search.data.hits.map((h, i) => (
              <li key={h.chunk_id} className="rounded-md border border-border p-3 text-sm">
                <div className="mb-1 flex flex-wrap gap-2 text-xs text-muted">
                  <span>#{i + 1} {h.filename}{h.heading ? ` — ${h.heading}` : ""}</span>
                  <span>vector rank {h.vector_rank ?? "–"} · keyword rank {h.keyword_rank ?? "–"} · rerank {h.rerank_score?.toFixed(2) ?? "–"}</span>
                </div>
                <p className="whitespace-pre-wrap">{h.text.slice(0, 600)}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
