"""The one write path into the ledger. Accrual, reversal, clearing and restatement all post through here."""

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
            memo, reversal_of, restates, source_finding_id, valid_time, decision_time, approved_by)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        [
            (f"{journal_id}-{i}", journal_id, entry_type, period, customer_id,
             line.program_id or program_id, line.account, line.debit, line.credit, line.memo,
             line.reversal_of, line.restates, source_finding_id, line.valid_time or default_valid,
             decision_time, approved_by)
            for i, line in enumerate(lines, 1)
        ],
    )
    return journal_id
