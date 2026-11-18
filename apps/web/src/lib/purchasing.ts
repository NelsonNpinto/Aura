import { queryOptions } from "@tanstack/react-query";
import { api } from "./api";

export const caseStages = {
  collecting_documents: "Collecting documents",
  needs_correction: "Correction required",
  awaiting_l1: "Awaiting L1",
  awaiting_finance: "Awaiting finance",
  approved_for_payment: "Ready for payment",
  paid: "Payment recorded",
} as const;

export type CaseStatus = keyof typeof caseStages;
export type CaseSummary = {
  id: string;
  po_number: string;
  vendor_id: string;
  status: CaseStatus;
};

export const documentNames: Record<string, string> = {
  po: "Purchase order",
  invoice: "Vendor invoice",
  receipt: "Goods receipt",
};

export const purchasingCases = queryOptions({
  queryKey: ["procurement", "summary"],
  queryFn: ({ signal }) =>
    api<{ roles: string[]; vendor_id: string | null; cases: CaseSummary[] }>(
      "/procurement/cases?view=summary",
      { signal },
    ),
});
