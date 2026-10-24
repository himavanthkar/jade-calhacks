"""The ledger's guarantees are enforced by the database. These tests prove each one."""

import psycopg
import pytest

from tpa.constants import Account, live_month, month_for_period, period_for_month


def post(cur, journal_id, lines, period="2026-02", restates=None, entry_type="accrual"):
    """lines: [(account, debit, credit)]"""
    for i, (account, debit, credit) in enumerate(lines, 1):
        cur.execute(
            """INSERT INTO ledger_entries
               (id, journal_id, entry_type, period, customer_id, program_id, account,
                debit, credit, restates, valid_time, decision_time, approved_by)
               VALUES (%s, %s, %s, %s, 'WMT', 'TP-0214', %s, %s, %s, %s, %s, '2026-02-28 18:00', 'controller')""",
            (f"{journal_id}-{i}", journal_id, entry_type, period, account, debit, credit,
             restates[i - 1] if restates else None, f"{period}-28"),
        )


ACCRUAL = [(Account.TRADE_PROMO_EXPENSE, 180100, 0), (Account.ACCRUED_TRADE_PROMO, 0, 180100)]


def test_balanced_journal_commits(base):
    with base.cursor() as cur:
        post(cur, "JE-1184", ACCRUAL)
    base.commit()
    with base.cursor() as cur:
        cur.execute("SELECT SUM(debit), SUM(credit) FROM ledger_entries")
        assert cur.fetchone() == (180100, 180100)


def test_unbalanced_journal_rejected_at_commit(base):
    with base.cursor() as cur:
        post(cur, "JE-1", [(Account.TRADE_PROMO_EXPENSE, 100, 0), (Account.ACCRUED_TRADE_PROMO, 0, 99)])
    with pytest.raises(psycopg.errors.RaiseException, match="does not balance"):
        base.commit()


def test_line_must_be_one_sided(base):
    with base.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        post(cur, "JE-1", [(Account.TRADE_PROMO_EXPENSE, 100, 100)])


@pytest.mark.parametrize("sql", [
    "UPDATE ledger_entries SET debit = 1 WHERE id = 'JE-1184-1'",
    "DELETE FROM ledger_entries WHERE id = 'JE-1184-1'",
    "TRUNCATE ledger_entries CASCADE",
])
def test_ledger_is_insert_only(base, sql):
    with base.cursor() as cur:
        post(cur, "JE-1184", ACCRUAL)
    base.commit()
    with base.cursor() as cur, pytest.raises(psycopg.errors.RaiseException, match="insert-only"):
        cur.execute(sql)


def test_signed_period_rejects_ordinary_entries(base):
    with base.cursor() as cur:
        post(cur, "JE-1184", ACCRUAL)
        cur.execute("UPDATE periods SET state = 'SIGNED' WHERE period = '2026-02'")
    base.commit()
    with base.cursor() as cur, pytest.raises(psycopg.errors.RaiseException, match="only restating"):
        post(cur, "JE-1190", ACCRUAL)


def test_signed_period_accepts_restatement(base):
    with base.cursor() as cur:
        post(cur, "JE-1184", ACCRUAL)
        cur.execute("UPDATE periods SET state = 'SIGNED' WHERE period = '2026-02'")
    base.commit()
    catch_up = [(Account.TRADE_PROMO_EXPENSE, 34250, 0), (Account.ACCRUED_TRADE_PROMO, 0, 34250)]
    with base.cursor() as cur:
        post(cur, "JE-1251", catch_up, restates=["JE-1184-1", "JE-1184-2"], entry_type="restatement")
    base.commit()


def test_signed_period_cannot_reopen(base):
    with base.cursor() as cur:
        cur.execute("UPDATE periods SET state = 'SIGNED' WHERE period = '2026-02'")
    base.commit()
    with base.cursor() as cur, pytest.raises(psycopg.errors.RaiseException, match="only move to RESTATED"):
        cur.execute("UPDATE periods SET state = 'OPEN' WHERE period = '2026-02'")


def test_deduction_clearer_and_approver_differ(base):
    with base.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
        cur.execute(
            """INSERT INTO deductions (id, customer_id, amount, reason_code, taken_date, claimed_period,
                                       cleared_by, approved_by, available_at)
               VALUES ('DD-1', 'WMT', 10, 'SCAN', '2026-05-01', '2026-02', 'controller', 'controller', '2026-05-01')"""
        )


def test_period_helpers():
    assert period_for_month(1) == "2025-01"
    assert period_for_month(13) == "2026-01"
    assert period_for_month(24) == "2026-12"
    assert month_for_period("2026-08") == 20
    assert live_month("2026-08") == 8
