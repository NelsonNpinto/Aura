# Tax Guide (synthetic)

## United States
Most vendors in this demo do not charge sales tax on B2B services. Where sales tax appears it
must match the rate on the PO.

## India — GST
Indian vendors charge GST at 18% on the goods and services in this demo. The vendor GSTIN is a
15-character identifier. Where an e-invoice IRN and signed QR code are present, both are
validated. Tax deducted at source (TDS) is withheld at 2% on contractor services and 10% on
professional fees, and the net amount is paid to the vendor.

## European Union — VAT
German vendors charge VAT at 19%. Invoices must show the vendor VAT ID.

## United Kingdom — VAT
UK vendors charge VAT at 20%.

## Tax mismatches
If the tax on an invoice differs from the expected rate, the invoice is routed to an approver
with a TAX_MISMATCH flag.
