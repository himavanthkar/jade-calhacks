"""The played year's statistics beside sourced industry and peer figures (tpa.benchmarks).

    uv run python scripts/benchmarks.py [--through 2026-12] [--json]

Reads DATABASE_URL after a played year (`make players`). Changes nothing.
"""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tpa.benchmarks import compare, measure  # noqa: E402
from tpa.db import connect  # noqa: E402


def fmt(v, unit: str) -> str:
    if v is None:
        return "—"
    return f"{Decimal(v):.1%}" if unit == "pct" else f"{Decimal(v):,.1f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--through", default="2026-12")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    with connect() as conn, conn.cursor() as cur:
        stats = measure(cur, args.through)
    rows = compare(stats)
    if args.json:
        print(json.dumps({"stats": stats, "benchmarks": rows}, indent=1, default=str))
        return
    print(f"{'metric':<30}{'simulation':>11}{'benchmark':>17}  {'':8}source")
    for r in rows:
        band = f"{fmt(r['low'], r['unit'])}–{fmt(r['high'], r['unit'])}"
        tag = "" if r["independent"] else " (vendor)"
        print(f"{r['metric']:<30}{fmt(r['simulation'], r['unit']):>11}{band:>17}  {r['where'] or '—':<8}"
              f"{r['source'][:70]}{tag}, {r['year']}")


if __name__ == "__main__":
    main()
