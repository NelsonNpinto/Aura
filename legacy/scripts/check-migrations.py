#!/usr/bin/env python3
"""Verify migrations in a disposable PostgreSQL database, preserving the application database."""

import secrets
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

root = Path(__file__).resolve().parent.parent
settings = dict(
    line.split("=", 1)
    for line in (root / ".env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
name = "aura_migration_check_" + secrets.token_hex(5)
user = settings.get("POSTGRES_USER", "aura")
base = [
    "docker",
    "compose",
    "--project-directory",
    str(root),
    "-f",
    str(root / "docker-compose.yml"),
]
subprocess.run(base + ["exec", "-T", "db", "createdb", "-U", user, name], check=True)
parts = urlsplit(settings["DATABASE_URL"])
credentials = parts.netloc.rsplit("@", 1)[0]
url = urlunsplit((parts.scheme, credentials + "@db:5432", "/" + name, "", ""))
try:
    for command in [
        ("upgrade", "head"),
        ("check",),
        ("downgrade", "base"),
        ("upgrade", "head"),
        ("check",),
    ]:
        subprocess.run(
            base
            + [
                "exec",
                "-T",
                "-e",
                "DATABASE_URL=" + url,
                "backend",
                "/app/.venv/bin/alembic",
                *command,
            ],
            check=True,
        )
    print("PostgreSQL/pgvector upgrade, drift check, downgrade, and re-upgrade passed.")
finally:
    subprocess.run(base + ["exec", "-T", "db", "dropdb", "-U", user, name], check=True)
