# Evaluation evidence

The workflow evaluator compares expected route, status and required flags with actual persisted workflow outcomes. It reads approval packets for interrupted runs because they have not executed finalize.

```bash
source scripts/local-env.sh
cd apps/api
uv run aura-eval run --dataset demo --gate --output /tmp/aura-workflow-report.json
```

The default uses fixture responses and an isolated synthetic evaluation organization. It seeds synthetic ERP data and stores the report in `ai.dataset_runs`. It makes no live model calls. `--live` explicitly enables provider calls and consumes the configured quotas. Run against your local database; do not point development commands at production unintentionally.

The `demo` dataset contains five scripted cases. `golden_invoices` selects the larger versioned set; the default limit is 20, bounded at 250. This implementation takes cases in file order, so a prefix run is not a representative or stratified sample. No golden-set accuracy claim is made until that run is measured. Cases with dependencies may require the complete set.

The CLI verifies source file SHA-256 values, records dataset and selected-case snapshot hashes, and returns a nonzero exit code with `--gate` when any route/status/flag check fails or an inappropriate automatic route appears. A unit test deliberately supplies an incorrect automatic route to demonstrate gate failure.

CI runs the five-case fixture gate and uploads its JSON artifact. Only explicitly public, synthetic reports are served by `/api/v1/eval-report`; private ad hoc judgments are filtered out. CI's local database is ephemeral, so its report artifact does not automatically appear in the production database.

## Actual results on 5 November 2026

- Five-case fixture workflow gate: 5/5 passed, zero incorrect automatic routes, zero run errors. This is workflow logic evidence, not model accuracy.
- One live Groq `gpt-oss-120b` judgment on synthetic marketing content: score 0.2, failed; identified unsupported 48-hour battery life and a 30% discount against supplied facts of 8 hours and a maximum 10% discount. This single case does not establish aggregate judge reliability.
- No genuine human calibration labels have been supplied as part of this implementation. Calibration starts unmeasured; test fixtures are confined to test data and do not represent production reviews.

## Judge workbench

`POST /api/v1/quality/judge` validates structured model output and stores the judgment privately in the caller's workspace. Unsupported claims force failure regardless of average score. Faithfulness is unavailable without context; when neither context nor reference exists, the aggregate result remains unscored. Provider/validation failures remain unscored with an error.

Human labels are stored under the actual reviewer's identity in `ai.judge_labels`. Each person has one current label per judgment. Calibration uses majority human verdicts from at most the latest 100 judgments, excludes ties/unscored judgments, and reports agreement, Cohen's kappa, false passes and false fails. Kappa is undefined when chance agreement equals one.

## Still required

Full golden-set and extraction benchmarks, representative held-out data, larger marketing regression datasets, semantic citation-support evaluation, model/prompt experiments, reviewed failures promoted into datasets, live nightly/weekly evaluation jobs and actual human calibration. None are implied by the five-case fixture result.
