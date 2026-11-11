# Purchasing workflow walkthrough

This guide describes the new implementation. Check PROGRESS.md for whether its commit is deployed. The original Invoices page remains a separate agent demonstration with risk-based auto-routing; Purchasing implements mandatory L1 and finance review.

## Accounts

The live login page has **Purchasing**, **Vendor**, **L1** and **Finance** shortcuts for the shared synthetic workspace. Pick a role, complete the sign-in check and click **Log in**. Start a case with a fresh PO number and vendor ID `ACME` so the Vendor account can see it. Public demo payment emails appear as previews. Use your own registered accounts and a vendor inbox you control to test Gmail delivery.

1. Create an AURA account for the workspace owner, a vendor, an L1 reviewer and a finance reviewer. Use different accounts. The owner can perform purchasing/receiving in the demo.
2. As the owner, open **Purchasing**. In **Assign a colleague or vendor**, enter each existing account email, its role and, for the vendor, an identifier such as `ACME`.
3. The other users open Purchasing and select the owner's workspace. Their personal workspace is separate. The vendor identifier on a case must exactly match its account assignment.
4. L1 uses role `approver`; L2 uses `finance`. An administrator cannot substitute for these approvals. A document uploader or case creator cannot review their own case, and L1 and L2 must be different people.

## PO, invoice and receipt

5. Purchasing creates a case with PO number `PO-1001` and vendor identifier `ACME`.
6. Supply its PO. Upload a synthetic PDF or image for AI extraction, inspect the proposed fields, correct them and click **Confirm document details**. Manual entry also works.
7. The vendor signs in separately, selects the shared workspace and supplies the invoice in the same case.
8. Purchasing or receiving supplies the goods receipt. Use the same item code for the same item across the three documents. When a receipt has no prices, prices/totals may be zero; receipt matching uses delivered quantities.
9. Prices are entered in paise/cents: `5000000` means INR 50,000. Only INR/USD/EUR/GBP are supported in this profile. Exact unit-price matching is enforced. Item matching is based on confirmed item identifiers, so a person must reconcile differing model-proposed identifiers.
10. For PO 2 laptops / invoice 2 / receipt 1, the case needs correction. Record the complete receipt when appropriate. A one-laptop partial invoice can match a one-laptop receipt. Currently one purchasing case holds one invoice per PO; multi-invoice PO allocation remains a future extension.
11. The form computes line totals plus tax; compare that total with the original document. Extracted fields are proposals, not independently certified facts.

## Reviews and payment

12. When all documents align, the case waits for L1. Sign in as the L1 reviewer, inspect the confirmed documents and source PDFs, add a comment and approve.
13. Sign in as finance and review next. Finance cannot act before L1. Requesting correction reopens the evidence stage.
14. Editing a document clears both approvals and increases the evidence revision. A reviewer viewing an older revision must refresh.
15. Finance enters a payment reference and date and clicks **Record simulated payment**. No funds move. A paid case cannot be edited; repeated identical requests return the existing payment, and conflicting payment details are rejected.
16. The notification event is stored transactionally with payment. Default `MAIL_MODE=preview` displays its content and explicitly sends nothing. For real demo notification, follow [GMAIL_SETUP.md](GMAIL_SETUP.md). `accepted` means Gmail accepted the request, not confirmed inbox delivery. An uncertain send requires checking the sender mailbox before retrying.

## Copilot and quality

17. Open **Copilot**, select a case, and ask "Why is this invoice waiting?" The assistant reads that case's current evidence. With Policy knowledge base selected, it uses the existing hybrid retrieval system. It cannot approve or pay.
18. Open **AI quality** to inspect stored synthetic workflow reports. Fixture results test orchestration with supplied extraction data; they do not measure model extraction accuracy.
19. As an admin/approver/controller, use the judge workbench. The synthetic marketing example deliberately conflicts with its supplied facts. You can generate a new draft, run the model judge and record your own genuine human assessment. No human labels are created automatically.
20. Observe actual agreement only after submitting labels. Tied human votes and unscored model outputs are excluded; tiny samples do not establish reliability.

## Important verification still required

Live extraction on representative scans, a complete signed-in browser walkthrough across accounts, and real email delivery remain distinct acceptance checks. API integration tests and a successful build do not substitute for these checks. Status is recorded in VALIDATION.md and PROGRESS.md.
