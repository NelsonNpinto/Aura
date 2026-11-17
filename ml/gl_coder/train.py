"""Unsloth QLoRA fine-tune of the GL coder (§B15).

Runs on a free Colab T4 or a Kaggle GPU session; it is not imported by the API and nothing here
is installed into the serving bundle (no torch on Vercel, §B4).

    python ml/gl_coder/train.py --data /kaggle/input/gl-coder --out ./outputs

Training is on completions only (the prompt is masked), the seed and every hyper-parameter are
logged next to the adapter, and the dataset version is written into the run config so the model
registry can trace model -> dataset.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Any

BASE_MODEL = "unsloth/Qwen3.5-2B-Instruct"
FALLBACKS = ("unsloth/Qwen3.5-0.8B-Instruct", "unsloth/Qwen3.5-4B-Instruct")
SEED = 20261117


def config(args: argparse.Namespace, dataset_version: str) -> dict[str, Any]:
    return {
        "base_model": args.base_model,
        "dataset_version": dataset_version,
        "seed": SEED,
        "max_seq_length": 1024,
        "lora": {"r": 16, "alpha": 32, "dropout": 0.0, "bias": "none"},
        "target_modules": [
            "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
        ],
        "train": {
            "epochs": args.epochs,
            "per_device_train_batch_size": 2,
            "gradient_accumulation_steps": 4,
            "learning_rate": 2e-4,
            "warmup_ratio": 0.05,
            "lr_scheduler_type": "linear",
            "optim": "adamw_8bit",
            "weight_decay": 0.01,
            "train_on_completions_only": True,
        },
        "quantization": {"load_in_4bit": True},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, help="folder with train/val/test.jsonl + VERSION")
    parser.add_argument("--out", default="./outputs")
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--push-to", default="", help="HF repo id for the adapter")
    parser.add_argument("--dry-run", action="store_true", help="write the config and stop")
    args = parser.parse_args()

    data = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dataset_version = (data / "VERSION").read_text(encoding="utf-8").strip()
    cfg = config(args, dataset_version)
    (out / "run_config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    if args.dry_run:
        print(json.dumps(cfg, indent=2))
        return

    random.seed(SEED)
    os.environ.setdefault("PYTHONHASHSEED", str(SEED))

    from datasets import load_dataset  # noqa: PLC0415  (training-only dependency)
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import train_on_responses_only

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg["base_model"],
        max_seq_length=cfg["max_seq_length"],
        load_in_4bit=cfg["quantization"]["load_in_4bit"],
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=cfg["lora"]["r"],
        lora_alpha=cfg["lora"]["alpha"],
        lora_dropout=cfg["lora"]["dropout"],
        bias=cfg["lora"]["bias"],
        target_modules=cfg["target_modules"],
        random_state=SEED,
    )

    splits = load_dataset(
        "json",
        data_files={
            "train": str(data / "train.jsonl"),
            "validation": str(data / "val.jsonl"),
        },
    )

    def to_text(batch: dict[str, Any]) -> dict[str, Any]:
        return {
            "text": [
                tokenizer.apply_chat_template(m, tokenize=False) for m in batch["messages"]
            ]
        }

    splits = splits.map(to_text, batched=True)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=splits["train"],
        eval_dataset=splits["validation"],
        args=SFTConfig(
            output_dir=str(out / "checkpoints"),
            num_train_epochs=cfg["train"]["epochs"],
            per_device_train_batch_size=cfg["train"]["per_device_train_batch_size"],
            gradient_accumulation_steps=cfg["train"]["gradient_accumulation_steps"],
            learning_rate=cfg["train"]["learning_rate"],
            warmup_ratio=cfg["train"]["warmup_ratio"],
            lr_scheduler_type=cfg["train"]["lr_scheduler_type"],
            optim=cfg["train"]["optim"],
            weight_decay=cfg["train"]["weight_decay"],
            logging_steps=5,
            seed=SEED,
            report_to="none",
            dataset_text_field="text",
            max_seq_length=cfg["max_seq_length"],
        ),
    )
    # Train on completions only: the prompt is masked so the loss comes from the JSON answer.
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )
    stats = trainer.train()

    (out / "train_log.json").write_text(
        json.dumps(
            {
                "dataset_version": dataset_version,
                "loss": getattr(stats, "training_loss", None),
                "steps": getattr(stats, "global_step", None),
                "config": cfg,
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    model.save_pretrained(str(out / "adapter"))
    tokenizer.save_pretrained(str(out / "adapter"))

    if args.push_to:
        model.push_to_hub(args.push_to, token=os.environ.get("HF_TOKEN"))
        tokenizer.push_to_hub(args.push_to, token=os.environ.get("HF_TOKEN"))
        # Merged weights and GGUF builds for the quantization comparison (§B15 evaluation).
        model.save_pretrained_merged(str(out / "merged"), tokenizer, save_method="merged_16bit")
        for quant in ("q8_0", "q4_k_m"):
            model.save_pretrained_gguf(str(out / f"gguf-{quant}"), tokenizer, quantization_method=quant)

    print(json.dumps({"dataset_version": dataset_version, "out": str(out)}, indent=2))


if __name__ == "__main__":
    main()
