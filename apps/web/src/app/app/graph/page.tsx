"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge, Button, Card, ErrorNote, Input, Label, Metric, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type Finding = { code: string; severity: string; message: string; evidence: Record<string, unknown> };
type Neighborhood = {
  status: "ok" | "unavailable" | "static";
  reason: string;
  note?: string;
  vendor: Record<string, unknown> | null;
  findings: Finding[];
};
type Patterns = {
  status: "ok" | "unavailable" | "static";
  reason: string;
  note?: string;
  patterns: Record<string, Record<string, unknown>[]>;
};
type Status = { configured: boolean; reason: string; templates: { name: string; description: string; params: string[] }[] };

const PATTERN_LABELS: Record<string, string> = {
  shared_bank_accounts: "Bank accounts shared by two or more vendors",
  employee_vendor_conflicts: "Employees sharing a bank account with a vendor",
  new_vendor_fast_approval: "First invoice approved by the vendor's creator",
  duplicate_across_aliases: "Same invoice number across vendor aliases",
};

function Unavailable({ reason }: { reason: string }) {
  return (
    <div className="rounded-lg border border-warn/40 bg-warn/10 p-4 text-sm">
      <p className="font-semibold">Knowledge graph unavailable</p>
      <p className="mt-1 text-muted">
        Reason: <code>{reason}</code>. AuraDB Free pauses when idle. Relationship checks that
        cannot run raise a MEDIUM flag and send the invoice to human review — they never report a
        silent pass.
      </p>
    </div>
  );
}

function StaticSnapshot({ note }: { note?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface-2 p-3 text-sm">
      <Badge tone="warn">Static snapshot</Badge>
      <p className="mt-1 text-muted">
        {note ?? "Showing the synthetic demo data while the live knowledge graph is offline."}{" "}
        Invoice relationship checks still route to human review until the graph is back.
      </p>
    </div>
  );
}

function severityTone(severity: string) {
  return severity === "HIGH" ? "danger" : severity === "MEDIUM" ? "warn" : "neutral";
}

export default function GraphPage() {
  const [vendorId, setVendorId] = useState("");
  const status = useQuery({ queryKey: ["graph-status"], queryFn: () => api<Status>("/graph/status") });
  const patterns = useQuery({ queryKey: ["graph-patterns"], queryFn: () => api<Patterns>("/graph/patterns") });
  const vendor = useMutation({
    mutationFn: (id: string) => api<Neighborhood>(`/graph/vendor/${encodeURIComponent(id)}`),
  });

  const unavailable = status.data && !status.data.configured;

  return (
    <div className="w-full space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Knowledge graph</h1>
        <p className="mt-1 text-sm text-muted">
          Vendors, bank accounts, employees, orders and decisions. Tenant data is read through
          parameterised templates only; generated Cypher runs read-only against the synthetic demo
          workspace and every query is logged.
        </p>
      </div>

      {status.isPending && <Skeleton className="h-16" />}
      <ErrorNote error={status.error} />
      {unavailable && patterns.data?.status !== "static" && <Unavailable reason={status.data!.reason} />}
      {unavailable && patterns.data?.status === "static" && <StaticSnapshot note={patterns.data.note} />}

      <Card>
        <h2 className="font-semibold">Vendor neighbourhood</h2>
        <form
          className="mt-3 flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (vendorId.trim()) vendor.mutate(vendorId.trim());
          }}
        >
          <div className="w-56">
            <Label htmlFor="vendor">Vendor ID</Label>
            <Input id="vendor" value={vendorId} placeholder="V001" onChange={(e) => setVendorId(e.target.value)} />
          </div>
          <Button type="submit" disabled={vendor.isPending || !vendorId.trim()}>
            {vendor.isPending ? "Loading…" : "Explore"}
          </Button>
        </form>
        <ErrorNote error={vendor.error} />

        {vendor.data?.status === "unavailable" && (
          <div className="mt-4">
            <Unavailable reason={vendor.data.reason} />
          </div>
        )}

        {vendor.data?.status === "static" && (
          <div className="mt-4">
            <StaticSnapshot note={vendor.data.note} />
          </div>
        )}
        {(vendor.data?.status === "ok" || vendor.data?.status === "static") && (
          <div className="mt-4 space-y-4">
            {!vendor.data.vendor && (
              <p className="text-sm text-muted">
                No vendor with that ID is in the graph yet. The projection runs through the outbox;
                try the sync on the admin page.
              </p>
            )}
            {vendor.data.vendor && (
              <pre className="overflow-x-auto rounded-lg bg-surface-2 p-3 text-xs">
                {JSON.stringify(vendor.data.vendor, null, 2)}
              </pre>
            )}
            <div>
              <h3 className="text-sm font-semibold">Relationship findings</h3>
              {vendor.data.findings.length === 0 ? (
                <p className="mt-1 text-sm text-muted">No fraud patterns matched for this vendor.</p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {vendor.data.findings.map((f) => (
                    <li key={f.code} className="rounded-lg border border-border p-3 text-sm">
                      <div className="flex items-center gap-2">
                        <Badge tone={severityTone(f.severity)}>{f.severity}</Badge>
                        <code className="text-xs">{f.code}</code>
                      </div>
                      <p className="mt-1">{f.message}</p>
                      <pre className="mt-2 overflow-x-auto text-xs text-muted">
                        {JSON.stringify(f.evidence, null, 2)}
                      </pre>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">Fraud patterns across the workspace</h2>
        {patterns.isPending && <Skeleton className="mt-3 h-20" />}
        <ErrorNote error={patterns.error} />
        {patterns.data?.status === "unavailable" && (
          <div className="mt-3">
            <Unavailable reason={patterns.data.reason} />
          </div>
        )}
        {(patterns.data?.status === "ok" || patterns.data?.status === "static") && (
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {Object.entries(patterns.data.patterns).map(([key, rows]) => (
              <div key={key} className="rounded-lg border border-border p-3">
                <Metric
                  label={PATTERN_LABELS[key] ?? key}
                  value={rows.length}
                  source={patterns.data?.status === "static" ? "static snapshot (synthetic world data)" : "Neo4j query template"}
                />
                {rows.length > 0 && (
                  <pre className="mt-2 max-h-40 overflow-auto text-xs text-muted">
                    {JSON.stringify(rows.slice(0, 3), null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">Query templates</h2>
        <p className="mt-1 text-sm text-muted">
          These are the only paths to tenant data. Parameters are bound, never interpolated.
        </p>
        <ul className="mt-3 divide-y divide-border text-sm">
          {status.data?.templates.map((t) => (
            <li key={t.name} className="py-2">
              <code className="text-xs font-semibold">{t.name}</code>
              <span className="ml-2 text-muted">{t.description}</span>
              {t.params.length > 0 && (
                <span className="ml-2 text-xs text-muted">params: {t.params.join(", ")}</span>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
