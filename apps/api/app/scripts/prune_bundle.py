"""Build step: delete static assets the in-process router never loads (LiteLLM's proxy admin UI
and Swagger bundle), to keep the api function under the bundle budget (§B17)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PRUNE = ["litellm/proxy/_experimental", "litellm/proxy/swagger"]


def main(site: str | None = None) -> None:
    if site is None:
        import litellm

        root = Path(litellm.__file__).resolve().parents[1]
    else:
        root = Path(site)
    freed = 0
    for rel in PRUNE:
        p = root / rel
        if p.is_dir():
            freed += sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            shutil.rmtree(p)
    print(f"pruned {freed / 1e6:.1f} MB from {root}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
