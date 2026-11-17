"""Publish the GL-coder dataset to the Hugging Face Hub (§B15).

Requires HF_TOKEN with write access (HC-3). The dataset is public and labelled synthetic; the
dataset card carries the version hash, the split sizes and the caveats.

    python -m ml.gl_coder.publish_dataset --path /tmp/gl-coder --repo owner/gl-coder-synthetic
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("HF_TOKEN is not set (HC-3): nothing published.", file=sys.stderr)
        sys.exit(1)

    from huggingface_hub import HfApi

    path = Path(args.path)
    version = (path / "VERSION").read_text(encoding="utf-8").strip()
    api = HfApi(token=token)
    api.create_repo(args.repo, repo_type="dataset", exist_ok=True, private=args.private)
    api.upload_folder(
        repo_id=args.repo,
        repo_type="dataset",
        folder_path=str(path),
        commit_message=f"gl-coder dataset {version}",
    )
    print(json.dumps({"repo": args.repo, "version": version, "status": "published"}, indent=2))


if __name__ == "__main__":
    main()
