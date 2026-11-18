"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote, Input, Label, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type Memory = {
  id: string;
  kind: "vendor" | "user";
  subject_id: string;
  fact: string;
  status: "pending" | "active" | "retired";
  observations: number;
  confidence: number;
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
};

const STATUS_TONE: Record<Memory["status"], "ok" | "warn" | "neutral"> = {
  active: "ok",
  pending: "warn",
  retired: "neutral",
};

export default function MemoriesPage() {
  const qc = useQueryClient();
  const [kind, setKind] = useState<"vendor" | "user">("vendor");
  const [subject, setSubject] = useState("");
  const [fact, setFact] = useState("");

  const memories = useQuery({
    queryKey: ["memories"],
    queryFn: () => api<{ memories: Memory[]; ttl_days: number }>("/memory"),
  });

  const add = useMutation({
    mutationFn: () =>
      api<Memory>("/memory", {
        method: "POST",
        body: JSON.stringify({ kind, subject_id: subject, fact, confirmed: true }),
      }),
    onSuccess: () => {
      setFact("");
      qc.invalidateQueries({ queryKey: ["memories"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api<{ deleted: boolean }>(`/memory/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memories"] }),
  });

  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">What the agent remembers</h1>
        <p className="mt-1 text-sm text-muted">
          Long-term memories come only from human-confirmed corrections or from three consistent
          observations — never from document text. Each one shows its source, confidence and
          expiry, and you can delete any of them. Memories used in a run appear in that run&apos;s
          lineage.
        </p>
      </div>

      <Card>
        <h2 className="font-semibold">Add a confirmed note</h2>
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (subject.trim() && fact.trim()) add.mutate();
          }}
        >
          <div>
            <Label htmlFor="kind">About</Label>
            <select
              id="kind"
              value={kind}
              onChange={(e) => setKind(e.target.value as "vendor" | "user")}
              className="min-h-10 rounded-lg border border-border bg-surface px-2 py-2 text-sm"
            >
              <option value="vendor">Vendor</option>
              <option value="user">User</option>
            </select>
          </div>
          <div className="w-40">
            <Label htmlFor="subject">{kind === "vendor" ? "Vendor ID" : "User ID"}</Label>
            <Input id="subject" value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="V001" />
          </div>
          <div className="min-w-64 flex-1">
            <Label htmlFor="fact">Fact</Label>
            <Input
              id="fact"
              value={fact}
              onChange={(e) => setFact(e.target.value)}
              placeholder="Freight lines from this vendor are coded to 5020."
            />
          </div>
          <Button type="submit" disabled={add.isPending}>
            {add.isPending ? "Saving…" : "Remember"}
          </Button>
        </form>
        <ErrorNote error={add.error} />
      </Card>

      <Card>
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Stored memories</h2>
          {memories.data && (
            <span className="text-xs text-muted">Default TTL {memories.data.ttl_days} days</span>
          )}
        </div>
        {memories.isPending && <Skeleton className="mt-3 h-20" />}
        <ErrorNote error={memories.error} />
        {memories.data?.memories.length === 0 && (
          <p className="mt-3 text-sm text-muted">
            Nothing stored yet. Correct a GL code or a field on an invoice and the correction can
            be remembered for that vendor.
          </p>
        )}
        <ul className="mt-3 divide-y divide-border text-sm">
          {memories.data?.memories.map((m) => (
            <li key={m.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={STATUS_TONE[m.status]}>{m.status}</Badge>
                  <code className="text-xs">
                    {m.kind}:{m.subject_id}
                  </code>
                  <span className="text-xs text-muted">
                    confidence {m.confidence}% · seen {m.observations}×
                  </span>
                </div>
                <p className="mt-1">{m.fact}</p>
                <p className="mt-1 text-xs text-muted">
                  by {m.created_by} on {new Date(m.created_at).toLocaleDateString()}
                  {m.last_used_at
                    ? ` · last used ${new Date(m.last_used_at).toLocaleDateString()}`
                    : " · never used"}
                  {m.expires_at ? ` · expires ${new Date(m.expires_at).toLocaleDateString()}` : ""}
                </p>
              </div>
              <Button
                variant="secondary"
                onClick={() => remove.mutate(m.id)}
                disabled={remove.isPending}
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>
        <ErrorNote error={remove.error} />
      </Card>
    </div>
  );
}
