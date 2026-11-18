# ADR-008: Fine-tuning the GL coder and serving it on free GPU

- **Status:** accepted
- **Date:** 2026-11-17

## Decision

**Task.** GL coding only. It is the one step where a small specialist is plausibly better than a
general model: the label space is a fixed chart of accounts, the input is short, and the output
is strictly structured. Extraction and policy reasoning stay on the general chain.

**Training.** Unsloth QLoRA on Qwen3.5-2B (fallbacks 0.8B / 4B), 4-bit, **trained on completions
only** so the loss comes from the JSON answer rather than the prompt. Seed, config, loss and
dataset version are written next to the adapter. It runs on a free Colab T4 or Kaggle GPU;
`retrain.yml` triggers Kaggle through its API, and Colab is the documented manual path.

**Data.** Generator ground truth, plus human GL overrides from `ap.feedback`, plus paraphrase
augmentation from **open-weight models only** — the Gemini terms forbid using its output to
develop competing models, so the router task is marked `open_weight_only` and the builder
asserts it. The test split is held out **by vendor**, chosen greedily so every test label still
appears in training; `check_dataset.py` fails the build on vendor leakage, duplicate line text
across splits, or an unseen test label.

**Serving.** A Gradio app on a free ZeroGPU Space, called by the router as
`specialist/gl-coder` over the Space's HTTP API — no extra client dependency, and no torch in
the serving bundle. The free allowance is about 5 GPU-minutes a day, so:

- `@spaces.GPU(duration=20)` instead of the 60 s default;
- the model loads once, outside the GPU-scoped function;
- **all lines of an invoice go in one call**, so one invoice costs one reservation;
- the router applies an 18 s timeout and falls back to the general chain on timeout, cold start
  or quota exhaustion, recording `fallback_reason`.

Modal + vLLM is documented as an alternative and left **off**: it can bill beyond its credits,
which the $0 constraint forbids.

**Promotion.** `ai.model_versions` records dataset version → adapter revision → eval metrics →
status → who promoted it. A candidate must beat production on the held-out split and pass the
golden-set gates, then run as a canary (20% by default) with online metrics, before a human
promotes it. Promotion and rollback are audited. `ENABLE_SPECIALIST=false` turns the whole thing
off without a code change.

## Alternatives considered

- **Fine-tuning extraction instead.** Much larger label space, vision needed for scans, and a
  wrong extraction is more dangerous than a wrong GL code. The deterministic validators would
  catch less.
- **Hosting the adapter on the API.** Impossible inside the free Vercel bundle: torch alone
  breaks the size budget and the CPU allowance.
- **Serving with Modal/vLLM.** Better latency, real billing risk.
- **Skipping fine-tuning.** Tempting given 38 unique examples. Kept because the end-to-end loop —
  correction → dataset → training → gate → canary → promotion → lineage — is the thing worth
  demonstrating, and the model card states the data limit plainly rather than hiding it.

## Consequences

- First call after idle is slow and usually falls back; that is designed for, not an incident.
- The dataset is small, so early measured gains may be negative. They will be published as
  measured either way (`docs/MODEL_CARD.md`).
- Training cannot run in this repository's CI: it needs HC-3 credentials and a GPU session.
