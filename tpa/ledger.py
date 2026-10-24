"""The one write path into the ledger. Accrual, reversal, clearing and restatement all post through here.

Posting conventions (the contract the gates check):

* accrual      Dr 4100 expense / Cr 2300 liability, one journal per program per origin
               period, valid_time = last day of the origin (shipment) period.
* reversal     the exact mirror of an accrual or opening line: same account, program,
               valid_time and amount, opposite side, reversal_of = that line. Used when
               an estimate is re-made: reverse the old line, post the new accrual.
* clearing     Dr 2300 liability / Cr 1250 deductions pending, valid_time = the origin
               period the deduction relates to, deduction_id set.
* restatement  posted into the closed period it corrects, every line naming the line
               it restates. Use `post_catch_up`.

Outstanding liability for (program, origin) is credits minus debits on 2300 for lines
with that program and valid_time. It must never go negative.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import psycopg

from tpa.constants import ENTRY_TYPES, period_end

ZERO = Decimal("0")


class LedgerError(ValueError):
    pass


@dataclass(frozen=True)
class Line:
    account: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    memo: str | None = None
    program_id: str | None = None   # defaults to the journal's program
    valid_time: date | None = None  # defaults to the last day of the period
    reversal_of: str | None = None
    restates: str | None = None
    deduction_id: str | None = None


def post_journal(
    cur: psycopg.Cursor,
    *,
    entry_type: str,
    period: str,
    customer_id: str,
    decision_time: datetime,
    lines: list[Line],
    approved_by: str | None = None,
    program_id: str | None = None,
    source_finding_id: str | None = None,
) -> str:
    """Insert one balanced journal and return its id. Does not commit: the caller owns the transaction.

    The database re-checks balance at commit and refuses ordinary entries into signed periods;
    the checks here exist to fail early with a readable message.
    """
    if entry_type not in ENTRY_TYPES:
        raise LedgerError(f"unknown entry_type {entry_type!r}")
    if not lines:
        raise LedgerError("a journal needs at least one line")
    for line in lines:
        if (line.debit > 0) == (line.credit > 0) or line.debit < 0 or line.credit < 0:
            raise LedgerError(f"line on {line.account} must have exactly one positive side")
    debits = sum((line.debit for line in lines), ZERO)
    credits = sum((line.credit for line in lines), ZERO)
    if debits != credits:
        raise LedgerError(f"journal does not balance: debits {debits} <> credits {credits}")
    if entry_type == "restatement" and not all(line.restates for line in lines):
        raise LedgerError("every restatement line must name the entry it restates")

    cur.execute("SELECT nextval('journal_seq')")
    journal_id = f"JE-{cur.fetchone()[0]}"
    default_valid = period_end(period)
    cur.executemany(
        """INSERT INTO ledger_entries
           (id, journal_id, entry_type, period, customer_id, program_id, account, debit, credit,
            memo, reversal_of, restates, source_finding_id, deduction_id, valid_time, decision_time, approved_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        [
            (f"{journal_id}-{i}", journal_id, entry_type, period, customer_id,
             line.program_id or program_id, line.account, line.debit, line.credit, line.memo,
             line.reversal_of, line.restates, source_finding_id, line.deduction_id, line.valid_time or default_valid,
             decision_time, approved_by)
            for i, line in enumerate(lines, 1)
        ],
    )
    return journal_id


def reverse_lines(
    cur: psycopg.Cursor,
    line_ids: list[str],
    *,
    period: str,
    decision_time: datetime,
    approved_by: str | None = None,
    memo: str | None = None,
) -> str:
    """Post the exact mirror of existing lines (normally one accrual journal) into `period`."""
    cur.execute(
        """SELECT id, customer_id, program_id, account, debit, credit, valid_time
           FROM ledger_entries WHERE id = ANY(%s) ORDER BY id""",
        (line_ids,),
    )
    originals = cur.fetchall()
    if len(originals) != len(set(line_ids)):
        raise LedgerError(f"unknown ledger lines in {line_ids}")
    customers = {o[1] for o in originals}
    if len(customers) != 1:
        raise LedgerError("a reversal journal covers one customer")
    return post_journal(
        cur, entry_type="reversal", period=period, customer_id=customers.pop(),
        decision_time=decision_time, approved_by=approved_by,
        lines=[Line(account=acct, debit=cr, credit=dr, memo=memo or f"Reverses {lid}",
                    program_id=prog, valid_time=vt, reversal_of=lid)
               for lid, _, prog, acct, dr, cr, vt in originals],
    )


def post_catch_up(
    cur: psycopg.Cursor,
    *,
    expense_line: str,
    liability_line: str,
    delta: Decimal,
    decision_time: datetime,
    approved_by: str,
    source_finding_id: str | None = None,
    memo: str | None = None,
) -> str | None:
    """Restate one closed accrual by `delta` (positive = catch-up, negative = clawback).

    The new journal lands in the original line's period with a later decision_time, so
    `balances_as_of(period, before)` still shows what was posted and
    `balances_as_of(period, after)` shows the restated truth. Moves a signed period to RESTATED.
    """
    if delta == 0:
        return None
    cur.execute(
        "SELECT id, period, customer_id, program_id, account, valid_time FROM ledger_entries WHERE id = ANY(%s)",
        ([expense_line, liability_line],),
    )
    found = {r[0]: r for r in cur.fetchall()}
    if set(found) != {expense_line, liability_line}:
        raise LedgerError("both restated lines must exist")
    exp, liab = found[expense_line], found[liability_line]
    if exp[1:4] != liab[1:4]:
        raise LedgerError("restated lines must share period, customer and program")
    _, period, customer_id, program_id, _, _ = exp
    amount = abs(delta)
    catch_up = delta > 0
    text = memo or f"{'Catch-up' if catch_up else 'Clawback'} restating {liability_line}"
    journal_id = post_journal(
        cur, entry_type="restatement", period=period, customer_id=customer_id, program_id=program_id,
        decision_time=decision_time, approved_by=approved_by, source_finding_id=source_finding_id,
        lines=[
            Line(account=exp[4], debit=amount if catch_up else ZERO, credit=ZERO if catch_up else amount,
                 memo=text, valid_time=exp[5], restates=expense_line),
            Line(account=liab[4], debit=ZERO if catch_up else amount, credit=amount if catch_up else ZERO,
                 memo=text, valid_time=liab[5], restates=liability_line),
        ],
    )
    cur.execute(
        "UPDATE periods SET state = 'RESTATED' WHERE period = %s AND customer_id = %s AND state IN ('SIGNED', 'CLOSED')",
        (period, customer_id),
    )
    return journal_id
