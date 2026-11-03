#!/usr/bin/env python3
"""Validate the Terraform example in Docker without provisioning resources."""

import argparse
import shutil
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--fix", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
source = root / "infra/terraform"
stage = (
    Path.home() / "Library/Caches/aura/terraform-check"
    if __import__("sys").platform == "darwin"
    else Path.home() / ".cache/aura/terraform-check"
)
stage.mkdir(parents=True, exist_ok=True)
stage.chmod(0o755)
for file in source.iterdir():
    if (
        file.is_file()
        and not file.name.startswith("._")
        and (file.suffix == ".tf" or file.name == ".terraform.lock.hcl")
    ):
        copy = stage / file.name
        copy.write_bytes(file.read_bytes())
        copy.chmod(0o644)
base = [
    "docker",
    "run",
    "--rm",
    "-v",
    f"{stage}:/workspace",
    "-v",
    "aura_terraform_validation:/tf-data",
    "-e",
    "TF_DATA_DIR=/tf-data",
    "-w",
    "/workspace",
    "hashicorp/terraform:1.13.4",
]
commands = [
    ["init", "-backend=false"],
    ["fmt"] if args.fix else ["fmt", "-check"],
    ["validate"],
]
for command in commands:
    subprocess.run(base + command, check=True)
if args.fix:
    for file in stage.glob("*.tf"):
        (source / file.name).write_bytes(file.read_bytes())
if (stage / ".terraform.lock.hcl").exists():
    shutil.copyfile(stage / ".terraform.lock.hcl", source / ".terraform.lock.hcl")
