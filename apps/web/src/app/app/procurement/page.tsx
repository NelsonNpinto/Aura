"use client";

import {
  ArrowRight,
  Check,
  ChevronRight,
  FileText,
  LoaderCircle,
  Mail,
  RefreshCw,
  Trash2,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, apiResponse, money } from "@/lib/api";
import { authClient } from "@/lib/auth-client";
import { navigateAfterAuthChange } from "@/lib/auth-navigation";
import {
  caseStages,
  documentNames,
  purchasingCases,
  type CaseSummary,
  type CaseStatus,
} from "@/lib/purchasing";
import { PURCHASING_DEMO_ORG } from "@/lib/purchasing-demo";
import { useWorkspace } from "@/lib/workspace-context";
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Input,
  Label,
  Skeleton,
} from "@/components/ui";

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
type EmailNotification = {
  status: string;
  notice?: string;
  body?: string;
  error?: string;
};
type CaseState = {
  status: CaseStatus;
  revision: number;
  documents: Partial<Record<string, Doc>>;
  evidence?: Partial<Record<string, { at: string }>>;
  comparison?: {
    matched: boolean;
    missing: string[];
    findings: {
      code: string;
      sku?: string;
      document?: string;
      ordered?: string;
      invoiced?: string;
      received?: string;
      po_minor?: number;
      invoice_minor?: number;
    }[];
  };
  correction?: { stage: string; comment: string };
  approvals: { actor_name?: string | null; stage: string; comment: string }[];
  payment?: {
    reference: string;
    date: string;
    amount_minor: number;
    actor_name?: string | null;
  };
  notification?: EmailNotification;
};
type Case = {
  id: string;
  vendor_id: string;
  po_number: string;
  can_delete: boolean;
  email_send_blocker: string | null;
  state: CaseState;
};
type CaseList = {
  roles: string[];
  vendor_id: string | null;
  cases: CaseSummary[];
  default_case: Case | null;
};
const caseListKey = [...purchasingCases.queryKey, "with-default"] as const;
const maxUploadBytes =
  process.env.NODE_ENV === "development" ? 10_000_000 : 4_000_000;
const selectClass = "rounded border border-border bg-surface px-3 py-2 text-sm";
const documentFields: Record<string, string> = {
  number: "Document number",
  po_number: "PO reference",
  sku: "Item code",
  description: "Description",
  quantity: "Quantity",
  unit_price_minor: "Unit price",
  tax_minor: "Tax",
  total_minor: "Total",
};

function totalInMinorUnits(lines: Line[], tax: number): number | null {
  if (!Number.isSafeInteger(tax) || tax < 0) return null;
  const scale = BigInt(1000);
  let mills = BigInt(tax) * scale;
  for (const { quantity, unit_price_minor: price } of lines) {
    const match = /^(\d{1,7})(?:\.(\d{1,3}))?$/.exec(quantity.trim());
    if (!match || !Number.isSafeInteger(price) || price < 0) return null;
    const scaled =
      BigInt(match[1]) * scale + BigInt((match[2] ?? "").padEnd(3, "0"));
    if (scaled === BigInt(0) || scaled > BigInt(1_000_000_000)) return null;
    mills += scaled * BigInt(price);
  }
  return mills % scale === BigInt(0) && mills <= BigInt(100_000_000_000_000)
    ? Number(mills / scale)
    : null;
}

function documentError(error: unknown) {
  if (!(error instanceof ApiError) || error.code !== "validation_error") {
    return error;
  }
  if (!Array.isArray(error.details)) return error;
  const messages = error.details.flatMap((detail) => {
    const { loc, msg } = detail ?? {};
    if (!Array.isArray(loc) || typeof msg !== "string") return [];
    const field = documentFields[loc.at(-1)];
    const item =
      loc[1] === "lines" && typeof loc[2] === "number"
        ? `Item ${loc[2] + 1} · `
        : "";
    return [field ? `${item}${field}: ${msg}` : msg];
  });
  return messages.length ? new Error(messages.join(". ")) : error;
}

