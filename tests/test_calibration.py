"""The simulation against the real 10-K figures. No database."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from tpa.seed import calibration as cal
from tpa.seed.generate import build

EXTRACTED = Path(__file__).resolve().parent.parent / "data" / "edgar" / "extracted.json"


@pytest.mark.skipif(not EXTRACTED.exists(), reason="run scripts/pull_10k.py to re-read the filings")
def test_cited_figures_match_the_filings():
    filings = {f["accession"]: f for f in json.loads(EXTRACTED.read_text())["filings"]}
    for f in (cal.FY2026, cal.FY2025):
        got = filings[f.accession]
        assert Decimal(got["net_sales_usd"]) / 1_000_000 == f.net_sales_musd
        assert Decimal(str(got["na_retail_net_sales_musd"]["value"])) == f.na_retail_net_sales_musd
        assert got["walmart_share_of_net_sales_pct"]["value"] == f.walmart_share_of_net_sales_pct
        assert got["walmart_share_of_na_retail_pct"]["value"] == f.walmart_share_of_na_retail_pct
        assert got["accrued_trade_and_coupon_liabilities_musd"]["value"] == f.accrued_trade_and_coupon_musd
        assert got["filed"] == f.filed
    latest = filings[cal.FY2026.accession]
    assert latest["walmart_share_of_net_sales_pct"]["quote"] == cal.QUOTES["walmart"]
    assert latest["accrued_trade_and_coupon_liabilities_musd"]["quote"] == cal.QUOTES["accrued_trade"]
    assert latest["trade_promotion_policy"]["quote"] == cal.QUOTES["policy"]


def test_the_simulation_is_a_slice_of_the_real_business():
    ds = build(1337, 24)
    walmart = sum((Decimal(s["cases"]) * s["gross_price"] for s in ds.tables["shipments"]
                   if s["customer_id"] == "WMT" and s["ship_date"].year == 2026), Decimal("0"))
    s = cal.scale(walmart, Decimal(ds.answer_key["moment"]["total_catch_up"]), Decimal("0"))
    # One brand family is a part of General Mills' Walmart business, never more than all of it.
    assert 0 < s["sim_share_of_walmart_na_retail"] < 1
    # The moment is material to the program, and immaterial to the company: say both.
    assert s["catch_up_share_of_net_sales"] < Decimal("0.001")
