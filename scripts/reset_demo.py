"""Restore the deterministic demo dataset.

Usage:  python -m scripts.reset_demo
"""
from __future__ import annotations

import json
import sys

from app.db.connection import DatabaseUnavailable, get_client
from app.db.seed import reset_graph


def main() -> int:
    client = get_client()
    if not client.ping():
        print(f"ERROR: FalkorDB is not reachable at {client.settings.falkordb_host}:{client.settings.falkordb_port}.\n"
              "Start it with: docker compose up -d falkordb", file=sys.stderr)
        return 1
    try:
        counts = reset_graph(client)
    except DatabaseUnavailable as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Seeded graph '{client.graph_name}':")
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
