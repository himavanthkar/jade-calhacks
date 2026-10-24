"""Flux commentary: period-over-period change in an account, explained by the entries that drove it.

A control activity, not reporting: every number in the narrative is a sum of named journal
lines, and `driver_entry_ids` lists them. The narrative is templated from those sums; the
model may later rewrite the prose but never the numbers.

Balances are by decision time, so a restatement posted into February in August is August's
movement: the books as they stood at the end of each month.
"""

from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal

import psycopg

from tpa.accrual import ZERO, nice_ceiling
from tpa.constants import Account, add_months, period_end
from tpa.execute import next_id
from tpa.policy import MATERIALITY_FLOOR
from tpa.rows import all_rows

ACCOUNTS = (Account.ACCRUED_TRADE_PROMO, Account.DEDUCTIONS_PENDING)
def category(line: dict) -> str:
    """What a line did to the account, in the words a close reviewer uses."""
    t, acct = line["entry_type"], line["account"]
    if t == "reversal" or (t == "accrual" and line["source_finding_id"]):
        return "re-estimates (reversed and re-made accruals, net)"
    if t == "adjustment" and acct == Account.DEDUCTIONS_PENDING:
        return "deductions taken"
    if t == "adjustment" and line["memo"] and line["memo"].startswith("Release"):
        return "stale accruals released"
    if t == "dispute" and line["memo"] and line["memo"].startswith("Withdraw"):
        return "disputes withdrawn"
    return {"accrual": "new accruals", "opening": "opening balances", "clearing": "deductions cleared",
            "restatement": "restatement catch-ups", "adjustment": "true-ups", "dispute": "deductions disputed",
            "revenue": "revenue"}.get(t, t)


MONTH = "%B %Y"


def balance(cur: psycopg.Cursor, account: str, as_of: datetime) -> Decimal:
    """Credit-normal balance of a liability, debit-normal for an asset, as known at `as_of`."""
    cur.execute("SELECT COALESCE(SUM(credit) - SUM(debit), 0) FROM ledger_entries WHERE account = %s AND decision_time <= %s",
                (account, as_of))
    raw = cur.fetchone()[0]
    return raw if account.startswith("2") else -raw


def materiality(cur: psycopg.Cursor) -> Decimal:
    cur.execute("SELECT threshold FROM controls WHERE id = 'CTL-DED-GT-ACCRUAL'")
    row = cur.fetchone()
    return row[0] if row else nice_ceiling(MATERIALITY_FLOOR)


def write_flux(cur: psycopg.Cursor, period: str, when: datetime) -> list[str]:
    prior_period = add_months(period, -1)
    prior_at = datetime.combine(period_end(prior_period), time(23, 59))
    out = []
    for account in ACCOUNTS:
        current, prior = balance(cur, account, when), balance(cur, account, prior_at)
        change = current - prior
        if abs(change) <= materiality(cur):
            continue
        lines = all_rows(cur, """SELECT e.*, j.memo AS journal_memo FROM ledger_entries e
                                  LEFT JOIN LATERAL (SELECT memo FROM ledger_entries WHERE journal_id = e.journal_id
                                                     ORDER BY id LIMIT 1) j ON TRUE
                                  WHERE e.account = %s AND e.decision_time > %s AND e.decision_time <= %s
                                  ORDER BY e.decision_time, e.id""", (account, prior_at, when))
        sign = Decimal(1) if account.startswith("2") else Decimal(-1)
        by_type: dict[str, list[dict]] = defaultdict(list)
        for l in lines:
            by_type[category(l)].append(l)
        parts, drivers = [], []
        for etype, ls in sorted(by_type.items(), key=lambda kv: -abs(sum((l["credit"] - l["debit"] for l in kv[1]), ZERO))):
            amt = sign * sum((l["credit"] - l["debit"] for l in ls), ZERO)
            if amt == 0:
                continue
            journals = sorted({l["journal_id"] for l in ls})
            cite = ", ".join(journals[:6]) + (f" and {len(journals) - 6} more" if len(journals) > 6 else "")
            text = f"{'+' if amt > 0 else '−'}${abs(amt):,} {etype} ({cite})"
            if etype == "restatement catch-ups":
                periods = sorted({l["period"] for l in ls})
                programs = sorted({l["program_id"] for l in ls if l["program_id"]})
                text += (f" — restating {', '.join(programs)} for {periods[0]} to {periods[-1]}; those periods were "
                         f"right on what was known when they closed")
            parts.append(text)
            drivers += [l["id"] for l in sorted(ls, key=lambda l: -(l["credit"] + l["debit"]))[:10]]
        pct = (change / prior * 100).quantize(Decimal("0.1")) if prior else None
        head = (f"{account[5:]}, {period_end(period):{MONTH}}: ${current:,} vs ${prior:,} "
                f"{period_end(prior_period):%B}" + (f" ({'+' if pct >= 0 else ''}{pct}%)" if pct is not None else ""))
        narrative = head + ". Movement: " + "; ".join(parts) + "."
        fid = next_id(cur, "flux_commentary", "FX")
        cur.execute(
            """INSERT INTO flux_commentary (id, period, account, current_balance, prior_balance, pct_change, narrative,
                                            driver_entry_ids, decision_time)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (fid, period, account, current, prior, pct, narrative, drivers, when),
        )
        out.append(fid)
    return out
