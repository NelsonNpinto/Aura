# Evaluation evidence

The workflow evaluator compares expected route, status and required flags with actual persisted workflow outcomes. It reads approval packets for interrupted runs because they have not executed finalize.

```bash
source scripts/local-env.sh
cd apps/api
uv run aura-eval run --dataset demo --gate --output /tmp/aura-workflow-report.json
```

The default uses fixture responses and an isolated synthetic evaluation organization. It seeds synthetic ERP data and stores the report in `ai.dataset_runs`. It makes no live model calls. `--live` explicitly enables provider calls and consumes the configured quotas. Run against your local database; do not point development commands at production unintentionally.

The `demo` dataset contains five scripted cases. `golden_invoices` selects the larger versioned set; the default limit is 20, bounded at 250. This implementation takes cases in file order, so a prefix run is not a representative or stratified sample. No golden-set accuracy claim is made until that run is measured. Cases with dependencies may require the complete set.

Larger runs now pause 2.1 seconds between invoices by default (`--delay`), while tool quotas remain enforced. Increase pacing if the selected cases make multiple calls to the same limited tool. Runtime node errors fail the case even if the expected route was also an exception. Only the reviewed `demo` suite is published automatically; larger suites stay private pending review.

The CLI verifies source file SHA-256 values, records dataset and selected-case snapshot hashes, and returns a nonzero exit code with `--gate` when any route/status/flag check fails or an inappropriate automatic route appears. A unit test deliberately supplies an incorrect automatic route to demonstrate gate failure.

CI runs the five-case fixture gate and uploads its JSON artifact. Only explicitly public, synthetic reports are served by `/api/v1/eval-report`; private ad hoc judgments are filtered out. CI's local database is ephemeral, so its report artifact does not automatically appear in the production database.

When no public database report exists, the API serves the explicitly published recorded local validation artifact under `evals/datasets/reports`. It retains its original timestamp, dataset hash and fixture label; original traces remain local. This lets a new deployment show genuine measured workflow evidence without fabricating or rerunning it.

## Actual results on 5 November 2026

- Five-case fixture workflow gate: 5/5 passed, zero incorrect automatic routes, zero run errors. This is workflow logic evidence, not model accuracy.
- One live Groq `gpt-oss-120b` judgment on synthetic marketing content: score 0.2, failed; identified unsupported 48-hour battery life and a 30% discount against supplied facts of 8 hours and a maximum 10% discount. This single case does not establish aggregate judge reliability.
- No genuine human calibration labels have been supplied as part of this implementation. Calibration starts unmeasured; test fixtures are confined to test data and do not represent production reviews.
- An initial unpaced 207-case fixture run matched 84 expected outcomes and failed its gate, with zero unexpected auto routes. This is **not a valid accuracy benchmark**: it encountered tool quotas, and some generator-labelled clean cases conflict with seeded duplicate or vendor/employee-bank checks. Its old runtime-error count did not include handled node errors; that reporting bug is now fixed. The original report is retained locally, excluded from public benchmark publication. The dataset needs expectation/dependency review and a paced rerun.

## Judge workbench

`POST /api/v1/quality/judge` validates structured model output and stores the judgment privately in the caller's workspace. Unsupported claims force failure regardless of average score. Faithfulness is unavailable without context; when neither context nor reference exists, the aggregate result remains unscored. Provider/validation failures remain unscored with an error.

Human labels are stored under the actual reviewer's identity in `ai.judge_labels`. Each person has one current label per judgment. Calibration uses majority human verdicts from at most the latest 100 judgments, excludes ties/unscored judgments, and reports agreement, Cohen's kappa, false passes and false fails. Kappa is undefined when chance agreement equals one.

## Marketing regression suite

Open **AI Quality → Compare judge versions** for a side-by-side example using the marketing
dataset. It shows the product facts, draft, expected verdict, and why a permissive candidate would
fail the gate. This simulation is available to guests. Quality reviewers can run a live comparison
with a valid review file and provider credentials. Select two distinct combinations of saved judge
prompt version and configured model. Each side uses its selected model with caching and fallbacks
disabled. The result evaluates the same gate rule, and GitHub Actions owns the deployment decision.

The synthetic pack in `evals/datasets/marketing/v1/cases.json` includes supported claims, inflated
specs and discounts, missing shipping qualifiers, and an invented certification. The fixture gate
exercises the same scoring policy as AI Quality. It uses simulated judge outputs, so it measures
whether the application handles those outputs correctly. Every pull request and deployment runs
this gate and publishes a JSON artifact.

From `apps/api`:

```sh
uv run aura-eval run --dataset marketing --gate
```

For live evaluation, first have a human read the facts and draft for each case and record an
independent pass/fail decision with a reason. Save the resulting JSON as
`evals/datasets/marketing/v1/human-labels.json`. Its top-level fields are `dataset_sha256` (copy from
the fixture report), `reviewer` (reviewer's name or agreed identifier), and `cases` (an object keyed
by case ID). Each case entry has a boolean `passed` and a nonempty `reason`. Both verdict classes
must be represented. Review the complete dataset again when the snapshot changes. Only use
synthetic, publishable product material in this repository.

With a migrated, seeded local database and a Groq or Gemini key in the git-ignored environment:

```sh
uv run aura-eval run --dataset marketing --live --gate --labels ../../evals/datasets/marketing/v1/human-labels.json
```

The live run calls the branch's configured judge without the response cache. It reports human–judge
agreement, kappa, false passes, false fails, unscored errors, and per-case model, prompt version,
latency and estimated cost when available. A false pass is a draft the human rejected and the judge
approved. Any disagreement or unscored case fails this small release suite.

To require the live suite before deploying from `main`, commit the completed review file, add a
repository Actions secret `GROQ_API_KEY` or `GEMINI_API_KEY`, and set the repository Actions variable
`AURA_MARKETING_LIVE_GATE` to `true`. The deployment calls CI before production migrations.
The live gate fails if enabled with missing or stale reviews, missing credentials, or failed
judgments. Pull requests run the fixture gate without credentials. Requiring the CI check for PR
merges is a repository branch protection setting.

## Still required

Full golden-set and extraction benchmarks, representative held-out data, genuine reviews and live results for the marketing suite, semantic citation-support evaluation, model/prompt experiments, reviewed failures promoted into datasets, and live nightly/weekly evaluation jobs.
