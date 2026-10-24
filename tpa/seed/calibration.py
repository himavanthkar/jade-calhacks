"""What is real: figures from General Mills' 10-Ks on SEC EDGAR, each with the sentence it comes from.

Transaction-level trade data is never public, on either side of the trade. The filings give the
shape of the business and the accounting policy; the simulation is checked against them here.
`scripts/pull_10k.py` re-reads the filings and `tests/test_calibration.py` checks these still match.

The simulation models one brand family at three customers, so it is a slice of the company, not
the whole: `scale()` reports how big a slice. These comparisons describe the fiction; they never
tune it (fiction.py is frozen).
"""

from dataclasses import dataclass
from decimal import Decimal as D

CIK = "0000040704"


@dataclass(frozen=True)
class Filing:
    fiscal_year: int
    period_end: str
    accession: str
    url: str
    net_sales_musd: D                      # XBRL us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax
    na_retail_net_sales_musd: D            # segment table, Item 7
    walmart_share_of_net_sales_pct: int    # Item 1, Customers
    walmart_share_of_na_retail_pct: int
    accrued_trade_and_coupon_musd: int     # Critical accounting estimates, revenue recognition


FY2026 = Filing(2026, "2026-05-31", "0001628280-26-046466",
                "https://www.sec.gov/Archives/edgar/data/40704/000162828026046466/gis-20260531.htm",
                D("18424.6"), D("10571.8"), 22, 31, 493)
FY2025 = Filing(2025, "2025-05-25", "0001193125-25-147079",
                "https://www.sec.gov/Archives/edgar/data/40704/000119312525147079/d938443d10k.htm",
                D("19486.6"), D("11907.0"), 22, 31, 470)

QUOTES = {
    "walmart": "During fiscal 2026 , Walmart Inc. and its affiliates (Walmart) accounted for 22 percent of our "
               "consolidated net sales and 31 percent of net sales of our North America Retail segment.",
    "accrued_trade": "Our accrued trade and coupon promotion liabilities were $493 million as of May 31, 2026 , and "
                     "$470 million as of May 25, 2025 .",
    # The policy the ledger follows: accrue at the time of sale on estimated participation; true up later.
    "policy": "Trade promotions are recorded using significant judgment of estimated participation and performance "
              "levels for offered programs at the time of sale. Differences between the estimated and actual reduction "
              "to the transaction price are recognized as a change in estimate in a subsequent period.",
}


def scale(sim_walmart_gross_usd: D, catch_up_usd: D, sim_trade_liability_usd: D, f: Filing = FY2026) -> dict:
    """How the simulated slice compares with the real company, as plain ratios."""
    walmart_na_retail = f.na_retail_net_sales_musd * D(f.walmart_share_of_na_retail_pct) / 100 * 1_000_000
    return {
        "walmart_na_retail_sales_usd": walmart_na_retail,
        "sim_share_of_walmart_na_retail": sim_walmart_gross_usd / walmart_na_retail,
        "catch_up_share_of_net_sales": catch_up_usd / (f.net_sales_musd * 1_000_000),
        "sim_share_of_accrued_trade": sim_trade_liability_usd / (D(f.accrued_trade_and_coupon_musd) * 1_000_000),
    }
