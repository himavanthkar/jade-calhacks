"""Write a period's sign-off package as CSVs anyone can check in Excel.

    uv run python scripts/export.py --period 2026-02 --as-of month-2
    uv run python scripts/export.py --period 2026-02 --as-of month-8    # same table, the second correct answer
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tpa.db import connect  # noqa: E402
from tpa.export import files, parse_as_of  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--period", required=True, help="YYYY-MM")
    ap.add_argument("--as-of", help="month-N, YYYY-MM or an ISO date-time; default: as the books stand now")
    ap.add_argument("--out", type=Path, default=Path("data/export"))
    args = ap.parse_args()

    out = args.out / f"{args.period}_as_of_{args.as_of or 'now'}"
    out.mkdir(parents=True, exist_ok=True)
    with connect() as conn, conn.cursor() as cur:
        for name, text in files(cur, args.period, parse_as_of(args.as_of)).items():
            (out / name).write_text(text)
            print(out / name)


if __name__ == "__main__":
    main()
