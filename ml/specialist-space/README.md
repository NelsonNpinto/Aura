---
title: AURA GL Coder
emoji: 🧾
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: 5.52.0
app_file: app.py
pinned: false
license: apache-2.0
short_description: Fine-tuned GL coding specialist for the AURA finance demo (synthetic data)
---

# AURA GL coder (specialist)

Serves the fine-tuned GL-coding model for [AURA](https://github.com/NelsonNpinto/Aura) on a
free ZeroGPU Space.

## Budget

A free ZeroGPU token gives roughly **5 GPU-minutes a day**. This Space is built around that:

- `@spaces.GPU(duration=20)` — the default would reserve 60 s per call.
- The model loads once, outside the GPU-scoped function.
- Callers send **every line of an invoice in one request**, so one invoice costs one reservation.
- Greedy decoding and a short `max_new_tokens`.

AURA's router calls `predict` with a 15–20 s timeout and falls back to its general model chain
when the Space is cold or out of quota. That fallback is expected behaviour, not an incident.

## Configuration

| Variable | Meaning |
|---|---|
| `BASE_MODEL` | base model id (default `Qwen/Qwen3.5-2B-Instruct`) |
| `ADAPTER_REPO` | LoRA adapter repo; empty serves the base model |
| `GPU_SECONDS` | GPU reservation per call (default 20) |

## Data and limits

Training data is synthetic, generated for the AURA demo. Accuracy here does not transfer to a
real ledger. See `docs/MODEL_CARD.md` in the repository for measured results and caveats.
