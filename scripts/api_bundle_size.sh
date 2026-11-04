#!/usr/bin/env bash
# Approximates the Vercel api bundle: runtime deps (no dev group, pruned like the build step)
# + app code + model cache. Fails above LIMIT_MB (default 450, §B17) or if torch is present.
set -euo pipefail
LIMIT_MB="${LIMIT_MB:-450}"
cd "$(dirname "$0")/../apps/api"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
uv export --no-dev --no-hashes --frozen --no-emit-project -o "$TMP/req.txt" >/dev/null
uv pip install --quiet --target "$TMP/site" -r "$TMP/req.txt"
if [ -d "$TMP/site/torch" ]; then echo "FAIL: torch found in api bundle"; exit 1; fi
python3 app/scripts/prune_bundle.py "$TMP/site"
python3 - "$TMP/site" "$LIMIT_MB" <<'PY'
import os, sys
def mb(p):
    t = 0
    for r, _, fs in os.walk(p):
        for f in fs:
            fp = os.path.join(r, f)
            if not f.startswith("._") and not os.path.islink(fp):
                t += os.path.getsize(fp)
    return t / 1e6
deps, app, models = mb(sys.argv[1]), mb("app"), mb("model_cache") if os.path.isdir("model_cache") else 0.0
total, limit = deps + app + models, float(sys.argv[2])
print(f"api bundle estimate: deps={deps:.0f}MB app={app:.1f}MB models={models:.0f}MB total={total:.0f}MB limit={limit:.0f}MB")
sys.exit(0 if total <= limit else 1)
PY
