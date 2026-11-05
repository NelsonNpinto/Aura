# Approval Matrix and Tolerances (synthetic)

Effective 2026-01-01. Amounts are in the base currency (USD) at the dated FX rate.

| Condition | Required approval |
|---|---|
| Up to $1,000 with no flags | Auto-approve |
| Up to $10,000 | Approver |
| Above $10,000, or any HIGH-severity flag | Controller |
| Any bank-detail change | Controller, plus a documented call-back verification |

| Tolerance | Value |
|---|---|
| Unit price | 2% or $5, whichever is larger |
| Quantity | Billed quantity must not exceed received quantity |
| Header total | 0.5% |
| Freight and surcharges not on the PO | Up to 3% of goods value |

Approvals not actioned within 2 business days escalate to the next role.