function DocumentForm({
  item,
  kind,
  refresh,
  onState,
}: {
  item: Case;
  kind: string;
  refresh: () => void;
  onState: (state: CaseState) => void;
}) {
  const initial = item.state.documents[kind];
  const [number, setNumber] = useState(initial?.number ?? "");
  const [poNumber, setPoNumber] = useState(
    initial?.po_number ?? item.po_number,
  );
  const [currency, setCurrency] = useState(
    initial?.currency ?? item.state.documents.po?.currency ?? "INR",
  );
  const [lines, setLines] = useState<Line[]>(
    initial?.lines ?? [
      { sku: "", description: "", quantity: "1", unit_price_minor: 0 },
    ],
  );
  const [tax, setTax] = useState(initial?.tax_minor ?? 0);
  const [extractedTotal, setExtractedTotal] = useState<number | null>(null);
  const [source, setSource] = useState(initial?.source_document_id ?? null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [extractedName, setExtractedName] = useState("");
  const [fileStatus, setFileStatus] = useState("");
  const [uploading, setUploading] = useState<"extract" | "attach" | null>(null);
  const [fileError, setFileError] = useState<unknown>(null);
  const total = totalInMinorUnits(lines, tax);
  async function upload(file: File, useAi: boolean) {
    setUploading(useAi ? "extract" : "attach");
    setBusy(true);
    setFileError(null);
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("synthetic_confirmed", "true");
      body.append("use_ai", String(useAi));
      const res = await api<{
        draft: Doc | null;
        source_document_id: string;
        extraction_mode?: "demo_fixture" | "manual";
      }>(`/procurement/cases/${item.id}/extract/${kind}`, {
        method: "POST",
        body,
      });
      if (res.draft) {
        setNumber(res.draft.number);
        setPoNumber(res.draft.po_number);
        setCurrency(res.draft.currency);
        setLines(res.draft.lines);
        setTax(res.draft.tax_minor);
      }
      setExtractedTotal(res.draft?.total_minor ?? null);
      setSource(res.source_document_id);
      setSelectedFile(null);
      setExtractedName(file.name);
      setFileStatus(
        res.extraction_mode === "manual"
          ? "Source attached"
          : res.extraction_mode === "demo_fixture"
            ? "Demo fields ready to review"
            : "Ready to review",
      );
    } catch (e) {
      setFileError(e);
    } finally {
      setUploading(null);
      setBusy(false);
    }
  }
  async function confirm() {
    setError(null);
    if (!number.trim()) {
      setError(new Error("Enter the document number."));
      return;
    }
    const incompleteItem = lines.findIndex(
      (line) => !line.sku.trim() || !line.description.trim(),
    );
    if (incompleteItem !== -1) {
      setError(
        new Error(
          `Enter the item code and description for item ${incompleteItem + 1}.`,
        ),
      );
      return;
    }
    if (poNumber.trim() !== item.po_number) {
      setError(
        new Error(
          `The source must reference PO ${item.po_number}. Check the document before confirming.`,
        ),
      );
      return;
    }
    if (total === null || (kind === "invoice" && total === 0)) {
      setError(
        new Error(
          "Check the quantities and prices. Totals must use whole paise or cents, and invoices must have a positive total.",
        ),
      );
      return;
    }
    setBusy(true);
    try {
      const state = await api<CaseState>(
        `/procurement/cases/${item.id}/documents/${kind}?revision=${item.state.revision}`,
        {
          method: "PUT",
          body: JSON.stringify({
            number,
            po_number: poNumber,
            currency,
            lines,
            tax_minor: tax,
            total_minor: total,
            source_document_id: source,
          }),
        },
      );
      onState(state);
    } catch (e) {
      setError(documentError(e));
      if (e instanceof ApiError && e.code === "revision_changed") refresh();
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="rounded border border-border p-3">
      <summary className="cursor-pointer font-medium">
        {initial ? "Edit" : "Add"} {documentNames[kind].toLowerCase()}
      </summary>
      <div className="mt-3 space-y-3">
        <div className="space-y-3 rounded-xl border border-dashed border-border bg-surface-2 p-4">
          <div className="flex items-start gap-3">
            <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-surface text-accent">
              <FileText size={18} aria-hidden />
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold">Add a source document</p>
              <p className="text-xs text-muted">
                Synthetic PDF, PNG or JPEG up to {maxUploadBytes / 1_000_000}{" "}
                MB.
              </p>
            </div>
          </div>
          <input
            ref={picker}
            type="file"
            accept=".pdf,.png,.jpg,.jpeg"
            disabled={busy}
            hidden
            onChange={(e) => {
              const file = e.currentTarget.files?.[0];
              e.currentTarget.value = "";
              if (!file) return;
              if (file.size > maxUploadBytes) {
                setSelectedFile(null);
                setFileError(
                  new Error(
                    `Choose a file that is ${maxUploadBytes / 1_000_000} MB or smaller.`,
                  ),
                );
                return;
              }
              setFileError(null);
              setSelectedFile(file);
            }}
          />
          <div role="status" className="break-all text-sm text-muted">
            {selectedFile
              ? selectedFile.name
              : extractedName
                ? `${fileStatus} · ${extractedName}`
                : source
                  ? "Source file attached"
                  : "No file selected"}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant={selectedFile ? "secondary" : "primary"}
              disabled={busy}
              onClick={() => picker.current?.click()}
            >
              <Upload size={16} aria-hidden />
              {selectedFile ? "Change file" : "Choose PDF or image"}
            </Button>
            {selectedFile && (
              <>
                <Button
                  type="button"
                  disabled={busy}
                  onClick={() => void upload(selectedFile, true)}
                >
                  {uploading === "extract" && (
                    <LoaderCircle
                      className="size-4 motion-safe:animate-spin"
                      aria-hidden
                    />
                  )}
                  {uploading === "extract"
                    ? "Reading document…"
                    : "Extract details"}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void upload(selectedFile, false)}
                >
                  {uploading === "attach" ? "Attaching…" : "Attach without AI"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    setSelectedFile(null);
                    setFileError(null);
                  }}
                >
                  Remove selection
                </Button>
              </>
            )}
          </div>
          <ErrorNote error={fileError} />
        </div>
        <p className="text-xs text-muted">
          Review the extracted fields before confirming, or enter the details
          below. Use the same item code across all three documents. Editing
          resets approvals.
        </p>
        {kind === "receipt" && (
          <p className="text-xs text-muted">
            Enter the quantity actually received. For a receipt that lists
            quantities only, leave the unit price and tax at zero.
          </p>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          <Label>
            Document number
            <Input
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              required
            />
          </Label>
          <Label>
            PO reference
            <Input
              value={poNumber}
              onChange={(e) => setPoNumber(e.target.value)}
              aria-invalid={poNumber.trim() !== item.po_number}
            />
          </Label>
        </div>
        {poNumber.trim() !== item.po_number && (
          <p className="text-sm text-warn">
            This case is for {item.po_number}. Check the PO printed on the
            source file.
          </p>
        )}
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
              disabled={busy || lines.length === 1}
              onClick={() => setLines(lines.filter((_, j) => j !== i))}
            >
              Remove item
            </Button>
          </fieldset>
        ))}
        <Button
          variant="secondary"
          disabled={busy || lines.length >= 100}
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
        <p className="text-sm">
          Computed total{" "}
          <strong className="tabular-nums">{money(total, currency)}</strong>
          {extractedTotal !== null && extractedTotal !== total && (
            <span className="ml-2 text-warn">
              Extracted total {money(extractedTotal, currency)}. Check the
              source before saving.
            </span>
          )}
        </p>
        <ErrorNote error={error} />
        <Button
          disabled={busy || Boolean(selectedFile)}
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
  onState,
  onDelete,
}: {
  item: Case;
  roles: string[];
  refresh: () => void;
  onState: (state: CaseState) => void;
  onDelete: (item: Case) => void;
}) {
  const [comment, setComment] = useState("");
  const [reference, setReference] = useState("");
  const deleteDialog = useRef<HTMLDialogElement>(null);
  const remove = useMutation({
    mutationFn: () =>
      api<void>(
        `/procurement/cases/${item.id}?revision=${item.state.revision}`,
        { method: "DELETE" },
      ),
    onSuccess: () => {
      deleteDialog.current?.close();
      onDelete(item);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) refresh();
    },
  });
  const mutate = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) =>
      api<CaseState>(`/procurement/cases/${item.id}/${path}`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (state) => {
      onState(state);
      setComment("");
      setReference("");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) refresh();
    },
  });
  const email = useMutation({
    mutationFn: () =>
      api<EmailNotification>(
        `/procurement/cases/${item.id}/notification/send`,
        { method: "POST" },
      ),
    onSuccess: refresh,
    onError: (error) => {
      if (error instanceof ApiError && error.code === "gmail_unavailable")
        refresh();
    },
  });
  const can = (...r: string[]) => r.some((role) => roles.includes(role));
  const storedNotification = item.state.notification;
  const notification =
    email.data && email.data.status !== "already_processed_or_busy"
      ? { ...storedNotification, ...email.data }
      : storedNotification;
  const sendingUnavailable =
    Boolean(item.email_send_blocker) ||
    (email.error instanceof ApiError &&
      email.error.code === "gmail_unavailable");
  const emailStatus =
    notification?.status === "accepted"
      ? "Accepted by Gmail"
      : notification?.status === "delivery_unknown"
        ? "Check Gmail Sent"
        : notification?.status === "failed"
          ? "Delivery failed"
          : sendingUnavailable
            ? "Preview"
            : "Ready to send";
  const documentRoles: Record<string, string[]> = {
    po: ["purchasing", "clerk", "admin"],
    invoice: ["vendor", "clerk", "admin"],
    receipt: ["receiving", "purchasing", "clerk", "admin"],
  };
  const [fileError, setFileError] = useState<unknown>(null);
  const [openingFile, setOpeningFile] = useState<string | null>(null);
  async function openFile(kind: string) {
    const tab = window.open("about:blank", "_blank");
    if (!tab) throw new Error("Allow pop-ups to open the source document.");
    tab.opener = null;
    setOpeningFile(kind);
    setFileError(null);
    try {
      const res = await apiResponse(
        `/procurement/cases/${item.id}/documents/${kind}/file`,
      );
      const url = URL.createObjectURL(await res.blob());
      tab.location.replace(url);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (error) {
      tab.close();
      throw error;
    } finally {
      setOpeningFile(null);
    }
  }
  const phase =
    ["awaiting_l1", "awaiting_finance", "approved_for_payment", "paid"].indexOf(
      item.state.status,
    ) + 1;
  return (
    <Card className="workspace-enter space-y-4">
      <div className="flex flex-wrap justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">{item.po_number}</h2>
          <p className="mt-1 text-sm text-muted">
            {item.vendor_id} · Revision {item.state.revision}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            tone={item.state.status === "needs_correction" ? "warn" : "accent"}
          >
            {caseStages[item.state.status]}
          </Badge>
          {item.can_delete && (
            <Button
              type="button"
              variant="ghost"
              className="text-danger"
              onClick={() => {
                remove.reset();
                deleteDialog.current?.showModal();
              }}
            >
              <Trash2 className="size-4" aria-hidden /> Delete case
            </Button>
          )}
        </div>
      </div>
      <dialog
        ref={deleteDialog}
        aria-labelledby="delete-case-title"
        className="m-auto w-[min(92vw,28rem)] rounded-xl border border-border bg-surface p-5 text-text shadow-xl backdrop:bg-black/40"
        onCancel={(event) => {
          if (remove.isPending) event.preventDefault();
        }}
      >
        <h3 id="delete-case-title" className="font-semibold">
          Delete {item.po_number}?
        </h3>
        <p className="mt-2 text-sm text-muted">
          This permanently removes the case from Purchasing for everyone in this
          workspace. Its audit record is retained.
        </p>
        <div className="mt-4 space-y-3">
          <ErrorNote error={remove.error} />
          <div className="flex flex-wrap justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              disabled={remove.isPending}
              onClick={() => deleteDialog.current?.close()}
            >
              Cancel
            </Button>
            <Button
              type="button"
              className="bg-danger text-white"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {remove.isPending ? "Deleting…" : "Permanently delete case"}
            </Button>
          </div>
        </div>
      </dialog>
      <ol
        aria-label="Case steps"
        className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4"
      >
        {["Documents", "L1 review", "Finance review", "Payment"].map(
          (label, i) => (
            <li
              key={label}
              aria-current={phase === i ? "step" : undefined}
              className={`flex items-center gap-2 rounded-md border px-2 py-2 ${phase === i ? "border-accent/40 bg-accent/10 font-semibold text-accent" : "border-border text-muted"}`}
            >
              {i < phase && (
                <Check className="size-4 shrink-0 text-ok" aria-hidden />
              )}
              {label}
            </li>
          ),
        )}
      </ol>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">Evidence</h3>
        <Link
          className="inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline"
          href={`/app/copilot?case=${item.id}`}
        >
          Ask Copilot <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
      {Object.entries(documentNames).map(([kind, label]) => {
        const doc = item.state.documents[kind];
        return doc ? (
          <div
            key={kind}
            className="rounded-lg border border-border p-3 text-sm"
          >
            <div className="flex flex-wrap justify-between gap-2">
              <strong>
                {label} · {doc.number}
              </strong>
              <span className="font-medium tabular-nums">
                {money(doc.total_minor, doc.currency)}
              </span>
            </div>
            <details className="mt-2">
              <summary className="cursor-pointer text-muted">
                View {doc.lines.length}{" "}
                {doc.lines.length === 1 ? "item" : "items"}
              </summary>
              <ul className="mt-2 space-y-1">
                {doc.lines.map((line) => (
                  <li
                    key={line.sku}
                    className="flex flex-wrap justify-between gap-x-3 border-t border-border py-2"
                  >
                    <span>
                      <strong>{line.sku}</strong> · {line.description}
                    </span>
                    <span className="tabular-nums text-muted">
                      {line.quantity} ×{" "}
                      {money(line.unit_price_minor, doc.currency)}
                    </span>
                  </li>
                ))}
              </ul>
              {!!doc.tax_minor && (
                <p className="text-muted">
                  Tax {money(doc.tax_minor, doc.currency)}
                </p>
              )}
            </details>
            {doc.source_document_id && (
              <Button
                variant="ghost"
                disabled={openingFile !== null}
                onClick={() => void openFile(kind).catch(setFileError)}
              >
                {openingFile === kind ? "Opening…" : "View source"}
              </Button>
            )}
          </div>
        ) : (
          <div
            key={kind}
            className="flex flex-wrap justify-between gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-sm"
          >
            <span>{label}</span>
            <span className="text-muted">Awaiting document</span>
          </div>
        );
      })}
      {!item.state.payment &&
        Object.entries(documentRoles)
          .filter(([, r]) => can(...r))
          .map(([kind]) => (
            <DocumentForm
              key={`${kind}-${item.state.evidence?.[kind]?.at ?? "new"}`}
              item={item}
              kind={kind}
              refresh={refresh}
              onState={onState}
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
              ? `Still needed: ${item.state.comparison.missing.map((kind) => documentNames[kind]).join(", ")}`
              : ""}
          </p>
          <ul>
            {item.state.comparison.findings.map((f, i) => (
              <li key={i} className="text-sm text-warn">
                {(
                  {
                    QUANTITY_SHORTFALL: "Quantity mismatch",
                    PRICE_VARIANCE: "Unit price mismatch",
                    HEADER_MISMATCH: "PO reference or currency mismatch",
                    NO_PO_LINE: "Invoice item missing from the PO",
                    UNEXPECTED_RECEIPT:
                      "Unexpected item or quantity on receipt",
                  } as Record<string, string>
                )[f.code] ?? "Review document"}{" "}
                · {f.sku ?? documentNames[f.document ?? ""] ?? "Evidence"}
                {f.invoiced
                  ? ` — invoiced ${f.invoiced}, received ${f.received}, ordered ${f.ordered}`
                  : ""}
                {f.code === "PRICE_VARIANCE" &&
                  ` — PO ${money(f.po_minor, item.state.documents.po?.currency)}, invoice ${money(f.invoice_minor, item.state.documents.invoice?.currency)}`}
              </li>
            ))}
          </ul>
        </div>
      )}
      {item.state.correction && (
        <div className="rounded-lg border border-warn/40 bg-warn/5 p-3 text-sm">
          <strong>
            {item.state.correction.stage === "l1" ? "L1" : "Finance"} requested
            a correction
          </strong>
          <p className="mt-1 whitespace-pre-wrap">
            {item.state.correction.comment}
          </p>
        </div>
      )}
      {item.state.approvals.map((a) => (
        <p key={a.stage} className="text-sm">
          {a.stage === "l1" ? "L1" : "Finance"} approved by{" "}
          {a.actor_name ?? "a reviewer"} · {a.comment}
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
              maxLength={2000}
              onChange={(e) => setComment(e.target.value)}
            />
          </Label>
          <Button
            disabled={!comment.trim() || mutate.isPending}
            onClick={() => {
              mutate.mutate({
                path: "review",
                body: {
                  revision: item.state.revision,
                  action:
                    item.state.status === "awaiting_l1" ? "l1" : "finance",
                  comment,
                },
              });
            }}
          >
            Approve {item.state.status === "awaiting_l1" ? "L1" : "finance"}
          </Button>{" "}
          <Button
            variant="secondary"
            disabled={!comment.trim() || mutate.isPending}
            onClick={() => {
              mutate.mutate({
                path: "review",
                body: {
                  revision: item.state.revision,
                  action: "reject",
                  comment,
                },
              });
            }}
          >
            Request correction
          </Button>
        </div>
      )}
      {item.state.status === "approved_for_payment" &&
        can("finance", "controller") && (
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              const fd = new FormData(event.currentTarget);
              mutate.mutate({
                path: "paid",
                body: {
                  revision: item.state.revision,
                  reference,
                  date: fd.get("date"),
                  amount_minor: item.state.documents.invoice?.total_minor,
                },
              });
            }}
          >
            <Label>
              Payment reference
              <Input
                required
                value={reference}
                maxLength={100}
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
            <Button disabled={mutate.isPending || !reference.trim()}>
              {mutate.isPending ? "Recording…" : "Record simulated payment"}
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
          {item.state.payment.actor_name &&
            ` · Recorded by ${item.state.payment.actor_name}`}
        </p>
      )}
      {notification && (
        <div className="space-y-3 rounded-lg border border-border bg-surface-2 p-4 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 font-semibold">
              <Mail className="size-4 text-accent" aria-hidden />
              Payment email
            </h3>
            <Badge
              tone={
                notification.status === "accepted"
                  ? "ok"
                  : ["failed", "delivery_unknown"].includes(notification.status)
                    ? "warn"
                    : "neutral"
              }
            >
              {emailStatus}
            </Badge>
          </div>
          {notification.status === "delivery_unknown" ? (
            <p className="mt-1 text-warn">
              Check the sender’s Gmail Sent folder. Gmail may have received this
              message.
            </p>
          ) : (
            notification.status === "failed" && (
              <p>
                {notification.notice ??
                  notification.error?.replaceAll("_", " ")}
              </p>
            )
          )}
          {notification.body && notification.status !== "accepted" && (
            <div className="rounded-md border border-border bg-surface px-3 py-3">
              <p className="whitespace-pre-wrap leading-6">
                {notification.body.trimEnd()}
              </p>
            </div>
          )}
          {can("finance", "controller", "admin") &&
            ["preview", "failed", "pending"].includes(notification.status) && (
              <div className="space-y-2">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={email.isPending || sendingUnavailable}
                  onClick={() => email.mutate()}
                >
                  <Mail size={16} aria-hidden />
                  {email.isPending ? "Sending…" : "Send email"}
                </Button>
                {email.data?.status === "already_processed_or_busy" && (
                  <p className="text-muted">
                    A send may already be in progress. Refresh the case to check
                    its status.
                  </p>
                )}
                {!sendingUnavailable && <ErrorNote error={email.error} />}
              </div>
            )}
        </div>
      )}
      <ErrorNote error={mutate.error ?? fileError} />
    </Card>
  );
}

