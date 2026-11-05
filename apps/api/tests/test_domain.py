"""Table-driven tests for deterministic domain rules (task 1.5, §B6, §B18)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.domain.approval import ApprovalMatrix, Level, required_approval
from app.domain.duplicates import PriorInvoice, find_duplicates, normalize_invoice_number
from app.domain.flags import Flag, Severity
from app.domain.matching import InvoiceLine, LineOutcome, POLine, convert_qty, three_way_match
from app.domain.money import FxRate, FxTable, MoneyError, parse_decimal, to_minor
from app.domain.risk import Route, decide
from app.domain.sod import Approver, InvoiceParties, check_sod

M = ApprovalMatrix()


# ---------------------------------------------------------------- money
@pytest.mark.parametrize(
    ("raw", "cur", "minor"),
    [
        ("1,234.50", "USD", 123450),
        ("1.234,50", "EUR", 123450),
        ("(12.00)", "USD", -1200),
        ("$ 99", "USD", 9900),
        ("12,5", "EUR", 1250),
        ("1 234.567", "USD", 123457),
        ("500", "JPY", 500),
        ("1,000", "USD", 100000),
    ],
)
def test_to_minor(raw, cur, minor):
    assert to_minor(raw, cur) == minor


@pytest.mark.parametrize("raw", ["", "abc", "12..3.4x", "NaN"])
def test_parse_rejects_junk(raw):
    with pytest.raises(MoneyError):
        parse_decimal(raw)


def test_fx_uses_latest_rate_on_or_before_date():
    fx = FxTable(
        "USD",
        [
            FxRate("USD", "EUR", date(2026, 1, 1), D("1.10")),
            FxRate("USD", "EUR", date(2026, 3, 1), D("1.20")),
        ],
    )
    assert fx.to_base(10000, "EUR", date(2026, 2, 15)) == 11000
    assert fx.to_base(10000, "EUR", date(2026, 3, 1)) == 12000
    with pytest.raises(MoneyError):
        fx.to_base(10000, "EUR", date(2025, 12, 31))


# ---------------------------------------------------------------- matching
PO = [
    POLine("PO-1", 1, "Laptop stand aluminium", D(10), 4500, received_qty=D(10)),
    POLine("PO-1", 2, "USB-C docking station", D(5), 12000, received_qty=D(3)),
    POLine("PO-1", 3, "Printer paper A4", D(10), 4800, uom="box12", received_qty=D(10)),
    POLine("PO-2", 1, "Consulting services March", D(20), 15000, uom="hour", is_service=True),
    POLine("PO-3", 1, "Office chairs", D(4), 25000, received_qty=D(0)),
]


def line(i, desc, qty, price, uom="each", po="PO-1"):
    return InvoiceLine(i, desc, D(qty), price, int(D(qty) * price), uom, po)


@pytest.mark.parametrize(
    ("inv", "expected"),
    [
        (line(0, "Laptop stand, aluminium", 10, 4500), LineOutcome.MATCHED),
        (
            line(0, "Laptop stand aluminium", 10, 4900),
            LineOutcome.MATCHED,
        ),  # +400 < $5 abs tolerance
        (line(0, "Laptop stand aluminium", 10, 5200), LineOutcome.PRICE_VARIANCE),
        (line(0, "USB-C docking station", 5, 12000), LineOutcome.QTY_VARIANCE),  # received 3
        (line(0, "Office chairs", 4, 25000, po="PO-3"), LineOutcome.NO_RECEIPT),
        (line(0, "Office chairs", 4, 25000, po="PO-9"), LineOutcome.NO_PO),
        (
            line(0, "Printer paper A4", 120, 400, uom="each"),
            LineOutcome.MATCHED,
        ),  # 120 each = 10 box12
        (line(0, "Printer paper A4", 2, 2400, uom="pallet"), LineOutcome.UOM_MISMATCH),
        (
            line(0, "Consulting services March", 20, 15000, uom="hour", po="PO-2"),
            LineOutcome.MATCHED,
        ),
    ],
)
def test_line_outcomes(inv, expected):
    r = three_way_match([inv], PO, invoice_subtotal_minor=inv.amount_minor)
    assert r.lines[0].outcome == expected, r.lines[0]


def test_service_line_needs_confirmation_not_receipt():
    r = three_way_match(
        [line(0, "Consulting services March", 10, 15000, "hour", "PO-2")],
        PO,
        invoice_subtotal_minor=150000,
    )
    assert r.lines[0].outcome == LineOutcome.MATCHED and r.lines[0].needs_service_confirmation


def test_multi_po_invoice_and_freight_within_tolerance():
    lines = [
        line(0, "Laptop stand aluminium", 10, 4500),
        line(1, "USB-C docking station", 3, 12000),
        InvoiceLine(2, "Freight charge", D(1), 1000, 1000),
    ]
    r = three_way_match(lines, PO, invoice_subtotal_minor=45000 + 36000 + 1000)
    assert [m.outcome for m in r.lines] == [
        LineOutcome.MATCHED,
        LineOutcome.MATCHED,
        LineOutcome.NON_PO_CHARGE,
    ]
    assert r.header_ok and not any("exceeds" in n for n in r.lines[2].notes)


def test_freight_above_tolerance_flagged():
    lines = [
        line(0, "Laptop stand aluminium", 10, 4500),
        InvoiceLine(1, "Shipping surcharge", D(1), 9000, 9000),
    ]
    r = three_way_match(lines, PO, invoice_subtotal_minor=54000)
    assert any("exceeds" in n for n in r.lines[1].notes)


def test_over_billing_across_invoices():
    po = [
        POLine(
            "PO-1", 1, "Laptop stand aluminium", D(10), 4500, received_qty=D(10), billed_qty=D(8)
        )
    ]
    r = three_way_match(
        [line(0, "Laptop stand aluminium", 5, 4500)], po, invoice_subtotal_minor=22500
    )
    assert r.lines[0].outcome == LineOutcome.QTY_VARIANCE and r.over_billed == ["PO-1#1"]


def test_header_total_tolerance():
    r = three_way_match(
        [line(0, "Laptop stand aluminium", 10, 4500)], PO, invoice_subtotal_minor=46000
    )
    assert not r.header_ok


def test_uom_conversion_both_directions():
    assert convert_qty(D(2), "box12", "each") == 24
    assert convert_qty(D(24), "each", "box12") == 2
    assert convert_qty(D(1), "pallet", "each") is None


# ---------------------------------------------------------------- duplicates
@pytest.mark.parametrize(
    ("a", "b"), [("INV-0042", "42"), ("inv 42", "INV-42"), ("#00042", "Invoice No. 42")]
)
def test_normalize_invoice_number(a, b):
    assert normalize_invoice_number(a) == normalize_invoice_number(b)


PRIOR = [PriorInvoice("i1", "v1", "INV-1042", 100000, "USD", date(2026, 10, 1))]


@pytest.mark.parametrize(
    ("vendor", "number", "total", "d", "kinds"),
    [
        ("v1", "inv 1042", 999, date(2026, 1, 1), ["exact"]),
        (
            "v2",
            "INV-1042",
            100000,
            date(2026, 10, 1),
            [],
        ),  # same number, other vendor: not a duplicate
        ("v1", "INV-1043", 100300, date(2026, 10, 20), ["fuzzy"]),
        ("v1", "INV-1043", 101000, date(2026, 10, 20), []),  # amount off by 1%
        ("v1", "INV-1043", 100000, date(2026, 12, 20), []),  # > 30 days
    ],
)
def test_duplicates(vendor, number, total, d, kinds):
    hits = find_duplicates(
        vendor_id=vendor,
        number=number,
        total_minor=total,
        currency="USD",
        invoice_date=d,
        prior=PRIOR,
    )
    assert [h.kind for h in hits] == kinds


# ---------------------------------------------------------------- approval matrix
@pytest.mark.parametrize(
    ("amount", "flags", "level", "callback"),
    [
        (50_000, [], Level.AUTO, False),
        (100_000, [], Level.AUTO, False),
        (100_001, [], Level.APPROVER, False),
        (1_000_000, [], Level.APPROVER, False),
        (1_000_001, [], Level.CONTROLLER, False),
        (50_000, ["NEW_VENDOR"], Level.APPROVER, False),
        (50_000, ["DUPLICATE_SUSPECTED"], Level.CONTROLLER, False),
        (50_000, ["BANK_ACCOUNT_MISMATCH"], Level.CONTROLLER, True),
        (50_000, ["PII_PRESENT"], Level.AUTO, False),
    ],
)
def test_approval_matrix(amount, flags, level, callback):
    req = required_approval(amount, [Flag(c) for c in flags], M)
    assert (req.level, req.callback_verification) == (level, callback)


def test_unknown_flag_is_never_low():
    assert Flag("SOMETHING_NEW").severity == Severity.MEDIUM


# ---------------------------------------------------------------- SoD
PARTIES = InvoiceParties(
    preparer_id="rahul", uploader_id="rahul", vendor_bank_last_editor_id="meera2"
)


@pytest.mark.parametrize(
    ("approver", "required", "amount", "codes"),
    [
        (Approver("priya", frozenset({"approver"})), Level.APPROVER, 500_000, []),
        (Approver("rahul", frozenset({"approver"})), Level.APPROVER, 500_000, ["SOD_PREPARER"]),
        (
            Approver("meera2", frozenset({"controller"})),
            Level.CONTROLLER,
            500_000,
            ["SOD_BANK_EDITOR"],
        ),
        (Approver("priya", frozenset({"approver"})), Level.CONTROLLER, 2_000_000, ["SOD_ROLE"]),
        (
            Approver("priya", frozenset({"approver"}), limit_minor=200_000),
            Level.APPROVER,
            500_000,
            ["SOD_LIMIT"],
        ),
        (Approver("meera", frozenset({"controller"})), Level.APPROVER, 500_000, []),
        (Approver("ann", frozenset({"clerk"})), Level.APPROVER, 500_000, ["SOD_ROLE"]),
    ],
)
def test_sod(approver, required, amount, codes):
    assert [v.code for v in check_sod(approver, PARTIES, required, amount)] == codes


# ---------------------------------------------------------------- risk routing (demo scenarios)
def _match(outcome_line, subtotal):
    return three_way_match([outcome_line], PO, invoice_subtotal_minor=subtotal)


def test_route_clean_invoice_auto_posts():
    d = decide(
        amount_base_minor=45000,
        flags=[],
        match=_match(line(0, "Laptop stand aluminium", 10, 4500), 45000),
        matrix=M,
    )
    assert d.route == Route.AUTO


def test_route_price_variance_is_exception():
    d = decide(
        amount_base_minor=52000,
        flags=[],
        match=_match(line(0, "Laptop stand aluminium", 10, 5200), 52000),
        matrix=M,
    )
    assert d.route == Route.EXCEPTION and "price_variance" in d.reasons[0]


def test_route_bank_change_goes_to_controller_even_if_clean():
    d = decide(
        amount_base_minor=45000,
        flags=[Flag("BANK_ACCOUNT_MISMATCH")],
        match=_match(line(0, "Laptop stand aluminium", 10, 4500), 45000),
        matrix=M,
    )
    assert d.route == Route.APPROVAL and d.approval and d.approval.level == Level.CONTROLLER
    assert d.approval.callback_verification


def test_route_injection_never_auto_posts():
    d = decide(amount_base_minor=100, flags=[Flag("INJECTION_DETECTED")], match=None, matrix=M)
    assert d.route == Route.APPROVAL and d.level == "high"


def test_route_errors_go_to_exception_never_auto():
    d = decide(amount_base_minor=100, flags=[], match=None, matrix=M, errors=["extraction failed"])
    assert d.route == Route.EXCEPTION


def test_missing_po_allowed_by_policy():
    m = _match(line(0, "Electricity October", 1, 30000, po="PO-X"), 30000)
    assert decide(amount_base_minor=30000, flags=[], match=m, matrix=M).route == Route.EXCEPTION
    assert (
        decide(amount_base_minor=30000, flags=[], match=m, matrix=M, missing_po_allowed=True).route
        == Route.AUTO
    )
