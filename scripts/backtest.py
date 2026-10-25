"""Backtest the trade promotion accrual estimate and the close's controls on General Mills' real 10-Ks.

    uv run python scripts/backtest.py [--json]

No database, no network: the figures are cited in tpa/filings.py (re-read them with scripts/pull_10k.py).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tpa.backtest import ESTIMATORS, run  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args()
    res = run()
    if args.json:
        print(json.dumps(res, indent=1, default=str))
        return

    names = list(ESTIMATORS)
    print("Accrued trade and coupon promotion liabilities, $M: estimate at close vs reported in the 10-K\n")
    print(f"{'FY':<6}{'known':<11}{'reported':>9}" + "".join(f"{n:>15}" for n in names) + f"{'review drift':>14}")
    for c in res["closes"]:
        known = f"FY{c['known_filings'][0] % 100:02d}-{c['known_filings'][-1] % 100:02d}"
        est = "".join(f"{c['estimates_musd'][n]:>9} {(c['estimates_musd'][n] / c['actual_musd'] - 1):>+5.0%}" for n in names)
        flag = " FLAG" if c["review_flagged"] else ""
        print(f"FY{c['fiscal_year'] % 100:<4}{known:<11}{c['actual_musd']:>9}{est}{c['review_drift']:>+13.1%}{flag}")
    print()
    for n in names:
        s = res["scores"][n]
        best = "  ← best" if n == res["best"] else ""
        print(f"{n:<15} MAE ${s['mae_musd']}M  MAPE {s['mape']:.1%}  bias {s['bias']:+.1%}  worst {s['worst']:+.1%}{best}")
    ar = res["analytical_review"]
    print(f"\nAnalytical review at ±{ar['tolerance']:.0%}: {ar['false_alarms']} false alarms on audited books "
          f"(largest year-on-year drift {ar['largest_drift']:+.1%})")
    print(f"Restatements of a reported year end: {len(res['restatements']) or 'none'}")


if __name__ == "__main__":
    main()
