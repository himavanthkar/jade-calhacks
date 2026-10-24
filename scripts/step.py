"""Drive the monthly engine from the command line.

    uv run python scripts/step.py                     # step one month
    uv run python scripts/step.py --through month-9   # step until September has run
    uv run python scripts/step.py --reset --through month-12 --autopilot --metrics

--reset re-seeds first (same as `make seed`). --autopilot answers escalations the way last
year's humans did (tpa.autopilot) instead of leaving them for workstream C.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tpa import autopilot  # noqa: E402
from tpa.asof import sim_clock  # noqa: E402
from tpa.cycle import Hooks, run_through, step  # noqa: E402
from tpa.db import connect  # noqa: E402
from tpa.evaluate import metrics  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--through", help="'2026-09' or 'month-9'; default: one month")
    ap.add_argument("--reset", action="store_true", help="re-seed the database first")
    ap.add_argument("--autopilot", action="store_true", help="stand-in humans answer escalations")
    ap.add_argument("--metrics", action="store_true", help="print precision/recall/escalation/autonomy after")
    args = ap.parse_args()

    if args.reset:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "seed.py"), "--seed", "1337", "--months", "24",
                        "--load-terms"], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    hooks = autopilot.hooks() if args.autopilot else Hooks()
    conn = connect()
    summaries = run_through(conn, args.through, hooks) if args.through else [step(conn, hooks)]
    for s in summaries:
        states = " ".join(f"{c}:{st}" for c, st in s["states"].items())
        found = ", ".join(f"{c.removeprefix('CTL-')} {st}×{n}" for c, st, n in s["findings"]) or "no findings"
        print(f"{s['period']}  {states}  |  {found}")
        for line in s["log"]:
            print(f"    {line}")
    if args.metrics:
        key = json.loads((ROOT / "data" / "answer_key.json").read_text())
        with conn.cursor() as cur:
            period, _ = sim_clock(cur)
            last = summaries[-1]["period"] if summaries else period
            for spec in ("month-1", last):
                m = metrics(cur, key, spec)
                print(f"{m['as_of']}  precision {m['precision']}  recall {m['recall']}  "
                      f"escalation rate {m['escalation_rate']}  autonomy {m['autonomy']}")
            for row in m["missed"]:
                print(f"    missed {row['error_id']} {row['type']} ({row['period']} {row['customer_id']})")
            for row in m["false_positives"]:
                print(f"    false positive {row['finding_id']} {row['control_id']} ({row['period']})")
    conn.close()


if __name__ == "__main__":
    main()
