"""Seven years of General Mills' public figures, as first filed: the backtest's real data.

Every figure is from a 10-K on SEC EDGAR (CIK 0000040704) and carries the day it became public,
the earliest a backtest may use it. `scripts/pull_10k.py` re-reads the filings into
data/edgar/extracted.json and `tests/test_backtest.py` checks these still match.

    accrued_trade_musd        Critical accounting estimates: "Our accrued trade and coupon promotion
                              liabilities were $X million as of <this year end>, and $Y million as of
                              <prior year end>." X is this year; Y is the prior year as restated here.
    net_sales_musd            XBRL us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax, fiscal year
    q4_net_sales_musd         the same tag, the fiscal fourth quarter (13 or 14 weeks)
    walmart_share_pct         Item 1, Customers: Walmart's share of consolidated net sales

Company-level figures only. Deduction-level data is never public; precision and recall on
deductions stay scored against the simulation's answer key (`tpa/evaluate.py`).
"""

from dataclasses import dataclass
from decimal import Decimal as D

CIK = "0000040704"


@dataclass(frozen=True)
class Year:
    fiscal_year: int
    period_end: str
    filed: str                     # the 10-K's filing date: public from this day
    accession: str
    net_sales_musd: D
    q4_net_sales_musd: D
    accrued_trade_musd: int
    accrued_trade_prior_musd: int  # the prior year end, as this filing states it
    walmart_share_pct: int

    @property
    def url(self) -> str:
        return f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{self.accession.replace('-', '')}/"


YEARS = (
    Year(2020, "2020-05-31", "2020-07-02", "0001193125-20-186469", D("17626.6"), D("5023.0"), 471, 410, 21),
    Year(2021, "2021-05-30", "2021-06-30", "0001193125-21-204830", D("18127.0"), D("4523.6"), 508, 471, 20),
    Year(2022, "2022-05-29", "2022-06-30", "0001193125-22-185257", D("18992.8"), D("4891.2"), 420, 508, 20),
    Year(2023, "2023-05-28", "2023-06-28", "0001193125-23-177500", D("20094.2"), D("5030.0"), 394, 420, 21),
    Year(2024, "2024-05-26", "2024-06-26", "0001193125-24-168943", D("19857.2"), D("4713.9"), 425, 394, 22),
    Year(2025, "2025-05-25", "2025-06-26", "0001193125-25-147079", D("19486.6"), D("4556.2"), 470, 425, 22),
    Year(2026, "2026-05-31", "2026-07-01", "0001628280-26-046466", D("18424.6"), D("4609.6"), 493, 470, 22),
)
