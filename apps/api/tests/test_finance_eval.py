import json
from types import SimpleNamespace

from app.api.v1.copilot import CaseAnswer, case_evidence, citation_ids
from app.domain.procurement import EvidenceDocument, compare
from app.evaluation import finance
from app.schemas.llm_outputs import FinanceClaim, FinanceVerdict
from app.services.pdf import extract_text


async def test_fixture_gate_rejects_citation_regression(monkeypatch, tmp_path):
    baseline = await finance.run(live=False, delay=0)
    assert baseline["gate_passed"]
    assert baseline["human_calibration"] is None
    assert all(row["citation_valid"] for row in baseline["results"])
    assert any(row["passed"] is False for row in baseline["results"])

    relative = "finance_copilot/v1/cases.json"
    data = json.loads((finance.datasets_root() / relative).read_text(encoding="utf-8"))
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(finance, "datasets_root", lambda: tmp_path)

    same_snapshot = await finance.run(live=False, delay=0)
    assert same_snapshot["dataset_sha256"] == baseline["dataset_sha256"]

    candidate = data["cases"][0]["candidates"][0]
    candidate["answer"] = candidate["answer"].replace("[comparison]", "[invented_receipt]")
    path.write_text(json.dumps(data), encoding="utf-8")
    regression = await finance.run(live=False, delay=0)
    assert not regression["gate_passed"]
    assert regression["failed_expected_passes"] == ["quantity-hold/supported"]
    assert regression["results"][0]["reason"] == "invalid_citation"


async def test_finance_gate_fails_closed_when_models_are_unavailable(monkeypatch):
    class UnavailableRouter:
        async def run(self, *args):
            raise TimeoutError

    monkeypatch.setattr(finance, "evaluation_router", lambda: (UnavailableRouter(), "test-prompt"))
    report = await finance.run(live=True, delay=0)
    assert not report["gate_passed"]
    assert len(report["unscored"]) == len(report["results"]) == 12
    assert {result["error"] for result in report["results"]} == {"TimeoutError"}


async def test_finance_live_runner_grades_generated_copilot_answers(monkeypatch):
    dataset = finance.Dataset.model_validate_json(
        (finance.datasets_root() / "finance_copilot/v1/cases.json").read_bytes()
    )
    cases = {case.question: case for case in dataset.cases}

    class ScriptedRouter:
        async def run(self, task, variables, _context):
            case = cases[variables["question"]]
            if task == "copilot_case":
                answer = next(
                    candidate.answer for candidate in case.candidates if candidate.expected_pass
                )
                parsed = CaseAnswer(
                    answer=answer,
                    evidence_ids=sorted(citation_ids(answer)),
                    needs_more_evidence=False,
                )
                return SimpleNamespace(parsed=parsed, public=lambda: {"model": "scripted-copilot"})
            assert task == "finance_judge"
            candidate = next(c for c in case.candidates if c.answer == variables["answer"])
            return SimpleNamespace(
                parsed=candidate.fixture,
                model="scripted-judge",
                prompt_version=1,
                latency_ms=2,
                est_cost_microusd=0,
                fallback_reason=None,
            )

    monkeypatch.setattr(finance, "evaluation_router", lambda: (ScriptedRouter(), "test-prompt"))
    report = await finance.run(live=True, delay=0)
    generated = [row for row in report["results"] if row["kind"] == "generated_answer"]
    assert report["gate_passed"]
    assert len(generated) == len(dataset.cases)
    assert all(row["copilot"]["model"] == "scripted-copilot" for row in generated)
    assert all(row["model"] == "scripted-judge" for row in generated)


def test_finance_scoring_rejects_false_claims_and_invalid_judge_sources():
    claim = FinanceClaim(
        claim="Finance rejected the invoice",
        verdict="insufficient_evidence",
        source_ids=["status"],
        reason="The status only shows an unresolved discrepancy.",
    )
    verdict = FinanceVerdict(claims=[claim], missing_required_facts=[])
    assert finance.score(verdict, {"status"}) == (False, None)
    claim.source_ids = ["invented"]
    assert finance.score(verdict, {"status"}) == (None, "judge_invalid_source")


