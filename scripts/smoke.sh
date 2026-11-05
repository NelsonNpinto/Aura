#!/usr/bin/env bash
# Post-deploy smoke test. Usage: scripts/smoke.sh https://aura-xyz.vercel.app
set -euo pipefail
BASE="${1:?base url}"
fail() { echo "SMOKE FAIL: $*"; exit 1; }
check() {  # path expected_status
  code=$(curl -s -o /tmp/smoke.body -w "%{http_code}" --max-time 30 "$BASE$1")
  [ "$code" = "$2" ] || fail "$1 returned $code (expected $2): $(head -c 300 /tmp/smoke.body)"
  echo "ok $1 $code"
}
check /api/v1/health 200
grep -q '"status":"ok"' /tmp/smoke.body || fail "health body"
# Neon may be cold (~1 s); /ready returns 503 only when Postgres is down.
check /api/v1/ready 200
check / 200
check /demo 200
check /login 200
check /api/auth/jwks 200
grep -q '"keys"' /tmp/smoke.body || fail "jwks has no keys"
check /api/v1/me 401
hdr=$(curl -sI --max-time 30 "$BASE/api/v1/health")
echo "$hdr" | grep -qi '^x-request-id:' || fail "missing X-Request-ID"
echo "$hdr" | grep -qi '^content-security-policy:' || fail "missing CSP"
echo "smoke passed: $BASE"
