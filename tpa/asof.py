"""Reading the books, the terms and the source data as they stood at a point in time.

Everything the interrogation box does reduces to `balances_as_of`: same table, same
period, two correct answers depending on `as_of`.
"""

from datetime import date, datetime
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

from tpa.constants import Account

# Source tables the month stepper reveals by available_at.
LANDED_TABLES = (
    "trade_programs", "program_amendments", "shipments", "returns", "invoices",
    "deductions", "claim_backup", "disputes",
)


def _dict_cur(cur: psycopg.Cursor) -> psycopg.Cursor:
    return cur.connection.cursor(row_factory=dict_row)


def balances_as_of(cur: psycopg.Cursor, period: str, as_of: datetime,
                   customer_id: str | None = None) -> dict[str, Decimal]:
    """The spec's one query: SUM(debit) - SUM(credit) per account for a period, known by `as_of`."""
    cur.execute(
        """SELECT account, SUM(debit) - SUM(credit)
           FROM ledger_entries
           WHERE period = %s AND decision_time <= %s AND (%s::text IS NULL OR customer_id = %s)
           GROUP BY account ORDER BY account""",
        (period, as_of, customer_id, customer_id),
    )
    return dict(cur.fetchall())


def entries_as_of(cur: psycopg.Cursor, period: str, as_of: datetime, *, account: str | None = None,
                  customer_id: str | None = None, program_id: str | None = None) -> list[dict]:
    """The lines behind a balance, so every number traces to an entry."""
    with _dict_cur(cur) as c:
        c.execute(
            """SELECT * FROM ledger_entries
               WHERE period = %s AND decision_time <= %s
                 AND (%s::text IS NULL OR account = %s)
                 AND (%s::text IS NULL OR customer_id = %s)
                 AND (%s::text IS NULL OR program_id = %s)
               ORDER BY decision_time, id""",
            (period, as_of, account, account, customer_id, customer_id, program_id, program_id),
        )
        return c.fetchall()


def liability_outstanding(cur: psycopg.Cursor, as_of: datetime, *, through_period: str | None = None,
                          customer_id: str | None = None) -> dict[tuple[str, date], Decimal]:
    """Accrued liability still open per (program, origin valid_time): credits minus debits on 2300."""
    cur.execute(
        """SELECT program_id, valid_time, SUM(credit) - SUM(debit)
           FROM ledger_entries
           WHERE account = %s AND decision_time <= %s
             AND (%s::text IS NULL OR period <= %s)
             AND (%s::text IS NULL OR customer_id = %s)
           GROUP BY program_id, valid_time ORDER BY program_id, valid_time""",
        (Account.ACCRUED_TRADE_PROMO, as_of, through_period, through_period, customer_id, customer_id),
    )
    return {(prog, vt): bal for prog, vt, bal in cur.fetchall()}


def entry_history(cur: psycopg.Cursor, entry_id: str) -> dict | None:
    """Everything known about one ledger line: its journal, what it reverses or restates, what
    later reversed or restated it, the deduction it settles and the finding that caused it."""
    with _dict_cur(cur) as c:
        c.execute("SELECT * FROM ledger_entries WHERE id = %s", (entry_id,))
        line = c.fetchone()
        if line is None:
            return None
        c.execute("SELECT * FROM ledger_entries WHERE journal_id = %s ORDER BY id", (line["journal_id"],))
        journal = c.fetchall()
        c.execute("SELECT * FROM ledger_entries WHERE reversal_of = %s ORDER BY decision_time, id", (entry_id,))
        reversed_by = c.fetchall()

        # Restatements can restate restatements: walk down the chain.
        restated_by, frontier = [], [entry_id]
        while frontier:
            c.execute("SELECT * FROM ledger_entries WHERE restates = ANY(%s) ORDER BY decision_time, id", (frontier,))
            found = c.fetchall()
            restated_by += found
            frontier = [r["id"] for r in found]

        target = None
        if line["reversal_of"] or line["restates"]:
            c.execute("SELECT * FROM ledger_entries WHERE id = %s", (line["reversal_of"] or line["restates"],))
            target = c.fetchone()

        deduction = finding = approver = None
        if line["deduction_id"]:
            c.execute("SELECT * FROM deductions WHERE id = %s", (line["deduction_id"],))
            deduction = c.fetchone()
        if line["source_finding_id"]:
            c.execute("SELECT * FROM findings WHERE id = %s", (line["source_finding_id"],))
            finding = c.fetchone()
        if line["approved_by"]:
            c.execute("SELECT * FROM actors WHERE id = %s", (line["approved_by"],))
            approver = c.fetchone()

    return {
        "line": line, "journal": journal, "reverses_or_restates": target,
        "reversed_by": reversed_by, "restated_by": restated_by,
        "deduction": deduction, "finding": finding, "approved_by": approver,
    }


def terms_as_of(cur: psycopg.Cursor, program_id: str, on: date, as_of: datetime) -> dict | None:
    """The term in force on `on`, as we knew it at `as_of`. The latest decision wins, so after
    AM-02 lands TP-0214 reads $4.20 from 2026-02-14; before, $3.80 for the whole year."""
    with _dict_cur(cur) as c:
        c.execute(
            """SELECT * FROM program_terms
               WHERE program_id = %s AND decision_time <= %s
                 AND valid_from <= %s AND (valid_to IS NULL OR valid_to >= %s)
               ORDER BY decision_time DESC, valid_from DESC LIMIT 1""",
            (program_id, as_of, on, on),
        )
        return c.fetchone()


def landed(cur: psycopg.Cursor, table: str, sim_date: date, *, customer_id: str | None = None,
           since: date | None = None) -> list[dict]:
    """Source rows that have reached our systems by `sim_date` (optionally only those after `since`)."""
    if table not in LANDED_TABLES:
        raise ValueError(f"{table} is not a landed source table")
    has_customer = table not in ("program_amendments", "claim_backup", "disputes")
    with _dict_cur(cur) as c:
        c.execute(
            f"""SELECT * FROM {table}
                WHERE available_at <= %s AND (%s::date IS NULL OR available_at > %s)
                {"AND (%s::text IS NULL OR customer_id = %s)" if has_customer else ""}
                ORDER BY available_at, id""",
            (sim_date, since, since, *((customer_id, customer_id) if has_customer else ())),
        )
        return c.fetchall()


def sim_clock(cur: psycopg.Cursor) -> tuple[str, date]:
    """(the period the next step will run, the last simulated date fully processed)."""
    cur.execute("SELECT current_period, sim_date FROM sim_clock")
    return cur.fetchone()
