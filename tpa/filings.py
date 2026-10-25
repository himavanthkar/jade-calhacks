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


# The balance-sheet line, sixteen year ends: Notes to the financial statements, other current liabilities,
# "Accrued trade and consumer promotions" (XBRL AccruedMarketingCostsCurrent). Broader than the critical
# estimate above (it includes consumer promotions); each value as first filed, in that year's own 10-K
# (FY2011's in the FY2012 10-K's prior-year column). None was ever restated by a later filing.
@dataclass(frozen=True)
class BalanceSheet:
    fiscal_year: int
    accrued_trade_and_consumer_musd: D
    net_sales_musd: D
    accession: str


BALANCE_SHEET = (
    BalanceSheet(2011, D("463.0"), D("14880.2"), "0001193125-12-293636"),
    BalanceSheet(2012, D("560.7"), D("16657.9"), "0001193125-12-293636"),
    BalanceSheet(2013, D("635.3"), D("17774.1"), "0001193125-13-282371"),
    BalanceSheet(2014, D("578.2"), D("17909.6"), "0001193125-14-260716"),
    BalanceSheet(2015, D("564.7"), D("17630.3"), "0001193125-15-245476"),
    BalanceSheet(2016, D("563.7"), D("16563.1"), "0001193125-16-638404"),
    BalanceSheet(2017, D("482.6"), D("15619.8"), "0001193125-17-217396"),
    BalanceSheet(2018, D("499.6"), D("15740.4"), "0001193125-18-209377"),
    BalanceSheet(2019, D("484.4"), D("16865.2"), "0001193125-19-184675"),
    BalanceSheet(2020, D("550.4"), D("17626.6"), "0001193125-20-186469"),
    BalanceSheet(2021, D("580.9"), D("18127.0"), "0001193125-21-204830"),
    BalanceSheet(2022, D("474.4"), D("18992.8"), "0001193125-22-185257"),
    BalanceSheet(2023, D("454.3"), D("20094.2"), "0001193125-23-177500"),
    BalanceSheet(2024, D("502.3"), D("19857.2"), "0001193125-24-168943"),
    BalanceSheet(2025, D("527.2"), D("19486.6"), "0001193125-25-147079"),
    BalanceSheet(2026, D("547.0"), D("18424.6"), "0001628280-26-046466"),
)


# When the estimate trues up, it moves the reported quarter. Every earnings release (8-K, EX-99) since
# 2024 that names "trade expense timing" with a size, quoted. Points of year-on-year growth.
@dataclass(frozen=True)
class Timing:
    quarter: str
    released: str
    accession: str
    net_sales_pts: int
    operating_profit_pts: int | None
    quote: str


TRADE_TIMING = (
    Timing("Q4 FY2024", "2024-06-26", "0001193125-24-168511", -3, None,
           "Results included a 3-point headwind from a comparison against favorable trade expense timing in the "
           "prior year, which impacted net price realization and mix."),
    Timing("Q4 FY2025", "2025-06-25", "0001193125-25-146132", -2, -13,
           "Organic net sales were also down 3 percent, including a 2-point headwind from unfavorable trade "
           "expense timing."),
    Timing("Q4 FY2026", "2026-07-01", "0001628280-26-046337", 1, 7,
           "Adjusted operating profit of $705 million was up 13 percent in constant currency, driven by higher "
           "adjusted gross profit dollars including a 7-point benefit from favorable trade expense timing."),
)