def test_copilot_exposes_payment_evidence_independently_of_approval_status():
    state = {"documents": {}, "status": "approved_for_payment", "revision": 3, "payment": None}
    assert case_evidence(state)["payment"] == {"recorded": False}
    state.update(status="paid", payment={"date": "2026-11-10", "reference": "SIM-8404"})
    assert case_evidence(state)["payment"] == state["payment"]


def test_copilot_links_unresolved_comparison_findings_to_the_correction_hold():
    state = {
        "documents": {},
        "status": "needs_correction",
        "revision": 3,
        "comparison": {"matched": False, "findings": [{"code": "HEADER_MISMATCH"}]},
    }
    status = case_evidence(state)["status"]
    assert status["status"] == "needs_correction"
    assert "on hold for correction" in status["explanation"]
    assert "before approval" in status["explanation"]

    state["comparison"] = {"matched": True, "findings": []}
    assert "explanation" not in case_evidence(state)["status"]


def test_copilot_derives_same_currency_difference_without_changing_stored_comparison():
    finding = {"code": "PRICE_VARIANCE", "po_minor": 4500, "invoice_minor": 5200}
    state = {
        "documents": {"po": {"currency": "USD"}, "invoice": {"currency": "USD"}},
        "status": "needs_correction",
        "revision": 3,
        "comparison": {"findings": [finding]},
    }
    assert case_evidence(state)["comparison"]["findings"] == [
        {**finding, "currency": "USD", "difference_minor": 700}
    ]
    assert "difference_minor" not in finding
    state["documents"]["invoice"]["currency"] = "GBP"
    assert case_evidence(state)["comparison"]["findings"] == [finding]


def test_copilot_calculates_unreceived_quantity_with_decimal_precision():
    finding = {"code": "QUANTITY_SHORTFALL", "invoiced": "40.25", "received": "30.10"}
    state = {
        "documents": {},
        "status": "needs_correction",
        "revision": 3,
        "comparison": {"findings": [finding]},
    }
    assert case_evidence(state)["comparison"]["findings"] == [
        {**finding, "unreceived_quantity": "10.15"}
    ]
    assert "unreceived_quantity" not in finding


def test_purchasing_demo_documents_match_the_quantity_hold_and_correction():
    folder = finance.datasets_root() / "finance_copilot/v1"
    dataset = finance.Dataset.model_validate_json((folder / "cases.json").read_bytes())
    case = next(case for case in dataset.cases if case.id == "quantity-hold")
    documents = {key: doc.model_dump(mode="json") for key, doc in case.documents.items()}
    assert not compare(dict(documents))["matched"]
    corrected = documents["receipt"]
    priced_line = "FILTER-02 Air handler filter 40 USD 45.00 USD 1,800.00"
    for filename, expected in (
        ("01-purchase-order-8401.pdf", ["PO-8401", priced_line]),
        ("02-vendor-invoice-8401.pdf", ["INV-8401", "PO-8401", priced_line]),
        ("03-goods-receipt-8401.pdf", ["GRN-8401", "PO-8401", "FILTER-02 Air handler filter 30"]),
        (
            "04-corrected-receipt-8401.pdf",
            ["GRN-8401-R1", "PO-8401", "FILTER-02 Air handler filter 40"],
        ),
    ):
        pdf = extract_text((folder / "documents" / filename).read_bytes(), max_pages=1)
        assert not pdf.hidden
        assert all(value in pdf.visible_text.splitlines() for value in expected)
    corrected["number"] = "GRN-8401-R1"
    corrected["lines"][0]["quantity"] = "40"
    EvidenceDocument.model_validate(corrected)
    assert compare(dict(documents))["matched"]
