"""The close's analytical review: the total liability against General Mills' reported ratio."""

from datetime import datetime
from decimal import Decimal

from helpers import accrue
from tpa.constants import Account
from tpa.ledger import Line, post_journal
from tpa.package import package
from tpa.review import review, write_review
from tpa.seed import calibration as cal

CLOSE = datetime(2026, 2, 28, 21)


def sell(cur, amount: str):
    a = Decimal(amount)
    post_journal(cur, entry_type="revenue", period="2026-02", customer_id="WMT", decision_time=datetime(2026, 2, 28, 18),
                 lines=[Line(Account.ACCOUNTS_RECEIVABLE, debit=a), Line(Account.GROSS_SALES, credit=a)])


def test_a_close_only_compares_with_a_published_filing():
    assert cal.latest_filing("2025-06-25") is None
    assert cal.latest_filing("2026-06-30") is cal.FY2025
    assert cal.latest_filing("2026-07-01") is cal.FY2026
    assert round(cal.trade_liability_ratio(cal.FY2026), 4) == Decimal("0.0268")


def test_inside_the_range_is_commentary(base):
    with base.cursor() as cur:
        sell(cur, "1000.00")
        accrue(cur, "2026-02", "100.00", datetime(2026, 2, 28, 18))      # 100 / ((1000 − 100) × 12 / 2) = 1.85%
        r = review(cur, "2026-02", CLOSE)
    assert r["within_range"] is True and r["source"]["fiscal_year"] == 2025
    assert r["ratio"].quantize(Decimal("0.0001")) == Decimal("0.0185")
    assert "Within the review range of 1.21% to 3.62%" in r["narrative"]


def test_outside_the_range_needs_the_reviewers_explanation(base):
    with base.cursor() as cur:
        sell(cur, "1000.00")
        accrue(cur, "2026-02", "300.00", datetime(2026, 2, 28, 18))      # 300 / 4,200 = 7.14%
        write_review(cur, "2026-02", CLOSE)
        pkg = package(cur, "2026-02", CLOSE)
    assert pkg["analytical_review"]["within_range"] is False and pkg["needs_explanation"] is True
    assert "the close reviewer explains the difference before signing" in pkg["analytical_review"]["narrative"]
