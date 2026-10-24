"""Score the system against the answer key.

    uv run python scripts/evaluate.py --as-of month-1 --as-of month-9
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tpa.db import connect  # noqa: E402
from tpa.evaluate import metrics  # noqa: E402


def fmt(v) -> str:
    return "—" if v is None else f"{v:.1%}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", action="append", required=True, help="month-N (live month) or YYYY-MM; repeatable")
    ap.add_argument("--answer-key", type=Path, default=Path("data/answer_key.json"))
    ap.add_argument("--json", action="store_true", help="print the full result as JSON")
    args = ap.parse_args()

    key = json.loads(args.answer_key.read_text())
    with connect() as conn, conn.cursor() as cur:
        results = [metrics(cur, key, spec) for spec in args.as_of]

    if args.json:
        print(json.dumps(results, indent=2))
        return
    print(f"{'':<12}{'precision':>11}{'recall':>9}{'escalation':>12}{'autonomy':>10}")
    for r in results:
        print(f"month {r['live_month']:<6}{fmt(r['precision']):>11}{fmt(r['recall']):>9}"
              f"{fmt(r['escalation_rate']):>12}{fmt(r['autonomy']):>10}")
    last = results[-1]
    j = last["judgment"]
    print(f"\nanswers that stuck, as of {last['as_of']}: {j['settled_by_precedent']} of {j['repeat_findings']} repeat "
          f"situations settled silently by precedent ({fmt(j['precedent_hit_rate'])}); "
          f"{j['asked_again']} asked again; {j['first_time_questions']} first-time questions")
    for a in j["asked_again_detail"]:
        print(f"  asked again {a['finding_id']}: {a['reason']} (${a['exposure']:,} vs ${a['standing_approval'] or 0:,})")
    if last["missed"]:
        print(f"\nmissed as of {last['as_of']}:")
        for m in last["missed"]:
            print(f"  {m['error_id']}  {m['type']:<28}{m['period']}  {m['customer_id']}")
    if last["false_positives"]:
        print(f"\nfalse positives as of {last['as_of']}: {len(last['false_positives'])}")


if __name__ == "__main__":
    main()
