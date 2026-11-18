"""Trigger the Unsloth training notebook on a free Kaggle GPU (§B15).

Kaggle gives roughly 30 GPU-hours a week to a phone-verified account. This pushes the kernel in
`ml/gl_coder/kaggle/` and starts it; the adapter is pushed to the Hub by the kernel itself.
Colab remains the manual fallback.

    python ml/gl_coder/kaggle_run.py --dataset-version <version>
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

KERNEL_DIR = Path(__file__).resolve().parent / "kaggle"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--slug", default=os.environ.get("KAGGLE_KERNEL_SLUG", ""))
    args = parser.parse_args()

    if not (os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY")):
        print("Kaggle credentials are not configured (HC-3). Use the Colab notebook.", file=sys.stderr)
        sys.exit(1)
    slug = args.slug or f"{os.environ['KAGGLE_USERNAME']}/aura-gl-coder"

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for file in KERNEL_DIR.glob("*"):
            (work / file.name).write_bytes(file.read_bytes())
        metadata = json.loads((work / "kernel-metadata.json").read_text(encoding="utf-8"))
        metadata["id"] = slug
        metadata["title"] = "AURA GL coder"
        (work / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        (work / "DATASET_VERSION").write_text(args.dataset_version + "\n", encoding="utf-8")
        result = subprocess.run(  # noqa: S603  (fixed argv, no shell)
            ["kaggle", "kernels", "push", "-p", str(work)],
            capture_output=True,
            text=True,
            check=False,
        )
    print(result.stdout or result.stderr)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
