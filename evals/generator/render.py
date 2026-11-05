"""Render InvoiceSpec → PDF (fpdf2) and scanned PNG variants (pypdfium2 + Pillow noise/rotation)."""

from __future__ import annotations

import io
import random

from fpdf import FPDF
from invoices import InvoiceSpec

SYM = {"USD": "$", "EUR": "EUR ", "INR": "INR ", "GBP": "GBP "}


def money(minor: int, cur: str) -> str:
    neg = minor < 0
    s = f"{abs(minor) / 100:,.2f}"
    return f"{'-' if neg else ''}{SYM.get(cur, cur + ' ')}{s}"


def _ascii(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1")


def render_pdf(s: InvoiceSpec) -> bytes:
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_creator("AURA synthetic generator")
    pdf.set_title(f"SYNTHETIC {s.doc_type} {s.invoice_number}")
    title = "CREDIT NOTE" if s.doc_type == "credit_note" else "INVOICE"
    if s.layout == 0:
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 10, _ascii(s.vendor_name), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=9)
        pdf.cell(0, 5, _ascii(s.vendor_address), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 5, f"Tax ID: {s.vendor_tax_id}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        meta = [("Invoice No", s.invoice_number), ("Invoice Date", s.invoice_date), ("Due Date", s.due_date),
                ("PO Number", s.po_number or "-"), ("Currency", s.currency)]
        for k, v in meta:
            pdf.cell(35, 6, k + ":")
            pdf.cell(0, 6, _ascii(v), new_x="LMARGIN", new_y="NEXT")
    elif s.layout == 1:
        pdf.set_font("Helvetica", "B", 22)
        pdf.cell(100, 12, title)
        pdf.set_font("Helvetica", size=10)
        pdf.cell(0, 6, f"# {s.invoice_number}", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(100, 6, "")
        pdf.cell(0, 6, f"Date {s.invoice_date}", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(100, 6, "")
        pdf.cell(0, 6, f"Payment due {s.due_date}", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 6, "From", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 5, _ascii(f"{s.vendor_name}\n{s.vendor_address}\nTax ID {s.vendor_tax_id}"))
        pdf.ln(2)
        pdf.cell(0, 6, f"Purchase order: {s.po_number or 'none'}    Currency: {s.currency}", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.set_fill_color(230, 236, 245)
        pdf.rect(0, 0, 210, 32, style="F")
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_xy(10, 8)
        pdf.cell(120, 8, _ascii(s.vendor_name))
        pdf.set_font("Helvetica", size=9)
        pdf.set_xy(10, 17)
        pdf.cell(120, 5, _ascii(f"{s.vendor_address} | VAT/Tax {s.vendor_tax_id}"))
        pdf.set_xy(140, 8)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(60, 8, f"{title} {s.invoice_number}", align="R")
        pdf.set_xy(10, 38)
        pdf.set_font("Helvetica", size=10)
        pdf.cell(0, 6, f"Issued {s.invoice_date} - Due {s.due_date} - PO {s.po_number or 'N/A'} - {s.currency}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    # line table
    pdf.set_font("Helvetica", "B", 9)
    widths = [90, 18, 16, 32, 34]
    for h, wd in zip(["Description", "Qty", "Unit", "Unit price", "Amount"], widths, strict=True):
        pdf.cell(wd, 7, h, border=1)
    pdf.ln()
    pdf.set_font("Helvetica", size=9)
    for ln in s.lines:
        desc = _ascii(ln.description)
        if s.injection_style == "line":
            pdf.set_font("Helvetica", size=6)
        pdf.cell(widths[0], 7, desc[:95], border=1)
        pdf.set_font("Helvetica", size=9)
        pdf.cell(widths[1], 7, str(ln.quantity), border=1, align="R")
        pdf.cell(widths[2], 7, ln.uom, border=1)
        pdf.cell(widths[3], 7, money(ln.unit_price_minor, s.currency), border=1, align="R")
        pdf.cell(widths[4], 7, money(ln.amount_minor, s.currency), border=1, align="R")
        pdf.ln()
    pdf.ln(2)
    tax_label = {"INR": "GST", "EUR": "VAT", "GBP": "VAT"}.get(s.currency, "Sales tax")
    for k, v in (("Subtotal", s.subtotal_minor), (tax_label, s.tax_minor), ("Total due", s.total_minor)):
        pdf.cell(sum(widths[:3]), 6, "")
        pdf.set_font("Helvetica", "B" if k == "Total due" else "", 10)
        pdf.cell(widths[3], 6, k)
        pdf.cell(widths[4], 6, money(v, s.currency), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Remit to", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(0, 5, f"Bank account: {s.bank_account}   Routing: {s.bank_routing}", new_x="LMARGIN", new_y="NEXT")
    if s.pii_note:
        pdf.ln(3)
        pdf.multi_cell(0, 5, _ascii(s.pii_note))
    if s.injection and s.injection_style == "visible":
        pdf.ln(3)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _ascii("Note: " + s.injection))
    if s.injection and s.injection_style == "white":
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", size=9)
        pdf.set_xy(12, 270)
        pdf.cell(0, 5, _ascii(s.injection))
        pdf.set_text_color(0, 0, 0)
    if s.injection and s.injection_style == "tiny":
        pdf.set_font("Helvetica", size=1)
        pdf.set_xy(12, 275)
        pdf.cell(0, 1, _ascii(s.injection))
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(120, 120, 120)
    pdf.set_xy(10, 285)
    pdf.cell(0, 4, "SYNTHETIC DOCUMENT - generated for the AURA demo. Not a real invoice.")
    return bytes(pdf.output())


def render_scan_png(pdf_bytes: bytes, seed: int) -> bytes:
    """Rasterise page 1, rotate slightly, add noise and blur: a 'scanned' invoice with no text layer."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    rng = random.Random(seed)
    doc = pdfium.PdfDocument(pdf_bytes)
    img = doc[0].render(scale=1.6).to_pil().convert("L")
    doc.close()
    img = img.rotate(rng.uniform(-2.5, 2.5), expand=True, fillcolor=255)
    px = img.load()
    w, h = img.size
    for _ in range(w * h // 60):
        x, y = rng.randrange(w), rng.randrange(h)
        px[x, y] = rng.choice([0, 60, 200, 255])
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    out = io.BytesIO()
    Image.Image.save(img, out, format="PNG", optimize=True)
    return out.getvalue()
