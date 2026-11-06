import json

import pytest

from app.evaluation import marketing


async def test_fixture_gate_fails_on_an_unsupported_draft_that_slips_through(tmp_path, monkeypatch):
    baseline = await marketing.run()
    assert baseline["gate_passed"]
    assert baseline["human_calibration"] is None

    relative = "marketing/v1/cases.json"
    cases = json.loads((marketing.datasets_root() / relative).read_text(encoding="utf-8"))
    bad_case = next(case for case in cases if case["fixture_unsupported_claims"])
    bad_case["fixture_unsupported_claims"] = []
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cases), encoding="utf-8")
    monkeypatch.setattr(marketing, "datasets_root", lambda: tmp_path)

    report = await marketing.run()
    assert not report["gate_passed"]
    assert report["false_passes"] == [bad_case["id"]]


async def test_live_gate_requires_current_complete_labels_and_fails_unscored(tmp_path, monkeypatch):
    baseline = await marketing.run()
    labels = {
        "dataset_sha256": baseline["dataset_sha256"],
        "reviewer": "test-only",
        "cases": {
            case["id"]: {"passed": case["expected_pass"], "reason": "Unit test review fixture"}
            for case in baseline["results"]
        },
    }
    monkeypatch.setattr(marketing, "_live_results", _unscored_live_result)
    path = tmp_path / "labels.json"
    path.write_text(json.dumps({**labels, "dataset_sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(ValueError, match="current dataset snapshot"):
        await marketing.run(path)

    path.write_text(json.dumps(labels), encoding="utf-8")
    report = await marketing.run(path)
    assert report["errors"] == 1
    assert report["human_calibration"]["sample_size"] == report["case_count"] - 1
    assert not report["gate_passed"]


async def _unscored_live_result(cases, delay):
    return [
        {"id": case.id, "passed": None if index == 0 else case.expected_fixture_pass}
        for index, case in enumerate(cases)
    ]
