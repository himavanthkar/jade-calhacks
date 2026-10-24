"""Verifiability gates. A failure blocks the period: `sign_period` refuses to sign it.

Each gate returns violations carrying the ids that broke it, so the close reviewer and
the evaluator see exactly which rows are at fault. Accrual violations are keyed
`accrual:<program>:<origin period>`, the same form the answer key uses.
"""

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal

import psycopg

from tpa.asof import liability_outstanding, terms_as_of
from tpa.constants import (
    HISTORY_MONTHS, Account, month_for_period, period_end, period_for_month, period_of, period_start,
)

STALE_GRACE_PERIODS = 2
SIGNING_ROLES = ("controller", "close_reviewer")


@dataclass
class GateResult:
    name: str
    description: str
    passed: bool = True
    violations: list[dict] = field(default_factory=list)

    def fail(self, **violation) -> None:
        self.passed = False
        self.violations.append(violation)


class GateFailure(RuntimeError):
    def __init__(self, period: str, customer_id: str, results: dict[str, GateResult]):
        self.results = results
        failed = [r.name for r in results.values() if not r.passed]
        super().__init__(f"period {period} for {customer_id} is blocked by gates: {', '.join(failed)}")


def accrual_key(program_id: str, valid_time: date) -> str:
    return f"accrual:{program_id}:{period_of(valid_time)}"


# ── the gates ───────────────────────────────────────────────────────────────
def journals_balance(cur, period, customer_id, as_of) -> GateResult:
    g = GateResult("journals_balance", "Debits equal credits on every posted journal")
    cur.execute(
        """SELECT journal_id, SUM(debit), SUM(credit) FROM ledger_entries
           WHERE period = %s AND customer_id = %s AND decision_time <= %s
           GROUP BY journal_id HAVING SUM(debit) <> SUM(credit)""",
        (period, customer_id, as_of),
    )
    for journal_id, dr, cr in cur.fetchall():
        g.fail(journal_id=journal_id, debits=dr, credits=cr)
    return g


def reversals_mirror(cur, period, customer_id, as_of) -> GateResult:
    g = GateResult("reversals_mirror", "Every reversal exactly offsets the accrual it reverses, once")
    cur.execute(
        """SELECT r.id, r.account, r.program_id, r.valid_time, r.debit, r.credit,
                  o.id, o.account, o.program_id, o.valid_time, o.debit, o.credit, o.entry_type
           FROM ledger_entries r JOIN ledger_entries o ON o.id = r.reversal_of
           WHERE r.period = %s AND r.customer_id = %s AND r.decision_time <= %s""",
        (period, customer_id, as_of),
    )
    for rid, racct, rprog, rvt, rdr, rcr, oid, oacct, oprog, ovt, odr, ocr, otype in cur.fetchall():
        if otype not in ("accrual", "opening"):
            g.fail(entry_id=rid, reverses=oid, reason=f"reverses a {otype} line, not an accrual")
        elif (racct, rprog, rvt, rdr, rcr) != (oacct, oprog, ovt, ocr, odr):
            g.fail(entry_id=rid, reverses=oid, reason="does not mirror the original line",
                   reversal=str(rdr or -rcr), original=str(odr or -ocr))
    cur.execute(
        """SELECT reversal_of, array_agg(id ORDER BY id) FROM ledger_entries
           WHERE customer_id = %s AND decision_time <= %s AND reversal_of IS NOT NULL
             AND period <= %s
           GROUP BY reversal_of HAVING COUNT(*) > 1""",
        (customer_id, as_of, period),
    )
    for oid, ids in cur.fetchall():
        g.fail(entry_id=oid, reversed_by=ids, reason="reversed more than once")
    return g


def cleared_within_accrued(cur, period, customer_id, as_of) -> GateResult:
    g = GateResult("cleared_within_accrued",
                   "Deductions cleared never exceed the liability accrued for that program and period")
    for (program_id, vt), outstanding in liability_outstanding(
            cur, as_of, through_period=period, customer_id=customer_id).items():
        if outstanding < 0:
            g.fail(key=accrual_key(program_id, vt), program_id=program_id, origin=period_of(vt),
                   over_cleared_by=-outstanding)
    return g


def claim_lag_prior(cur, customer_id) -> int:
    """Median months from claimed period to deduction during the history year: a derived prior."""
    history_end = period_end(period_for_month(max(HISTORY_MONTHS)))
    cur.execute(
        "SELECT claimed_period, taken_date FROM deductions WHERE customer_id = %s AND available_at <= %s",
        (customer_id, history_end),
    )
    lags = [month_for_period(period_of(taken)) - month_for_period(claimed) for claimed, taken in cur.fetchall()]
    return int(statistics.median(lags)) if lags else 0


