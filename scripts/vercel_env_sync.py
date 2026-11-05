#!/usr/bin/env python3
"""Push AURA env vars from .env.local to the linked Vercel project (Production).

Values are read from .env.local and piped to `vercel env add` over stdin, so they never
appear in argv, logs or output. URL-shaped settings are rewritten for the public origin.
Production-only internal secrets are generated once into .local/prod-secrets.env
(git-ignored) so they differ from local dev and can be reused for `gh secret set`.

    python3 scripts/vercel_env_sync.py --origin https://aura-henna-one.vercel.app          # dry run
    python3 scripts/vercel_env_sync.py --origin https://aura-henna-one.vercel.app --apply
    python3 scripts/vercel_env_sync.py --apply --remove-legacy                              # also drop legacy vars
"""

from __future__ import annotations

import argparse
import re
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".env.local"
PROD_SECRETS = ROOT / ".local" / "prod-secrets.env"

# Copied as-is from .env.local (secret = stored as Vercel "Sensitive").
COPY_SECRET = [
    "DATABASE_URL",
    "DATABASE_URL_UNPOOLED",
    "UPSTASH_REDIS_REST_TOKEN",
    "NEO4J_PASSWORD",
    "LANGFUSE_SECRET_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "TURNSTILE_SECRET_KEY",
]
COPY_CONFIG = [
    "UPSTASH_REDIS_REST_URL",
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_DATABASE",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_HOST",
    "LANGFUSE_SAMPLE_RATE",
    "TURNSTILE_SITE_KEY",
    "NEXT_PUBLIC_TURNSTILE_SITE_KEY",
    "AURA_JWT_AUDIENCE",
    "DAILY_RUN_BUDGET",
    "GUEST_DAILY_RUNS",
    "RATE_LIMIT_PER_MINUTE",
]
# Fresh random values for production, never the local-dev ones.
GENERATED = [
    "BETTER_AUTH_SECRET",
    "ERP_SERVICE_TOKEN",
    "WEBHOOK_SECRET",
    "DEMO_RESET_SECRET",
    "APPROVAL_TOKEN_SECRET",
]
# Variables left over from the legacy app that the rebuild does not read.
LEGACY = ["API_KEY", "VITE_API_TIMEOUT_MS"]


def load(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if m:
            out[m[1]] = m[2].split(" #")[0].strip().strip('"').strip("'")
    return out


def prod_secrets() -> dict[str, str]:
    have = load(PROD_SECRETS)
    missing = [k for k in GENERATED if not have.get(k)]
    if missing:
        PROD_SECRETS.parent.mkdir(parents=True, exist_ok=True)
        for k in missing:
            have[k] = secrets.token_urlsafe(32) if k == "BETTER_AUTH_SECRET" else secrets.token_hex(32)
        PROD_SECRETS.write_text("".join(f"{k}={have[k]}\n" for k in GENERATED))
        PROD_SECRETS.chmod(0o600)
    return have


def plan(origin: str) -> list[tuple[str, str, bool]]:
    env = load(LOCAL)
    gen = prod_secrets()
    rows: list[tuple[str, str, bool]] = []
    for k in COPY_SECRET:
        rows.append((k, env.get(k, ""), True))
    for k in COPY_CONFIG:
        rows.append((k, env.get(k, ""), False))
    for k in GENERATED:
        rows.append((k, gen[k], True))
    rows += [
        ("APP_ENV", "production", False),
        ("LOG_LEVEL", "INFO", False),
        ("ENABLE_BEDROCK", "false", False),
        ("ENABLE_SPECIALIST", "false", False),
        ("BETTER_AUTH_URL", origin, False),
        ("WEB_ORIGIN", origin, False),
        ("AURA_JWT_ISSUER", origin, False),
        ("AURA_JWKS_URL", f"{origin}/api/auth/jwks", False),
    ]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default="https://aura-henna-one.vercel.app")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--remove-legacy", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"https://[a-z0-9.-]+", a.origin):
        sys.exit("--origin must look like https://host")
    rows = plan(a.origin)
    empty = [k for k, v, _ in rows if not v]
    for k, v, sens in rows:
        print(f"{'secret' if sens else 'config':6}  {k:32} {'EMPTY' if not v else 'len ' + str(len(v))}")
    if empty:
        print(f"\nRefusing: empty values for {empty}. Fill them in .env.local first.")
        return 1
    if a.remove_legacy:
        print(f"\nlegacy to remove: {LEGACY}")
    if not a.apply:
        print("\nDry run. Re-run with --apply to write to Vercel (Production).")
        return 0
    failed = []
    for k, v, sens in rows:
        cmd = ["vercel", "env", "add", k, "production", "--force", "--sensitive" if sens else "--no-sensitive"]
        r = subprocess.run(cmd, input=v, text=True, capture_output=True, cwd=ROOT)
        print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} {k}")
        if r.returncode:
            failed.append(k)
    if a.remove_legacy:
        for k in LEGACY:
            r = subprocess.run(
                ["vercel", "env", "rm", k, "production", "--yes"], capture_output=True, text=True, cwd=ROOT
            )
            r2 = subprocess.run(
                ["vercel", "env", "rm", k, "preview", "--yes"], capture_output=True, text=True, cwd=ROOT
            )
            print(f"{'removed' if r.returncode == 0 else 'rm-fail'} {k} (production), {'removed' if r2.returncode == 0 else 'rm-fail'} (preview)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
