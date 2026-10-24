from datetime import date, datetime
from decimal import Decimal

from tpa.constants import Account
from tpa.ledger import Line, post_journal


def accrue(cur, period: str, amount: str, decided: datetime, program_id: str = "TP-0214") -> str:
    a = Decimal(amount)
    return post_journal(
        cur, entry_type="accrual", period=period, customer_id="WMT", program_id=program_id,
        decision_time=decided, approved_by="controller",
        lines=[Line(Account.TRADE_PROMO_EXPENSE, debit=a), Line(Account.ACCRUED_TRADE_PROMO, credit=a)],
    )


def clear(cur, period: str, amount: str, origin_end: date, decided: datetime, deduction_id: str | None = None) -> str:
    a = Decimal(amount)
    return post_journal(
        cur, entry_type="clearing", period=period, customer_id="WMT", program_id="TP-0214",
        decision_time=decided, approved_by="controller",
        lines=[Line(Account.ACCRUED_TRADE_PROMO, debit=a, valid_time=origin_end, deduction_id=deduction_id),
               Line(Account.DEDUCTIONS_PENDING, credit=a, valid_time=origin_end, deduction_id=deduction_id)],
    )


def deduction(cur, ded_id: str, claimed_period: str, amount: str = "100.00", taken: date = date(2026, 7, 10)) -> None:
    cur.execute(
        """INSERT INTO deductions (id, customer_id, program_id, amount, reason_code, taken_date,
                                   claimed_period, available_at)
           VALUES (%s, 'WMT', 'TP-0214', %s, 'SB', %s, %s, %s)""",
        (ded_id, amount, taken, claimed_period, taken),
    )


def terms(cur, rate: str = "3.80", valid_from: date = date(2026, 1, 1), valid_to: date | None = None,
          decided: datetime = datetime(2025, 12, 9, 9), term_id: str = "PT-1") -> None:
    cur.execute(
        """INSERT INTO program_terms (id, program_id, customer_id, program_type, rate, rate_unit,
                                      base_definition, projected_redemption, window_start, window_end,
                                      requires_proof, valid_from, valid_to, decision_time)
           VALUES (%s, 'TP-0214', 'WMT', 'scan_back', %s, 'per_case', 'scan_units', 0.92,
                   '2026-01-01', '2026-12-31', false, %s, %s, %s)""",
        (term_id, rate, valid_from, valid_to, decided),
    )
