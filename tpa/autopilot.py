"""Stand-in humans: answer every escalation the way last year's humans did, deterministically.

For running the engine end to end before workstream C's model-played roles and precedent
store land, and for replaying a scenario on demand. Each control maps to the action its
prior-year precedents took and the role that took it. Nothing here writes escalations or
precedents — that is C's loop; this only decides and calls `tpa.execute.execute`.

    hooks = autopilot.hooks()      # then cycle.step(conn, hooks)
"""

from datetime import datetime

import psycopg

from tpa.constants import Control as C
from tpa.cycle import Hooks, MECHANICAL, default_judge
from tpa.execute import execute

# (control, conflict_type or None) → (role that answered last year, decision)
PRECEDENT_ANSWERS = {
    (C.SCAN_NO_BACKUP, None): ("deduction_analyst", "dispute"),            # reversed pending backup
    (C.OUTSIDE_WINDOW, None): ("controller", "dispute"),                   # recovered
    (C.PERIOD_STRADDLE, None): ("controller", "allocate"),                 # allocated by activity days
    (C.RATE_CONFLICT, "claimed_rate"): ("customer_team_analyst", "dispute_difference"),   # program as signed
    (C.CLAIM_VS_BACKUP, None): ("trade_promotion_accountant", "dispute_difference"),      # re-billed
    (C.DED_GT_ACCRUAL, "over_claim"): ("trade_promotion_accountant", "top_up_and_clear"),  # topped up
    (C.STALE_ACCRUAL, None): ("trade_promotion_accountant", "release_accrual"),           # released
    # Learned in the live year, so no precedent: the stand-in accountant notes it.
    (C.REDEMPTION_DRIFT, None): ("trade_promotion_accountant", "acknowledge"),
}
# Last year's people, standing in for the roles the live year escalates to.
ACTOR_FOR_ROLE = {
    "controller": "controller", "close_reviewer": "close_reviewer",
    "trade_promotion_accountant": "tpa.human", "deduction_analyst": "deductions.human",
}
CUSTOMER_TEAM = {"WMT": "team.walmart", "COST": "team.costco", "KR": "team.kroger"}


def answer(f: dict) -> tuple[str, str] | None:
    """(actor, decision) the prior year would have given, or None: no precedent, so it waits."""
    key = PRECEDENT_ANSWERS.get((f["control_id"], f["conflict_type"])) or PRECEDENT_ANSWERS.get((f["control_id"], None))
    if key is None:
        return None
    role, decision = key
    actor = CUSTOMER_TEAM[f["customer_id"]] if role == "customer_team_analyst" else ACTOR_FOR_ROLE[role]
    return actor, decision


def judge(cur: psycopg.Cursor, f: dict, when: datetime) -> None:
    if f["state"] != "open":
        return
    if f["control_id"] in MECHANICAL:
        default_judge(cur, f, when)
        return
    a = answer(f)
    if a is None:
        cur.execute("UPDATE findings SET state = 'escalated' WHERE id = %s", (f["id"],))
        return
    actor, decision = a
    precedents = (f["evidence"] or {}).get("control", {}).get("precedent_ids", [])
    execute(cur, f["id"], decision, actor, when,
            note=f"stand-in {actor}, following {len(precedents)} prior-year precedents ({', '.join(precedents[:3])}"
                 f"{'…' if len(precedents) > 3 else ''})")


def hooks() -> Hooks:
    return Hooks(judge=judge)
