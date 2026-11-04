#!/usr/bin/env python3
"""Build from a metadata-free staging context, then start AURA. Useful on macOS external drives."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--observability", action="store_true")
parser.add_argument("--build-only", action="store_true")
args = parser.parse_args()
staging = (
    Path.home() / "Library/Caches/aura/build-context"
    if __import__("sys").platform == "darwin"
    else Path.home() / ".cache/aura/build-context"
)


def copy_sources(source, target):
    target.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if (
            item.name.startswith("._")
            or item.name
            in {
                ".venv",
                "node_modules",
                "dist",
                "__pycache__",
                ".ruff_cache",
                ".pytest_cache",
                ".env",
            }
            or item.name.endswith(".tsbuildinfo")
        ):
            continue
        destination = target / item.name
        if item.is_dir():
            copy_sources(item, destination)
        else:
            # Copy bytes, not xattrs or resource forks; normalize source readability.
            destination.write_bytes(item.read_bytes())
            destination.chmod(0o644)


for name in ["backend", "frontend"]:
    target = staging / name
    if target.exists():
        shutil.rmtree(target)  # Only this script's generated build context.
    copy_sources(root / name, target)
local = root / ".local"
local.mkdir(exist_ok=True)
override = local / "compose-build.json"
override.write_text(
    json.dumps(
        {
            "services": {
                n: {"build": {"context": str(staging / n)}}
                for n in ["backend", "frontend"]
            }
        },
        indent=2,
    )
)
base = [
    "docker",
    "compose",
    "--project-directory",
    str(root),
    "-f",
    str(root / "docker-compose.yml"),
    "-f",
    str(override),
]
if args.observability:
    base += [
        "-f",
        str(root / "docker-compose.observability.yml"),
        "--profile",
        "observability",
    ]
subprocess.run(base + ["build"], check=True, cwd=root)
if not args.build_only:
    subprocess.run(base + ["up", "-d", "--no-build"], check=True, cwd=root)
