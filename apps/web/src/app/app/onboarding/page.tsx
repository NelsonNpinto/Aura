"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote, Input, Label, Skeleton, Textarea } from "@/components/ui";
import { api } from "@/lib/api";

type Finding = { code: string; severity: string; message: string; evidence: Record<string, unknown> };
type Assessment = { route: string; score: number; required_role: string | null; findings: Finding[] };
type Case = {
  id: string;
  vendor_name: string;
  status: string;
  created_by: string;
  created_at: string;
  assessment: Assessment | null;
  documents: Record<string, boolean>;
  tax_id_last4: string | null;
  bank_last4: string | null;
  decisions: { decision: string; by: string; comment: string }[];
  guardrails: { check: string; verdict: string; detail: string }[] | null;
};

const DOCS = ["registration_certificate", "tax_certificate", "bank_proof"];
const STATUS_TONE: Record<string, "ok" | "warn" | "danger" | "neutral"> = {
  approved: "ok",
  auto_approved: "ok",
  awaiting_approval: "warn",
  rejected: "danger",
  blocked: "danger",
};

export default function OnboardingPage() {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    legal_name: "",
    tax_id: "",
    tax_scheme: "US_EIN",
    routing: "",
    account_number: "",
    verified: false,
    notes: "",
    documents: Object.fromEntries(DOCS.map((d) => [d, false])) as Record<string, boolean>,
  });
  const [comment, setComment] = useState("");

  const cases = useQuery({ queryKey: ["onboarding"], queryFn: () => api<{ cases: Case[] }>("/onboarding/cases") });

  const create = useMutation({
    mutationFn: () =>
      api<Case>("/onboarding/cases", {
        method: "POST",
        body: JSON.stringify({
          legal_name: form.legal_name,
          tax_id: form.tax_id,
          tax_scheme: form.tax_scheme,
          documents: Object.fromEntries(
            Object.entries(form.documents).filter(([, v]) => v).map(([k]) => [k, "provided"]),
          ),
          bank: {
            routing: form.routing,
            account_number: form.account_number,
            verified_by_callback: form.verified,
          },
          notes: form.notes,
        }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["onboarding"] }),
  });

  const decide = useMutation({
    mutationFn: (args: { id: string; decision: "approve" | "reject" }) =>
      api(`/onboarding/cases/${args.id}/decide`, {
        method: "POST",
        body: JSON.stringify({ decision: args.decision, comment: comment || "Reviewed" }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["onboarding"] }),
  });

  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Vendor onboarding</h1>
        <p className="mt-1 text-sm text-muted">
          A second workflow on the same platform: the same guardrails, audit chain and approval
          rules, with its own deterministic checks (KYC documents, tax identifier format, a
          screening list, bank verification and duplicate detection). Synthetic data only; never
          enter real vendor details.
        </p>
      </div>

      <Card>
        <h2 className="font-semibold">New vendor</h2>
        <form
          className="mt-3 grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (form.legal_name.trim()) create.mutate();
          }}
        >
          <div>
            <Label htmlFor="legal_name">Legal name</Label>
            <Input
              id="legal_name"
              value={form.legal_name}
              onChange={(e) => setForm({ ...form, legal_name: e.target.value })}
              placeholder="Harbour Components Ltd"
            />
          </div>
          <div>
            <Label htmlFor="tax_id">Tax identifier</Label>
            <Input
              id="tax_id"
              value={form.tax_id}
              onChange={(e) => setForm({ ...form, tax_id: e.target.value })}
              placeholder="84-1739204"
            />
          </div>
          <div>
            <Label htmlFor="tax_scheme">Scheme</Label>
            <select
              id="tax_scheme"
              value={form.tax_scheme}
              onChange={(e) => setForm({ ...form, tax_scheme: e.target.value })}
              className="min-h-10 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            >
              {["US_EIN", "IN_GSTIN", "IN_PAN", "EU_VAT"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="routing">Bank routing</Label>
            <Input
              id="routing"
              value={form.routing}
              onChange={(e) => setForm({ ...form, routing: e.target.value })}
              placeholder="021000021"
            />
          </div>
          <div>
            <Label htmlFor="account">Account number</Label>
            <Input
              id="account"
              value={form.account_number}
              onChange={(e) => setForm({ ...form, account_number: e.target.value })}
              placeholder="4455667788"
            />
            <p className="mt-1 text-xs text-muted">Only a hash and the last four digits are stored.</p>
          </div>
          <div className="sm:col-span-2">
            <Label>Documents received</Label>
            <div className="flex flex-wrap gap-4">
              {DOCS.map((d) => (
                <label key={d} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.documents[d]}
                    onChange={(e) =>
                      setForm({ ...form, documents: { ...form.documents, [d]: e.target.checked } })
                    }
                  />
                  {d.replace(/_/g, " ")}
                </label>
              ))}
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.verified}
                  onChange={(e) => setForm({ ...form, verified: e.target.checked })}
                />
                bank verified by call-back
              </label>
            </div>
          </div>
          <div className="sm:col-span-2">
            <Label htmlFor="notes">Notes</Label>
            <Textarea
              id="notes"
              rows={2}
              value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
            />
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Assessing…" : "Assess and submit"}
            </Button>
          </div>
        </form>
        <ErrorNote error={create.error} />
      </Card>

      <Card>
        <h2 className="font-semibold">Cases</h2>
        {cases.isPending && <Skeleton className="mt-3 h-20" />}
        <ErrorNote error={cases.error} />
        {cases.data?.cases.length === 0 && (
          <p className="mt-2 text-sm text-muted">No onboarding cases yet.</p>
        )}
        <div className="mt-3">
          <Label htmlFor="comment">Decision comment</Label>
          <Input id="comment" value={comment} onChange={(e) => setComment(e.target.value)} />
        </div>
        <ul className="mt-3 divide-y divide-border text-sm">
          {cases.data?.cases.map((c) => (
            <li key={c.id} className="py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <Badge tone={STATUS_TONE[c.status] ?? "neutral"}>{c.status.replace(/_/g, " ")}</Badge>
                    <strong>{c.vendor_name}</strong>
                    {c.assessment && <span className="text-xs text-muted">risk {c.assessment.score}</span>}
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    by {c.created_by} · bank ••{c.bank_last4 ?? "—"} · tax ••{c.tax_id_last4 ?? "—"}
                    {c.assessment?.required_role ? ` · needs ${c.assessment.required_role}` : ""}
                  </p>
                </div>
                {c.status === "awaiting_approval" && (
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      onClick={() => decide.mutate({ id: c.id, decision: "reject" })}
                      disabled={decide.isPending}
                    >
                      Reject
                    </Button>
                    <Button
                      onClick={() => decide.mutate({ id: c.id, decision: "approve" })}
                      disabled={decide.isPending}
                    >
                      Approve
                    </Button>
                  </div>
                )}
              </div>
              {c.assessment && c.assessment.findings.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {c.assessment.findings.map((f) => (
                    <li key={f.code} className="text-xs">
                      <Badge tone={f.severity === "HIGH" ? "danger" : "warn"}>{f.severity}</Badge>{" "}
                      <code>{f.code}</code> — {f.message}
                    </li>
                  ))}
                </ul>
              )}
              {c.decisions.length > 0 && (
                <p className="mt-2 text-xs text-muted">
                  {c.decisions.map((d) => `${d.decision} by ${d.by}: ${d.comment}`).join(" · ")}
                </p>
              )}
            </li>
          ))}
        </ul>
        <ErrorNote error={decide.error} />
      </Card>
    </div>
  );
}