export default function ProcurementPage() {
  return (
    <Suspense fallback={<Skeleton className="h-56" />}>
      <PurchasingWorkspace />
    </Suspense>
  );
}

function PurchasingWorkspace() {
  const qc = useQueryClient();
  const params = useSearchParams();
  const workspace = useWorkspace();
  const [orgError, setOrgError] = useState<unknown>(null);
  const [switchingOrg, setSwitchingOrg] = useState(false);
  const [deletedPO, setDeletedPO] = useState<string | null>(null);
  const list = useQuery({
    queryKey: caseListKey,
    queryFn: ({ signal }) =>
      api<CaseList>("/procurement/cases?view=summary&include_default=true", {
        signal,
      }),
    enabled: Boolean(workspace.id),
    refetchOnWindowFocus: "always",
  });
  const cases = list.data?.cases ?? [];
  const active = params.get("case") || cases[0]?.id;
  const caseKey = ["procurement", "case", active] as const;
  const detail = useQuery({
    queryKey: caseKey,
    queryFn: ({ signal }) =>
      api<Case>(`/procurement/cases/${active}`, { signal }),
    enabled: Boolean(workspace.id && active),
    refetchOnWindowFocus: "always",
    initialData:
      list.data?.default_case?.id === active
        ? (list.data?.default_case ?? undefined)
        : undefined,
    initialDataUpdatedAt: list.dataUpdatedAt,
  });
  function openCase(id?: string) {
    window.history.replaceState(
      null,
      "",
      id ? `?case=${encodeURIComponent(id)}` : "/app/procurement",
    );
  }
  function refresh() {
    void qc.invalidateQueries({
      queryKey: ["procurement"],
      refetchType: "active",
    });
  }
  function updateCase(state: CaseState) {
    void qc.cancelQueries({ queryKey: caseKey });
    qc.setQueryData<Case>(
      caseKey,
      (previous) => previous && { ...previous, state },
    );
    qc.setQueryData<CaseList>(
      caseListKey,
      (previous) =>
        previous && {
          ...previous,
          default_case:
            previous.default_case && previous.default_case.id === active
              ? { ...previous.default_case, state }
              : previous.default_case,
          cases: previous.cases.map((item) =>
            item.id === active ? { ...item, status: state.status } : item,
          ),
        },
    );
    refresh();
  }
  function onDelete(item: Case) {
    void qc.cancelQueries({ queryKey: purchasingCases.queryKey });
    qc.setQueryData<CaseList>(
      caseListKey,
      (previous) =>
        previous && {
          ...previous,
          cases: previous.cases.filter((entry) => entry.id !== item.id),
          default_case:
            previous.default_case?.id === item.id
              ? null
              : previous.default_case,
        },
    );
    openCase();
    qc.removeQueries({
      queryKey: ["procurement", "case", item.id],
      exact: true,
    });
    setDeletedPO(item.po_number);
    void qc.invalidateQueries({ queryKey: purchasingCases.queryKey });
  }
  const create = useMutation({
    mutationFn: (fd: FormData) =>
      api<{ id: string }>("/procurement/cases", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(fd)),
      }),
    onSuccess: ({ id }) => {
      setDeletedPO(null);
      openCase(id);
      refresh();
    },
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
  const roles = list.data?.roles ?? [];
  const canCreate = roles.some((r) =>
    ["admin", "clerk", "purchasing"].includes(r),
  );
  if (!workspace.id)
    return <Card>No active workspace is available for this account.</Card>;
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-semibold">Purchasing</h1>
          <p className="mt-2 text-sm text-muted">
            Match source documents, review exceptions, and record simulated
            payments.
          </p>
        </div>
        {workspace.workspaces.length > 1 ? (
          <div>
            <Label htmlFor="purchasing-workspace">Workspace</Label>
            <select
              id="purchasing-workspace"
              className={`${selectClass} mt-1 block`}
              value={workspace.id}
              disabled={switchingOrg}
              onChange={async (e) => {
                const selector = e.currentTarget;
                setOrgError(null);
                setSwitchingOrg(true);
                try {
                  const response = await authClient.organization.setActive({
                    organizationId: selector.value,
                  });
                  if (response.error)
                    throw new Error(
                      response.error.message ?? "Could not switch workspace",
                    );
                  navigateAfterAuthChange("/app/procurement");
                } catch (error) {
                  setOrgError(error);
                  setSwitchingOrg(false);
                }
              }}
            >
              {workspace.workspaces.map((org) => (
                <option key={org.id} value={org.id}>
                  {org.name}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <p className="text-sm text-muted">{workspace.name}</p>
        )}
      </header>
      <ErrorNote error={orgError} />
      {deletedPO && (
        <p role="status" className="text-sm text-ok">
          {deletedPO} was deleted.
        </p>
      )}
      {canCreate && (
        <Card>
          <h2 className="font-semibold">Start a purchasing case</h2>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              create.mutate(new FormData(form), {
                onSuccess: () => form.reset(),
              });
            }}
            className="mt-3 grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]"
          >
            <Label className="mb-0">
              PO number
              <Input
                name="po_number"
                className="mt-1"
                placeholder="PO-1001"
                maxLength={80}
                required
              />
            </Label>
            <Label className="mb-0">
              Vendor identifier
              <Input
                name="vendor_id"
                className="mt-1"
                placeholder={list.data?.vendor_id ?? "ACME"}
                defaultValue={
                  workspace.id === PURCHASING_DEMO_ORG ? "ACME" : undefined
                }
                maxLength={80}
                required
              />
            </Label>
            <Button disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create case"}
            </Button>
          </form>
          {workspace.id === PURCHASING_DEMO_ORG && (
            <p className="mt-2 text-xs text-muted">
              The demo Vendor login can open this case.
            </p>
          )}
          <ErrorNote error={create.error} />
        </Card>
      )}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(12rem,1fr)_minmax(0,3fr)]">
        <Card className="p-3">
          <div className="flex items-center justify-between px-2 pb-2">
            <h2 className="font-semibold">Cases</h2>
            <Button
              type="button"
              variant="ghost"
              aria-label="Refresh cases"
              title="Refresh cases"
              className="min-h-8 px-2 py-1"
              disabled={list.isFetching || detail.isFetching}
              onClick={refresh}
            >
              <RefreshCw className="size-4" aria-hidden />
            </Button>
          </div>
          {list.isPending && (
            <div role="status" aria-label="Loading cases" className="space-y-2">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          )}
          {list.error && (
            <div className="space-y-2">
              <ErrorNote error={list.error} />
              <Button variant="secondary" onClick={() => void list.refetch()}>
                Retry
              </Button>
            </div>
          )}
          {list.isSuccess && !cases.length && (
            <p className="px-2 text-sm text-muted">No purchasing cases yet.</p>
          )}
          <nav
            aria-label="Purchasing cases"
            className="max-h-72 space-y-1 overflow-y-auto lg:max-h-[38rem]"
          >
            {cases.map((item) => (
              <Link
                key={item.id}
                href={`?case=${item.id}`}
                replace
                scroll={false}
                prefetch={false}
                aria-current={active === item.id ? "page" : undefined}
                className="flex items-center justify-between gap-2 rounded-lg border border-transparent px-3 py-2.5 text-sm transition hover:bg-surface-2 aria-[current=page]:border-accent/30 aria-[current=page]:bg-accent/10"
              >
                <div className="min-w-0">
                  <p className="truncate font-semibold">{item.po_number}</p>
                  <p className="mt-0.5 truncate text-xs text-muted">
                    {item.vendor_id} · {caseStages[item.status]}
                  </p>
                </div>
                <ChevronRight
                  className="size-4 shrink-0 text-muted"
                  aria-hidden
                />
              </Link>
            ))}
          </nav>
        </Card>
        {active && detail.isPending && (
          <Card
            role="status"
            aria-label="Loading case evidence"
            className="space-y-4"
          >
            <Skeleton className="h-7 w-32" />
            <Skeleton className="h-9" />
            <Skeleton className="h-24" />
          </Card>
        )}
        {active && detail.error && (
          <Card className="space-y-3">
            {detail.error instanceof ApiError && detail.error.status === 404 ? (
              <>
                <p className="text-sm text-muted">
                  This case is unavailable in your current workspace or role.
                </p>
                <Button variant="secondary" onClick={() => openCase()}>
                  Show my cases
                </Button>
              </>
            ) : (
              <>
                <ErrorNote error={detail.error} />
                <Button
                  variant="secondary"
                  onClick={() => void detail.refetch()}
                >
                  Reload case
                </Button>
              </>
            )}
          </Card>
        )}
        {detail.data && (
          <CaseCard
            key={detail.data.id}
            item={detail.data}
            roles={roles}
            refresh={refresh}
            onState={updateCase}
            onDelete={onDelete}
          />
        )}
      </div>
      {roles.includes("admin") && (
        <details className="rounded-xl border border-border bg-surface p-4">
          <summary className="cursor-pointer font-semibold">
            Assign a colleague or vendor
          </summary>
          <p className="my-2 text-sm text-muted">
            Enter an existing account email. A vendor only sees cases assigned
            to their vendor identifier.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const form = event.currentTarget;
              member.mutate(new FormData(form), {
                onSuccess: () => form.reset(),
              });
            }}
            className="grid items-end gap-3 sm:grid-cols-2"
          >
            <Label className="mb-0">
              Account email
              <Input name="email" type="email" maxLength={254} required />
            </Label>
            <Label className="mb-0">
              Role
              <select name="role" className={`${selectClass} block w-full`}>
                {[
                  "vendor",
                  "purchasing",
                  "receiving",
                  "approver",
                  "finance",
                  "auditor",
                ].map((role) => (
                  <option key={role}>{role}</option>
                ))}
              </select>
            </Label>
            <Label className="mb-0">
              Vendor identifier (vendor accounts)
              <Input name="vendor_id" placeholder="ACME" maxLength={80} />
            </Label>
            <Button className="justify-self-start" disabled={member.isPending}>
              Assign access
            </Button>
          </form>
          <ErrorNote error={member.error} />
          {member.isSuccess && (
            <p role="status" className="mt-2 text-sm text-ok">
              Access assigned.
            </p>
          )}
        </details>
      )}
    </div>
  );
}
