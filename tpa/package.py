"""The sign-off package: what the close reviewer signs, for one period, as the books stood at `as_of`.

Read-only. Per customer: the period's postings and balances, every finding with its escalation and
answer, the verifiability gates re-run as of that moment (not the stored results, so the package
for March reads what March knew), the flux commentary, and the reconciliation identity for each
program's accrual originating in the period:

    ending = opening + accruals + estimate adjustments − settled claims
"""

from datetime import datetime
from decimal import Decimal

import psycopg

from tpa.asof import balances_as_of, entries_as_of
from tpa.constants import CUSTOMERS, Account, period_end
from tpa.gates import GATES
from tpa.rows import all_rows, one_row

ZERO = Decimal("0")
ADJUSTMENTS = ("reversal", "adjustment", "restatement")


def reconciliation(cur: psycopg.Cursor, period: str, as_of: datetime, customer_id: str) -> list[dict]:
    """Per program, the accrual for this period's activity (valid_time = the period's last day)."""
    rows = all_rows(cur, """SELECT program_id, entry_type, SUM(credit) - SUM(debit) AS net FROM ledger_entries
                            WHERE account = %s AND valid_time = %s AND customer_id = %s AND decision_time <= %s
                              AND program_id IS NOT NULL
                            GROUP BY 1, 2 ORDER BY 1, 2""",
                    (Account.ACCRUED_TRADE_PROMO, period_end(period), customer_id, as_of))
    by_program: dict[str, dict] = {}
    for r in rows:
        by_program.setdefault(r["program_id"], {})[r["entry_type"]] = r["net"]
    out = []
    for program_id, t in by_program.items():
        opening, accruals = t.get("opening", ZERO), t.get("accrual", ZERO)
        adjustments = sum((t.get(k, ZERO) for k in ADJUSTMENTS), ZERO)
        settled = -t.get("clearing", ZERO)
        out.append({"program_id": program_id, "origin": period, "opening": opening, "accruals": accruals,
                    "estimate_adjustments": adjustments, "settled": settled,
                    "ending": opening + accruals + adjustments - settled, "outstanding": sum(t.values(), ZERO)})
    return out


def customer_package(cur: psycopg.Cursor, period: str, as_of: datetime, customer_id: str) -> dict:
    p = one_row(cur, "SELECT * FROM periods WHERE period = %s AND customer_id = %s", (period, customer_id))
    signed = p and p["signed_at"] and p["signed_at"] <= as_of
    postings = entries_as_of(cur, period, as_of, customer_id=customer_id)
    findings = all_rows(cur, """SELECT f.*, e.id AS escalation_id, e.to_role, e.question, e.answer, e.answered_by,
                                       e.answered_at, e.became_precedent_id
                                FROM findings f LEFT JOIN escalations e ON e.finding_id = f.id AND e.created_at <= %s
                                WHERE f.period = %s AND f.customer_id = %s AND f.created_at <= %s ORDER BY f.id, e.id""",
                        (as_of, period, customer_id, as_of))
    gates = {}
    for gate in GATES:
        r = gate(cur, period, customer_id, as_of)
        gates[r.name] = {"name": r.name, "description": r.description, "passed": r.passed, "violations": r.violations}
    return {
        "customer_id": customer_id,
        "state": p["state"] if p else None,
        "signed_by": p["signed_by"] if signed else None,
        "signed_at": p["signed_at"] if signed else None,
        "postings": postings,
        "balances": balances_as_of(cur, period, as_of, customer_id),
        "totals": {"debit": sum((e["debit"] for e in postings), ZERO), "credit": sum((e["credit"] for e in postings), ZERO)},
        "findings": findings,
        "gates": gates,
        "reconciliation": reconciliation(cur, period, as_of, customer_id),
    }


def package(cur: psycopg.Cursor, period: str, as_of: datetime) -> dict:
    flux = all_rows(cur, "SELECT * FROM flux_commentary WHERE period = %s AND decision_time <= %s ORDER BY id",
                    (period, as_of))
    return {"period": period, "as_of": as_of, "flux": flux,
            "customers": [customer_package(cur, period, as_of, c) for c in CUSTOMERS]}
