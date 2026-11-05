"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiToken, clearApiToken, money } from "@/lib/api";
import { authClient } from "@/lib/auth-client";
import { Badge, Button, Card, ErrorNote, Input, Label } from "@/components/ui";

type Line = {
  sku: string;
  description: string;
  quantity: string;
  unit_price_minor: number;
};
type Doc = {
  number: string;
  po_number: string;
  currency: string;
  lines: Line[];
  tax_minor: number;
  total_minor: number;
  source_document_id?: string | null;
};
type Case = {
  id: string;
  vendor_id: string;
  po_number: string;
  state: {
    status: string;
    revision: number;
    documents: Partial<Record<string, Doc>>;
    comparison?: {
      matched: boolean;
      missing: string[];
      findings: Record<string, string>[];
    };
    approvals: { actor: string; stage: string; comment: string }[];
    payment?: { reference: string; date: string; amount_minor: number };
    notification?: {
      status: string;
      notice?: string;
      body?: string;
      error?: string;
    };
  };
};
const selectClass = "rounded border border-border bg-surface px-3 py-2 text-sm";

function DocumentForm({
  item,
  kind,
  refresh,
}: {
  item: Case;
  kind: string;
  refresh: () => void;
}) {
  const initial = item.state.documents[kind];
  const [number, setNumber] = useState(initial?.number ?? "");
  const [currency, setCurrency] = useState(initial?.currency ?? "INR");
  const [lines, setLines] = useState<Line[]>(
    initial?.lines ?? [
      { sku: "", description: "", quantity: "1", unit_price_minor: 0 },
    ],
  );
  const [tax, setTax] = useState(initial?.tax_minor ?? 0);
  const [source, setSource] = useState(initial?.source_document_id ?? null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const total =
    lines.reduce((n, l) => n + Number(l.quantity) * l.unit_price_minor, 0) +
    tax;
  async function extract(file: File) {
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("synthetic_confirmed", "true");
      const res = await api<{ draft: Doc }>(
        `/procurement/cases/${item.id}/extract/${kind}`,
        { method: "POST", body },
      );
      setNumber(res.draft.number);
      setCurrency(res.draft.currency);
      setLines(res.draft.lines);
      setTax(res.draft.tax_minor);
      setSource(res.draft.source_document_id ?? null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api(`/procurement/cases/${item.id}/documents/${kind}`, {
        method: "PUT",
        body: JSON.stringify({
          number,
          po_number: item.po_number,
          currency,
          lines,
          tax_minor: tax,
          total_minor: total,
          source_document_id: source,
        }),
      });
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="rounded border border-border p-3">
      <summary className="cursor-pointer font-medium">
        {kind === "po"
          ? "Purchase order"
          : kind === "receipt"
            ? "Goods receipt"
            : "Vendor invoice"}{" "}
        · {initial ? "confirmed" : "required"}
      </summary>
      <div className="mt-3 space-y-3">
        <Label>
          Extract a synthetic PDF or image, then review every field
          <input
            type="file"
            accept=".pdf,.png,.jpg,.jpeg"
            disabled={busy}
            className="mt-2 block text-sm"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void extract(f);
            }}
          />
        </Label>
        <p className="text-xs text-muted">
          Only synthetic demo documents are allowed. Scans need vision
          extraction. You can also enter the document below. Item codes must
          identify the same item in all three documents. Editing resets
          approvals.
        </p>
        <Label>
          Document number
          <Input
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            required
          />
        </Label>
        <Label>
          Currency
          <select
            className={selectClass}
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
          >
            {["INR", "USD", "EUR", "GBP"].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </Label>
        {lines.map((l, i) => (
          <fieldset
            key={i}
            className="grid gap-2 rounded border border-border p-3 sm:grid-cols-2"
          >
            <legend>Item {i + 1}</legend>
            {(
              ["sku", "description", "quantity", "unit_price_minor"] as const
            ).map((field) => (
              <Label key={field}>
                {field === "sku"
                  ? "Item code"
                  : field === "unit_price_minor"
                    ? "Unit price in paise/cents"
                    : field === "quantity"
                      ? "Quantity"
                      : "Description"}
                <Input
                  value={l[field]}
                  type={field === "unit_price_minor" ? "number" : "text"}
                  min={0}
                  onChange={(e) =>
                    setLines(
                      lines.map((row, j) =>
                        j === i
                          ? {
                              ...row,
                              [field]:
                                field === "unit_price_minor"
                                  ? Number(e.target.value)
                                  : e.target.value,
                            }
                          : row,
                      ),
                    )
                  }
                />
              </Label>
            ))}
            <Button
              variant="ghost"
              disabled={lines.length === 1}
              onClick={() => setLines(lines.filter((_, j) => j !== i))}
            >
              Remove item
            </Button>
          </fieldset>
        ))}
        <Button
          variant="secondary"
          onClick={() =>
            setLines([
              ...lines,
              { sku: "", description: "", quantity: "1", unit_price_minor: 0 },
            ])
          }
        >
          Add item
        </Button>
        <Label>
          Tax in paise/cents
          <Input
            type="number"
            min={0}
            value={tax}
            onChange={(e) => setTax(Number(e.target.value))}
          />
        </Label>
        <p>
          Computed total: {money(total, currency)}. Compare it with the original
          document.
        </p>
        <ErrorNote error={error} />
        <Button
          disabled={busy || !number || !Number.isSafeInteger(total)}
          onClick={() => void confirm()}
        >
          {busy ? "Working…" : "Confirm document details"}
        </Button>
      </div>
    </details>
  );
}

function CaseCard({
  item,
  roles,
  refresh,
}: {
  item: Case;
  roles: string[];
  refresh: () => void;
}) {
  const [comment, setComment] = useState("");
  const [reference, setReference] = useState("");
  const mutate = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) =>
      api(`/procurement/cases/${item.id}/${path}`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: refresh,
  });
  const can = (...r: string[]) => r.some((role) => roles.includes(role));
  const documentRoles: Record<string, string[]> = {
    po: ["purchasing", "clerk", "admin"],
    invoice: ["vendor", "clerk", "admin"],
    receipt: ["receiving", "purchasing", "clerk", "admin"],
  };
  async function openFile(kind: string) {
    const res = await fetch(
      `/api/v1/procurement/cases/${item.id}/documents/${kind}/file`,
      { headers: { authorization: `Bearer ${await apiToken()}` } },
    );
    if (!res.ok) throw new Error("Could not open source");
    const url = URL.createObjectURL(await res.blob());
    window.open(url, "_blank", "noopener,noreferrer");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  const [fileError, setFileError] = useState<unknown>(null);
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap justify-between gap-2">
        <h2 className="text-lg font-semibold">
          {item.po_number} · {item.vendor_id}
        </h2>
        <Badge>{item.state.status.replaceAll("_", " ")}</Badge>
      </div>
      <p className="text-sm text-muted">
        Evidence revision {item.state.revision}. L1 and finance must be
        different people, and neither can be a document uploader.
      </p>
      {Object.entries(item.state.documents).map(
        ([kind, doc]) =>
          doc && (
            <div
              key={kind}
              className="rounded border border-border p-3 text-sm"
            >
              <strong>
                {kind.toUpperCase()}: {doc.number}
              </strong>
              <p>
                {doc.lines
                  .map((l) => `${l.quantity} × ${l.description}`)
                  .join("; ")}{" "}
                · {money(doc.total_minor, doc.currency)}
              </p>
              {doc.source_document_id && (
                <Button
                  variant="ghost"
                  onClick={() => void openFile(kind).catch(setFileError)}
                >
                  View source PDF
                </Button>
              )}
            </div>
          ),
      )}
      {!item.state.payment &&
        Object.entries(documentRoles)
          .filter(([, r]) => can(...r))
          .map(([kind]) => (
            <DocumentForm
              key={`${kind}-${item.state.revision}`}
              item={item}
              kind={kind}
              refresh={refresh}
            />
          ))}
      {item.state.comparison && (
        <div>
          <Badge tone={item.state.comparison.matched ? "ok" : "warn"}>
            {item.state.comparison.matched
              ? "Documents align"
              : "Evidence needs attention"}
          </Badge>
          <p className="mt-2 text-sm">
            {item.state.comparison.missing.length
              ? `Missing: ${item.state.comparison.missing.join(", ")}`
              : ""}
          </p>
          <ul>
            {item.state.comparison.findings.map((f, i) => (
              <li key={i} className="text-sm text-warn">
                {f.code.replaceAll("_", " ")}: {f.sku ?? f.document}
                {f.invoiced
                  ? ` — invoiced ${f.invoiced}, received ${f.received}, ordered ${f.ordered}`
                  : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {item.state.approvals.map((a) => (
        <p key={a.stage} className="text-sm">
          {a.stage} approved by {a.actor}: {a.comment}
        </p>
      ))}
      {((item.state.status === "awaiting_l1" && can("approver")) ||
        (item.state.status === "awaiting_finance" &&
          can("finance", "controller"))) && (
        <div className="space-y-2">
          <Label>
            Review comment
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </Label>
          <Button
            disabled={!comment || mutate.isPending}
            onClick={() =>
              mutate.mutate({
                path: "review",
                body: {
                  revision: item.state.revision,
                  action:
                    item.state.status === "awaiting_l1" ? "l1" : "finance",
                  comment,
                },
              })
            }
          >
            Approve {item.state.status === "awaiting_l1" ? "L1" : "finance"}
          </Button>{" "}
          <Button
            variant="secondary"
            disabled={!comment || mutate.isPending}
            onClick={() =>
              mutate.mutate({
                path: "review",
                body: {
                  revision: item.state.revision,
                  action: "reject",
                  comment,
                },
              })
            }
          >
            Request correction
          </Button>
        </div>
      )}
      {item.state.status === "approved_for_payment" &&
        can("finance", "controller") && (
          <form
            className="space-y-2"
            action={(fd) =>
              mutate.mutate({
                path: "paid",
                body: {
                  revision: item.state.revision,
                  reference,
                  date: fd.get("date"),
                  amount_minor: item.state.documents.invoice?.total_minor,
                },
              })
            }
          >
            <Label>
              Payment reference
              <Input
                required
                value={reference}
                onChange={(e) => setReference(e.target.value)}
              />
            </Label>
            <Label>
              Payment date
              <Input
                name="date"
                type="date"
                required
                defaultValue={new Date().toISOString().slice(0, 10)}
              />
            </Label>
            <Button disabled={mutate.isPending}>
              Record simulated payment
            </Button>
          </form>
        )}
      {item.state.payment && (
        <p>
          Payment recorded: {item.state.payment.reference} ·{" "}
          {money(
            item.state.payment.amount_minor,
            item.state.documents.invoice?.currency,
          )}{" "}
          · {item.state.payment.date}
        </p>
      )}
      {item.state.notification && (
        <div className="rounded border border-border p-3 text-sm">
          <strong>Vendor email: {item.state.notification.status}</strong>
          <p>
            {item.state.notification.notice ?? item.state.notification.error}
          </p>
          {item.state.notification.body && (
            <pre className="mt-2 whitespace-pre-wrap">
              {item.state.notification.body}
            </pre>
          )}
          {can("finance", "controller", "admin") &&
            ["preview", "failed", "pending"].includes(
              item.state.notification.status,
            ) && (
              <Button
                variant="secondary"
                onClick={() =>
                  mutate.mutate({ path: "notification/retry", body: {} })
                }
              >
                Retry notification
              </Button>
            )}
        </div>
      )}
      <ErrorNote error={mutate.error ?? fileError} />
    </Card>
  );
}

export default function ProcurementPage() {
  const qc = useQueryClient();
  const [orgError, setOrgError] = useState<unknown>(null);
  const query = useQuery({
    queryKey: ["procurement"],
    queryFn: () =>
      api<{ roles: string[]; cases: Case[] }>("/procurement/cases"),
  });
  const orgs = useQuery({
    queryKey: ["organizations"],
    queryFn: async () => {
      const r = await authClient.organization.list();
      return r.data ?? [];
    },
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["procurement"] });
  };
  const create = useMutation({
    mutationFn: (fd: FormData) =>
      api("/procurement/cases", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(fd)),
      }),
    onSuccess: refresh,
  });
  const member = useMutation({
    mutationFn: (fd: FormData) => {
      const body = Object.fromEntries(fd);
      if (!body.vendor_id) delete body.vendor_id;
      return api("/procurement/members", {
        method: "POST",
        body: JSON.stringify(body),
      });
    },
  });
  const roles = query.data?.roles ?? [];
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-2xl font-semibold">Purchasing and vendor workflow</h1>
      <p className="text-sm text-muted">
        Synthetic documents and simulated payments. Each account sees the
        actions assigned to its role.
      </p>
      {orgs.data && orgs.data.length > 1 && (
        <Card>
          <Label>
            Workspace
            <select
              className={selectClass}
              defaultValue=""
              onChange={async (e) => {
                try {
                  const r = await authClient.organization.setActive({
                    organizationId: e.target.value,
                  });
                  if (r.error) throw new Error(r.error.message);
                  clearApiToken();
                  window.location.reload();
                } catch (err) {
                  setOrgError(err);
                }
              }}
            >
              <option value="" disabled>
                Select a workspace
              </option>
              {orgs.data.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.name}
                </option>
              ))}
            </select>
          </Label>
          <ErrorNote error={orgError} />
        </Card>
      )}
      {roles.includes("admin") && (
        <Card>
          <h2 className="font-semibold">Assign a colleague or vendor</h2>
          <p className="my-2 text-sm text-muted">
            Ask them to sign up first. Add their account here, then they select
            this workspace using the selector above.
          </p>
          <form
            action={(fd) => member.mutate(fd)}
            className="grid gap-3 sm:grid-cols-2"
          >
            <Label>
              Account email
              <Input name="email" type="email" required />
            </Label>
            <Label>
              Role
              <select name="role" className={selectClass}>
                {[
                  "vendor",
                  "purchasing",
                  "receiving",
                  "approver",
                  "finance",
                  "auditor",
                ].map((r) => (
                  <option key={r}>{r}</option>
                ))}
              </select>
            </Label>
            <Label>
              Vendor identifier (vendor accounts)
              <Input name="vendor_id" placeholder="e.g. ACME" />
            </Label>
            <Button disabled={member.isPending}>Assign access</Button>
          </form>
          <ErrorNote error={member.error} />
          {member.isSuccess && (
            <p className="text-ok">
              Access assigned. The person can select this workspace.
            </p>
          )}
        </Card>
      )}
      {roles.some((r) => ["admin", "clerk", "purchasing"].includes(r)) && (
        <Card>
          <h2 className="font-semibold">Start a purchasing case</h2>
          <form
            action={(fd) => create.mutate(fd)}
            className="mt-3 flex flex-wrap gap-3"
          >
            <Input
              name="po_number"
              aria-label="PO number"
              placeholder="PO-1001"
              required
            />
            <Input
              name="vendor_id"
              aria-label="Vendor identifier"
              placeholder="Vendor identifier, e.g. ACME"
              required
            />
            <Button disabled={create.isPending}>Create case</Button>
          </form>
          <ErrorNote error={create.error} />
        </Card>
      )}
      <ErrorNote error={query.error} />
      {query.isPending && <p>Loading purchasing records…</p>}
      {query.data?.cases.length === 0 && (
        <Card>
          No cases yet. Purchasing creates a case and assigns its vendor.
        </Card>
      )}
      {query.data?.cases.map((c) => (
        <CaseCard key={c.id} item={c} roles={roles} refresh={refresh} />
      ))}
    </div>
  );
}
