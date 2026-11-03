#!/usr/bin/env python3
"""Create local development secrets without overwriting existing values."""

import argparse
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--observability", action="store_true")
args = parser.parse_args()
path = root / ".env"
if not path.exists():
    path.write_text(
        (root / ".env.example")
        .read_text()
        .replace("change-this-local-password", secrets.token_hex(24))
    )
lines = path.read_text().splitlines()
values = dict(
    line.split("=", 1)
    for line in lines
    if "=" in line and not line.lstrip().startswith("#")
)
updates = {"WEBHOOK_SECRET": values.get("WEBHOOK_SECRET") or secrets.token_hex(32)}
if args.observability:
    for key in [
        "LF_DATABASE_PASSWORD",
        "LF_REDIS_PASSWORD",
        "LF_STORAGE_PASSWORD",
        "LF_CLICKHOUSE_PASSWORD",
        "LF_SALT",
        "LF_ENCRYPTION_KEY",
        "LF_NEXTAUTH_SECRET",
        "LF_ADMIN_PASSWORD",
    ]:
        updates[key] = values.get(key) or secrets.token_hex(32)
    updates.update(
        {
            "LANGFUSE_PUBLIC_KEY": values.get("LANGFUSE_PUBLIC_KEY")
            or "pk-lf-" + secrets.token_hex(16),
            "LANGFUSE_SECRET_KEY": values.get("LANGFUSE_SECRET_KEY")
            or "sk-lf-" + secrets.token_hex(32),
            "LANGFUSE_BASE_URL": "http://langfuse-web:3000",
            "OTEL_ENDPOINT": "http://otel:4318/v1/traces",
        }
    )
seen = set()
for i, line in enumerate(lines):
    if "=" in line and line.split("=", 1)[0] in updates:
        key = line.split("=", 1)[0]
        lines[i] = key + "=" + updates[key]
        seen.add(key)
lines.extend(k + "=" + v for k, v in updates.items() if k not in seen)
path.write_text("\n".join(lines) + "\n")
path.chmod(0o600)
print("Local configuration saved in .env; secrets were not printed.")
