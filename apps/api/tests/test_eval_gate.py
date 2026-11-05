from app.evaluation.cli import assess


def test_gate_catches_false_automatic_approval_and_missing_evidence():
    expected = {
        "route": "approval",
        "status": "awaiting_approval",
        "flags": ["BANK_ACCOUNT_MISMATCH"],
    }
    result = assess(expected, {"route": "auto", "status": "posted", "flags": []})
    assert result["false_auto_post"] and not result["passed"]
    result = assess(expected, {"route": "approval", "status": "awaiting_approval", "flags": []})
    assert not result["passed"] and result["missing_flags"] == ["BANK_ACCOUNT_MISMATCH"]
