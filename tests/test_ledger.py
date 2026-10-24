"""The write path, restatement, and the as-of reads the interrogation box is built on."""

from datetime import date, datetime
from decimal import Decimal

import psycopg
import pytest

from helpers import accrue, terms
from tpa.asof import balances_as_of, entries_as_of, entry_history, landed, terms_as_of
from tpa.constants import Account
from tpa.gates import sign_period
from tpa.ledger import LedgerError, Line, post_catch_up, post_journal, reverse_lines

LIAB = Account.ACCRUED_TRADE_PROMO
FEB_CLOSE = datetime(2026, 2, 28, 18)
FEB_SIGNED = datetime(2026, 3, 2, 9, 14)
AUG_RESTATE = datetime(2026, 8, 19, 10)


@pytest.fixture
def signed_feb(base):
    with base.cursor() as cur:
        j = accrue(cur, "2026-02", "180100.00", FEB_CLOSE)
        sign_period(cur, "2026-02", "WMT", "controller", FEB_SIGNED)
    base.commit()
    return base, j


def test_february_has_two_correct_answers(signed_feb):
    conn, j = signed_feb
    with conn.cursor() as cur:
        jid = post_catch_up(cur, expense_line=f"{j}-1", liability_line=f"{j}-2", delta=Decimal("34250.00"),
                            decision_time=AUG_RESTATE, approved_by="controller")
    conn.commit()
    with conn.cursor() as cur:
        assert balances_as_of(cur, "2026-02", datetime(2026, 3, 1))[LIAB] == Decimal("-180100.00")
        assert balances_as_of(cur, "2026-02", datetime(2026, 8, 20))[LIAB] == Decimal("-214350.00")
        assert [e["id"] for e in entries_as_of(cur, "2026-02", datetime(2026, 8, 20), account=LIAB)] == [f"{j}-2", f"{jid}-2"]
        cur.execute("SELECT state, signed_by FROM periods WHERE period = '2026-02'")
        assert cur.fetchone() == ("RESTATED", "controller")


def test_restated_period_still_refuses_ordinary_entries(signed_feb):
    conn, j = signed_feb
    with conn.cursor() as cur:
        post_catch_up(cur, expense_line=f"{j}-1", liability_line=f"{j}-2", delta=Decimal("1"),
                      decision_time=AUG_RESTATE, approved_by="controller")
        with pytest.raises(psycopg.errors.RaiseException, match="only restating"):
            accrue(cur, "2026-02", "5.00", AUG_RESTATE)


def test_clawback_flips_sides(signed_feb):
    conn, j = signed_feb
    with conn.cursor() as cur:
        post_catch_up(cur, expense_line=f"{j}-1", liability_line=f"{j}-2", delta=Decimal("-100.00"),
                      decision_time=AUG_RESTATE, approved_by="controller")
        assert balances_as_of(cur, "2026-02", AUG_RESTATE)[LIAB] == Decimal("-180000.00")


def test_entry_history_walks_the_chain(signed_feb):
    conn, j = signed_feb
    with conn.cursor() as cur:
        first = post_catch_up(cur, expense_line=f"{j}-1", liability_line=f"{j}-2", delta=Decimal("34250.00"),
                              decision_time=AUG_RESTATE, approved_by="controller")
        second = post_catch_up(cur, expense_line=f"{first}-1", liability_line=f"{first}-2", delta=Decimal("-50.00"),
                               decision_time=datetime(2026, 9, 3), approved_by="controller")
        h = entry_history(cur, f"{j}-2")
    assert h["line"]["credit"] == Decimal("180100.00")
    assert [r["id"] for r in h["restated_by"]] == [f"{first}-2", f"{second}-2"]
    assert h["approved_by"]["role"] == "controller"
    assert [r["id"] for r in h["journal"]] == [f"{j}-1", f"{j}-2"]


def test_reverse_lines_mirrors(base):
    with base.cursor() as cur:
        j = accrue(cur, "2026-02", "100.00", FEB_CLOSE)
        r = reverse_lines(cur, [f"{j}-1", f"{j}-2"], period="2026-03", decision_time=datetime(2026, 3, 1))
        assert balances_as_of(cur, "2026-03", datetime(2026, 3, 2))[LIAB] == Decimal("100.00")
        h = entry_history(cur, f"{j}-2")
        assert [x["id"] for x in h["reversed_by"]] == [f"{r}-2"]
        assert h["reversed_by"][0]["valid_time"] == date(2026, 2, 28)


def test_post_journal_rejects_bad_journals(base):
    with base.cursor() as cur:
        with pytest.raises(LedgerError, match="does not balance"):
            post_journal(cur, entry_type="accrual", period="2026-02", customer_id="WMT", decision_time=FEB_CLOSE,
                         lines=[Line(LIAB, credit=Decimal("1")), Line(Account.TRADE_PROMO_EXPENSE, debit=Decimal("2"))])
        with pytest.raises(LedgerError, match="must name the entry"):
            post_journal(cur, entry_type="restatement", period="2026-02", customer_id="WMT", decision_time=FEB_CLOSE,
                         lines=[Line(LIAB, credit=Decimal("1")), Line(Account.TRADE_PROMO_EXPENSE, debit=Decimal("1"))])


def test_terms_as_of_prefers_latest_knowledge(base):
    with base.cursor() as cur:
        terms(cur)                                                     # as signed, open-ended
        learned = datetime(2026, 8, 19, 9)
        terms(cur, valid_to=date(2026, 2, 13), decided=learned, term_id="PT-2")
        terms(cur, rate="4.20", valid_from=date(2026, 2, 14), decided=learned, term_id="PT-3")
        assert terms_as_of(cur, "TP-0214", date(2026, 3, 1), datetime(2026, 7, 1))["rate"] == Decimal("3.80")
        assert terms_as_of(cur, "TP-0214", date(2026, 3, 1), datetime(2026, 8, 20))["rate"] == Decimal("4.20")
        assert terms_as_of(cur, "TP-0214", date(2026, 2, 1), datetime(2026, 8, 20))["id"] == "PT-2"


def test_landed_hides_the_future(base):
    with base.cursor() as cur:
        for i, avail in enumerate((date(2026, 2, 3), date(2026, 3, 9)), 1):
            cur.execute(
                """INSERT INTO shipments (id, customer_id, program_id, period, cases, gross_price, ship_date, available_at)
                   VALUES (%s, 'WMT', 'TP-0214', %s, 10, 42, %s, %s)""",
                (f"SH-{i}", avail.strftime("%Y-%m"), avail, avail),
            )
        assert [r["id"] for r in landed(cur, "shipments", date(2026, 2, 28))] == ["SH-1"]
        assert [r["id"] for r in landed(cur, "shipments", date(2026, 3, 31), since=date(2026, 2, 28))] == ["SH-2"]
        with pytest.raises(ValueError):
            landed(cur, "ledger_entries", date(2026, 3, 31))
