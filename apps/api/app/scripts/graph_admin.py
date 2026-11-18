"""Knowledge-graph admin: schema, sync, reconcile, ping (§B8.2).

    python -m app.scripts.graph_admin --schema      # create constraints and indexes
    python -m app.scripts.graph_admin --sync        # drain the outbox
    python -m app.scripts.graph_admin --ping        # keep-alive probe (never fails the job)

Every command degrades: when AuraDB is paused or unconfigured the script reports `unavailable`
and exits 0 for --ping (it is a keep-alive), non-zero for --schema and --sync (they are work
that did not happen).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.graph.client import GraphUnavailable, availability, ping
from app.graph.schema import apply_schema
from app.graph.sync import drain


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    out: dict[str, Any] = {
        "availability": dict(zip(("usable", "reason"), availability(), strict=True))
    }
    if args.ping:
        out["ping"] = await ping()
    if args.schema:
        try:
            out["schema"] = {"statements": await apply_schema()}
        except GraphUnavailable as exc:
            out["schema"] = {"status": "unavailable", "reason": exc.details.get("reason")}
    if args.sync:
        out["sync"] = await drain(args.limit)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", action="store_true")
    parser.add_argument("--sync", action="store_true")
    parser.add_argument("--ping", action="store_true")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    if not (args.schema or args.sync or args.ping):
        parser.error("choose --schema, --sync or --ping")
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2, default=str))
    if args.ping and not (args.schema or args.sync):
        return  # keep-alive never fails the workflow
    failed = any(isinstance(v, dict) and v.get("status") == "unavailable" for v in result.values())
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
