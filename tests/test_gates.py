"""Each gate passes on clean books and fails, naming the rows, on the error it exists for."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from helpers import accrue, clear, deduction, terms
from tpa.constants import Account
from tpa.gates import GateFailure, run_gates, sign_period
from tpa.ledger import Line, post_journal

AT = datetime(2026, 9, 1)
FEB_END = date(2026, 2, 28)


def gate(cur, name, period="2026-02"):
    return run_gates(cur, period, "WMT", AT)[name]


def test_clean_books_pass_every_gate(base):
    with base.cursor() as cur:
        terms(cur)
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        deduction(cur, "DD-1", "2026-02")
        clear(cur, "2026-03", "60.00", FEB_END, datetime(2026, 3, 20), "DD-1")
        assert all(r.passed for r in run_gates(cur, "2026-03", "WMT", AT).values())


def test_over_clearing_fails(base):
    with base.cursor() as cur:
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        clear(cur, "2026-03", "150.00", FEB_END, datetime(2026, 3, 20))
        g = gate(cur, "cleared_within_accrued", "2026-03")
    assert not g.passed
    assert g.violations[0]["key"] == "accrual:TP-0214:2026-02"
    assert g.violations[0]["over_cleared_by"] == Decimal("50.00")


def test_stale_accrual_fails_after_grace(base):
    with base.cursor() as cur:
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        assert gate(cur, "no_stale_accruals", "2026-04").passed          # age 2, allowed 0 + 2
        g = gate(cur, "no_stale_accruals", "2026-05")
    assert not g.passed and g.violations[0]["key"] == "accrual:TP-0214:2026-02"


def test_stale_grace_follows_the_customer_claim_lag(base):
    with base.cursor() as cur:
        for i, claimed in enumerate(("2025-01", "2025-02", "2025-03"), 1):   # history: claims land 5 months on
            y, m = (int(x) for x in claimed.split("-"))
            deduction(cur, f"DD-H{i}", claimed, taken=date(y, m + 5, 10))
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        assert gate(cur, "no_stale_accruals", "2026-09").passed           # age 7, allowed 5 + 2
        assert not gate(cur, "no_stale_accruals", "2026-10").passed


def test_partly_cleared_accrual_is_not_stale(base):
    with base.cursor() as cur:
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        clear(cur, "2026-03", "40.00", FEB_END, datetime(2026, 3, 20))
        assert gate(cur, "no_stale_accruals", "2026-08").passed


def test_claim_outside_window_fails(base):
    with base.cursor() as cur:
        terms(cur)
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        deduction(cur, "DD-1", "2025-12")
        clear(cur, "2026-03", "10.00", FEB_END, datetime(2026, 3, 20), "DD-1")
        g = gate(cur, "claims_inside_window", "2026-03")
    assert not g.passed and g.violations[0]["deduction_id"] == "DD-1"


def test_claim_without_terms_is_unverifiable(base):
    with base.cursor() as cur:
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        deduction(cur, "DD-1", "2026-02")
        clear(cur, "2026-03", "10.00", FEB_END, datetime(2026, 3, 20), "DD-1")
        g = gate(cur, "claims_inside_window", "2026-03")
    assert not g.passed and "cannot verify" in g.violations[0]["reason"]


def test_reversal_must_mirror_and_happen_once(base):
    with base.cursor() as cur:
        j = accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        for amount in ("90.00", "90.00"):
            a = Decimal(amount)
            post_journal(cur, entry_type="reversal", period="2026-03", customer_id="WMT", program_id="TP-0214",
                         decision_time=datetime(2026, 3, 1),
                         lines=[Line(Account.ACCRUED_TRADE_PROMO, debit=a, valid_time=FEB_END, reversal_of=f"{j}-2"),
                                Line(Account.TRADE_PROMO_EXPENSE, credit=a, valid_time=FEB_END, reversal_of=f"{j}-1")])
        g = gate(cur, "reversals_mirror", "2026-03")
    reasons = {v["reason"] for v in g.violations}
    assert reasons == {"does not mirror the original line", "reversed more than once"}


def test_sign_blocks_on_gate_failure(base):
    with base.cursor() as cur:
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        clear(cur, "2026-02", "150.00", FEB_END, datetime(2026, 2, 28, 12))
        with pytest.raises(GateFailure, match="cleared_within_accrued"):
            sign_period(cur, "2026-02", "WMT", "controller", datetime(2026, 3, 2))
        cur.execute("SELECT state, signed_at, gate_results->'cleared_within_accrued'->>'passed' FROM periods "
                    "WHERE period = '2026-02'")
        assert cur.fetchone() == ("OPEN", None, "false")


def test_only_controller_or_reviewer_signs(base):
    with base.cursor() as cur, pytest.raises(PermissionError):
        sign_period(cur, "2026-02", "WMT", "sales.walmart", datetime(2026, 3, 2))


def test_sign_records_a_permanent_signoff(base):
    with base.cursor() as cur:
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28))
        sign_period(cur, "2026-02", "WMT", "controller", datetime(2026, 3, 2))
        cur.execute("SELECT state FROM periods WHERE period = '2026-02'")
        assert cur.fetchone() == ("SIGNED",)
        cur.execute("SELECT signed_by FROM period_signoffs")
        assert cur.fetchall() == [("controller",)]
