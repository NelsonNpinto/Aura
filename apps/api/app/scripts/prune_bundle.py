"""Build step: delete packages and assets the deployed API never loads, to keep the api
function under the bundle budget (§B17; Vercel hard limit 500 MB, our gate 450 MB).

Each entry was checked on 2026-11-05 by removing it and running the test suite, a live router
call and fastembed embed + rerank:
- litellm proxy admin UI and Swagger bundle: only used by the LiteLLM proxy server, not the SDK.
- litellm rust_bridge native extension (~34 MB): optional; loader catches ImportError and the
  SDK falls back to pure Python.
- hf_xet (~11 MB): optional Xet transfer backend for huggingface_hub; models are pre-fetched.
- zstandard (~23 MB): optional for langsmith (falls back to uncompressed); AURA never sends
  traces to LangSmith (Langfuse is the tracing backend). Checked 2026-11-05 like the rest.
- boto3 / botocore / s3transfer (~31 MB): only for Bedrock, kept when ENABLE_BEDROCK=true.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PRUNE = [
    "litellm/proxy/_experimental",
    "litellm/proxy/swagger",
    "litellm/rust_bridge/_native.abi3.so",
    "hf_xet",
    "zstandard",
]
BEDROCK_ONLY = ["boto3", "botocore", "s3transfer"]


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def targets() -> list[str]:
    keep_bedrock = os.environ.get("ENABLE_BEDROCK", "").lower() in {"1", "true", "yes"}
    return PRUNE + ([] if keep_bedrock else BEDROCK_ONLY)


def main(site: str | None = None) -> None:
    if site is None:
        import litellm

        root = Path(litellm.__file__).resolve().parents[1]
    else:
        root = Path(site)
    freed = 0
    for rel in targets():
        p = root / rel
        if p.is_dir():
            freed += _size(p)
            shutil.rmtree(p)
        elif p.is_file():
            freed += _size(p)
            p.unlink()
    print(f"pruned {freed / 1e6:.1f} MB from {root}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
