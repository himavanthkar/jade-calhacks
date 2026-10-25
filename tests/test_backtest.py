"""The backtest on General Mills' real 10-Ks. No database."""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from tpa import backtest
from tpa.filings import YEARS

EXTRACTED = Path(__file__).resolve().parent.parent / "data" / "edgar" / "extracted.json"


@pytest.mark.skipif(not EXTRACTED.exists(), reason="run scripts/pull_10k.py to re-read the filings")
def test_cited_figures_match_the_filings():
    data = json.loads(EXTRACTED.read_text())
    filings = {f["accession"]: f for f in data["filings"]}
    q4 = {(q["end"], q["accession"]): q for q in data["quarters"]}
    for y in YEARS:
        got = filings[y.accession]
        assert got["filed"] == y.filed and got["fiscal_year_end"] == y.period_end
        assert Decimal(got["net_sales_usd"]) / 1_000_000 == y.net_sales_musd
        assert Decimal(q4[(y.period_end, y.accession)]["net_sales_usd"]) / 1_000_000 == y.q4_net_sales_musd
        trade = got["accrued_trade_and_coupon_liabilities_musd"]
        assert (trade["value"], trade["prior"]) == (y.accrued_trade_musd, y.accrued_trade_prior_musd)
        assert got["walmart_share_of_net_sales_pct"]["value"] == y.walmart_share_pct


def test_no_close_sees_its_own_filing_or_a_later_one():
    res = backtest.run()
    assert [c["fiscal_year"] for c in res["closes"]] == [2021, 2022, 2023, 2024, 2025, 2026]
    for c in res["closes"]:
        assert max(c["known_filings"]) == c["fiscal_year"] - 1


def test_an_estimator_cannot_peek_at_the_answer():
    """Changing a year's reported liability changes no estimate made at that year's close."""
    res = backtest.run()
    for i, y in enumerate(YEARS[1:], start=1):
        moved = list(YEARS)
        moved[i] = replace(y, accrued_trade_musd=y.accrued_trade_musd * 10)
        close = next(c for c in backtest.run(moved)["closes"] if c["fiscal_year"] == y.fiscal_year)
        before = next(c for c in res["closes"] if c["fiscal_year"] == y.fiscal_year)
        assert close["estimates_musd"] == before["estimates_musd"]


def test_audited_books_raise_no_analytical_review_alarm():
    res = backtest.run()
    assert res["analytical_review"]["false_alarms"] == 0
    assert res["restatements"] == []


def test_a_restated_year_end_is_caught():
    years = list(YEARS)
    years[3] = replace(years[3], accrued_trade_prior_musd=years[2].accrued_trade_musd + 15)
    assert backtest.run(years)["restatements"] == [
        {"fiscal_year": years[2].fiscal_year, "first_filed_musd": years[2].accrued_trade_musd,
         "restated_musd": years[2].accrued_trade_musd + 15, "restated_in": years[3].fiscal_year}]


def test_a_tight_review_tolerance_would_have_cried_wolf():
    """The largest real year-on-year drift is about 21%: a 15% tolerance flags audited books."""
    res = backtest.run(tolerance=Decimal("0.15"))
    assert res["analytical_review"]["false_alarms"] >= 1
