# Model card — AURA GL coder

> **Status: not yet trained.** The pipeline is complete and runnable; the training run needs the
> Hugging Face and Kaggle credentials from HC-3 plus a free GPU session. Every metric table below
> is therefore empty, and the fields read `not measured`. Nothing in this card is projected — the
> numbers appear only when a run produces them.

## Overview

| | |
|---|---|
| **Task** | Assign a general-ledger account and cost center to one invoice line |
| **Input** | Line description, vendor context, unit price, currency, chart of accounts |
| **Output** | `{"gl_account", "cost_center", "rationale"}` |
| **Base model** | `unsloth/Qwen3.5-2B-Instruct` (fallbacks: 0.8B, 4B) |
| **Method** | QLoRA (Unsloth), 4-bit, trained on completions only |
| **Serving** | Gradio app on a free Hugging Face ZeroGPU Space, called by the router as `specialist/gl-coder` |
| **Licence** | Apache-2.0 (adapter); base model keeps its own licence |

## Intended use

Inside the AURA demo, to code invoice lines that have no matching purchase-order line. It is one
step of a workflow whose decisions are made by deterministic code: a wrong GL code produces a
low-confidence line that goes to human review, not a wrong payment.

**Not intended for** real ledgers, tax or accounting advice, or any decision without a human in
the loop. It has never been evaluated on real accounting data.

## Training data

Built by `ml/gl_coder/build_dataset.py` from three sources:

1. **Generator ground truth** — synthetic invoice lines with known GL codes
   (`evals/datasets/gl_coding/raw.jsonl`). After deduplication this is **38 unique examples**:
   a small set, and that limit is the single most important caveat on this card.
2. **Human corrections** — GL overrides recorded in the app (`ap.feedback`), which is what makes
   the feedback → retrain → promote loop real rather than decorative.
3. **Paraphrase augmentation** — line descriptions rewritten by an **open-weight** model only.
   The Gemini API terms forbid using its output to develop competing models, and the router task
   `paraphrase_data` is marked `open_weight_only`, which the builder asserts before augmenting.

Splits are **held out by vendor** and chosen so that every GL account in the test split still
appears in training; `ml/gl_coder/check_dataset.py` fails the build on vendor leakage, duplicate
line text across splits, or a test label never seen in training.

| Split | Rows (generator only) |
|---|---|
| train | 30 |
| val | 3 |
| test | 5 |

The published dataset version is a hash of the split files, recorded with every model version so
a model can always be traced back to the exact data it saw.

## Evaluation plan

`ml/gl_coder/evaluate.py` scores four systems on the same vendor-held-out test split:

| System | Status |
|---|---|
| Base small model, zero-shot with the chart of accounts | not measured |
| Teacher (strongest configured free model), zero-shot | not measured |
| Current production router chain | not measured |
| Fine-tuned specialist | not measured |

Metrics: accuracy, macro-F1, cost-center accuracy, JSON validity, p50/p95 latency, and estimated
cost per 1,000 lines at list prices. A system whose provider is not configured is reported as
`not_measured`, never as zero.

### Quantization comparison

| Build | Accuracy | Latency (CPU) | Size |
|---|---|---|---|
| 16-bit merged | not measured | not measured | not measured |
| GGUF Q8_0 | not measured | not measured | not measured |
| GGUF Q4_K_M | not measured | not measured | not measured |

### Real-world check

A public spending dataset with expense categories (licence permitting) is to be scored next to
the synthetic test set, so results are not judged only on data from our own generator. **Not yet
run.**

## Serving and limits

- Free ZeroGPU gives roughly **5 GPU-minutes a day** per token. The Space reserves 20 s per call
  (`@spaces.GPU(duration=20)`) instead of the 60 s default, loads the model outside the GPU
  function, and accepts **all lines of an invoice in one call**.
- The router applies a 15–20 s timeout and falls back to the general chain on timeout, cold
  start or quota exhaustion. That fallback is normal operation and is recorded as
  `fallback_reason`.
- `ENABLE_SPECIALIST=false` disables the specialist entirely without a code change.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Overfitting to synthetic phrasing | Vendor-held-out test split; paraphrase augmentation; the caveat is stated here and on the Hub |
| Small dataset | Stated plainly above; the loop adds real corrections over time |
| Hallucinated GL codes | Output validated against the chart of accounts; unknown codes score 0 confidence and route to review |
| Injection inside line text | The line is untrusted data and is spotlighted; the Space's system prompt says so too |
| Silent regression after retraining | A candidate must beat production on held-out test and pass the golden-set gates, then run as a canary before manual promotion |

## Lineage

`ai.model_versions` records, for every version: dataset version → adapter repo and revision →
eval metrics → status (`candidate` / `canary` / `production` / `retired`) → who promoted it and
when. `/api/v1/models/lineage/{id}` returns that chain together with the runs that used the model.

## Changelog

| Date | Change |
|---|---|
| 2026-11-17 | Pipeline, serving app, registry and promotion flow implemented. No training run yet (HC-3 open). |
