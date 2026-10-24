"""Generate the simulation, load it, and write the answer key.

    uv run python scripts/seed.py --seed 1337 --months 24
      months  1–12  → history (2025), for onboarding to learn from
      months 13–24  → the live year (2026) the demo steps through

Resets the database schema first. Deterministic: the same seed gives the same rows.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tpa.db import connect, reset_schema  # noqa: E402
from tpa.seed.generate import build  # noqa: E402
from tpa.seed.load import fingerprint, load, write_files  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--out-dir", type=Path, default=Path("data"))
    ap.add_argument("--no-db", action="store_true", help="only write the answer key files")
    ap.add_argument("--load-terms", action="store_true",
                    help="tests of the ledger alone: load the extractor's answer key as program_terms. The engine "
                         "never needs it; it reads the agreements itself (tpa.extract)")
    args = ap.parse_args()

    ds = build(args.seed, args.months)
    for path in write_files(ds, args.out_dir):
        print(f"wrote {path}")
    if not args.no_db:
        conn = connect()
        reset_schema(conn)
        load(conn, ds, load_terms=args.load_terms)
        conn.close()
        print("loaded database")

    print()
    for table, rows in ds.tables.items():
        print(f"  {table:<22}{len(rows):>6}")
    m = ds.answer_key["moment"]
    print(f"\nplanted errors: {len(ds.answer_key['planted'])}")
    for t, n in sorted(Counter(r["type"] for r in ds.answer_key["planted"]).items()):
        print(f"  {t:<28}{n:>3}")
    print(f"\nthe moment: {m['amendment_id']} on {m['program_id']}, "
          f"${m['rate_as_signed']} → ${m['rate_amended']}/case from {m['effective_date']}, "
          f"entered {m['entered_on']}")
    for p in m["periods"]:
        print(f"  {p['period']}  {p['net_cases_from_effective_date']:>9,} cases  catch-up ${p['catch_up']:>12,}")
    print(f"  total catch-up ${m['total_catch_up']:,}")
    print(f"\nfingerprint {fingerprint(ds)}  (same on every machine for the same seed)")


if __name__ == "__main__":
    main()
