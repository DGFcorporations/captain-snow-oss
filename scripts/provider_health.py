"""Provider health check — standalone wrapper for `captainsnow doctor`.

    python scripts/provider_health.py          # config checks only
    python scripts/provider_health.py --ping   # + live ~10-token call/provider
    python scripts/provider_health.py --json   # machine-readable output

Run weekly (watchers skill or cron). Exit 1 if any configured provider is dead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "captainsnow"))

from core.profile import load_config
from core.provider_health import check_config, ping_all, render_table, exit_code


def main() -> int:
    ap = argparse.ArgumentParser(description="Captain Snow provider health check")
    ap.add_argument("--ping", action="store_true", help="make a live ~10-token call per provider")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    try:
        config = load_config()
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    rows = check_config(config)
    if args.ping:
        rows = asyncio.run(ping_all(config, rows))

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(render_table(rows, args.ping))

    return exit_code(rows, args.ping)


if __name__ == "__main__":
    raise SystemExit(main())