def no_stale_accruals(cur, period, customer_id, as_of) -> GateResult:
    lag = claim_lag_prior(cur, customer_id)
    allowed = lag + STALE_GRACE_PERIODS
    g = GateResult("no_stale_accruals",
                   f"No accrual open more than {STALE_GRACE_PERIODS} periods past the customer's "
                   f"{lag}-month claim lag without a deduction")
    # A deduction cleared or disputed against the accrual both mean the claim arrived.
    cur.execute(
        """SELECT DISTINCT program_id, valid_time FROM ledger_entries
           WHERE customer_id = %s AND decision_time <= %s AND period <= %s
             AND (entry_type = 'clearing' OR (entry_type = 'dispute' AND deduction_id IS NOT NULL))""",
        (customer_id, as_of, period),
    )
    cleared = set(cur.fetchall())
    now = month_for_period(period)
    for (program_id, vt), outstanding in liability_outstanding(
            cur, as_of, through_period=period, customer_id=customer_id).items():
        age = now - month_for_period(period_of(vt))
        if outstanding > 0 and (program_id, vt) not in cleared and age > allowed:
            g.fail(key=accrual_key(program_id, vt), program_id=program_id, origin=period_of(vt),
                   outstanding=outstanding, age_periods=age, allowed_periods=allowed)
    return g


def claims_inside_window(cur, period, customer_id, as_of) -> GateResult:
    g = GateResult("claims_inside_window", "Every cleared deduction's claimed period falls inside its program window")
    cur.execute(
        """SELECT e.id, e.program_id, d.id, d.claimed_period, d.claim_start, d.claim_end, e.valid_time,
                  (SELECT COUNT(DISTINCT x.valid_time) FROM ledger_entries x
                   WHERE x.deduction_id = d.id AND x.entry_type = 'clearing' AND x.account = e.account
                     AND x.decision_time <= %s)
           FROM ledger_entries e JOIN deductions d ON d.id = e.deduction_id
           WHERE e.period = %s AND e.customer_id = %s AND e.decision_time <= %s
             AND e.entry_type = 'clearing' AND e.account = %s""",
        (as_of, period, customer_id, as_of, Account.ACCRUED_TRADE_PROMO),
    )
    for entry_id, program_id, ded_id, claimed, cstart, cend, origin_end, origins in cur.fetchall():
        start, end = cstart or period_start(claimed), cend or period_end(claimed)
        if origins > 1:
            # Allocated across origins by activity days: check only the share cleared against this one.
            claimed = period_of(origin_end)
            start, end = max(start, period_start(claimed)), min(end, origin_end)
            if start > end:
                g.fail(entry_id=entry_id, deduction_id=ded_id, program_id=program_id, origin=claimed,
                       reason="cleared against an origin outside the claimed dates")
                continue
        terms = terms_as_of(cur, program_id, start, as_of) if program_id else None
        if terms is None:
            g.fail(entry_id=entry_id, deduction_id=ded_id, program_id=program_id,
                   reason="no program terms on file for the claimed dates; cannot verify")
        elif start < terms["window_start"] or end > terms["window_end"] or period_start(claimed) < terms["window_start"] \
                or period_end(claimed) > terms["window_end"]:
            g.fail(entry_id=entry_id, deduction_id=ded_id, program_id=program_id, claimed_period=claimed,
                   window=[terms["window_start"], terms["window_end"]])
    return g


GATES = (journals_balance, reversals_mirror, cleared_within_accrued, no_stale_accruals, claims_inside_window)


# ── running and signing ─────────────────────────────────────────────────────
def _json(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    raise TypeError(type(v).__name__)


def results_json(results: dict[str, GateResult]) -> str:
    return json.dumps({k: asdict(v) for k, v in results.items()}, default=_json)


def run_gates(cur: psycopg.Cursor, period: str, customer_id: str, as_of: datetime) -> dict[str, GateResult]:
    """Run every gate and store the results on the period row."""
    results = {g.__name__: g(cur, period, customer_id, as_of) for g in GATES}
    cur.execute("UPDATE periods SET gate_results = %s WHERE period = %s AND customer_id = %s",
                (results_json(results), period, customer_id))
    return results


def sign_period(cur: psycopg.Cursor, period: str, customer_id: str, signed_by: str, signed_at: datetime) -> dict:
    """Sign a period if every gate passes; otherwise raise GateFailure and leave it unsigned."""
    cur.execute("SELECT role FROM actors WHERE id = %s", (signed_by,))
    row = cur.fetchone()
    if row is None or row[0] not in SIGNING_ROLES:
        raise PermissionError(f"{signed_by} cannot sign the close; only {' or '.join(SIGNING_ROLES)} can")
    results = run_gates(cur, period, customer_id, signed_at)
    if not all(r.passed for r in results.values()):
        raise GateFailure(period, customer_id, results)
    payload = results_json(results)
    cur.execute(
        """UPDATE periods SET state = 'SIGNED', signed_by = %s, signed_at = %s, gate_results = %s
           WHERE period = %s AND customer_id = %s""",
        (signed_by, signed_at, payload, period, customer_id),
    )
    cur.execute(
        """INSERT INTO period_signoffs (period, customer_id, signed_by, signed_at, gate_results)
           VALUES (%s, %s, %s, %s, %s)""",
        (period, customer_id, signed_by, signed_at, payload),
    )
    return json.loads(payload)
