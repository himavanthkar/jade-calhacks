"""The close's analytical review: is the total trade promotion liability in a believable range?

Deal-level controls ask whether each claim is right. This asks the auditor's question one level up:
accrued trade promotion liability as a share of annualized net sales, against General Mills' own
reported ratio from the latest 10-K public at the close (FY2025's 2.41% until 2026-07-01, then
FY2026's 2.68%). The simulation is a slice of the company, so the comparison is a range, not a match.

Judgment, not a gate: inside the range it is commentary; outside it, the reviewer explains the
difference before signing. Every number is a ledger sum or a cited filing figure; it moves nothing.
"""

import json
from datetime import datetime, time
from decimal import Decimal

import psycopg

from tpa.asof import liability_outstanding
from tpa.constants import Account, add_months, live_month, period_end, period_for_month
from tpa.execute import _jsonable
from tpa.policy import ANALYTICAL_REVIEW_TOLERANCE
from tpa.rows import one_row
from tpa.seed.calibration import QUOTES, latest_filing, trade_liability_ratio

MEASURE = "Accrued trade promotion liability / annualized net sales"
ZERO = Decimal("0")


def pct(x: Decimal) -> str:
    return f"{x * 100:.2f}%"


def musd(x: Decimal) -> str:
    return f"${x / 1_000_000:,.2f}M"


def measure(cur: psycopg.Cursor, period: str, at: datetime) -> dict:
    """The liability outstanding at `at`, and net sales (gross less trade promotion, as General
    Mills reports them) over the live year to `period`, annualized."""
    liability = sum(liability_outstanding(cur, at).values(), ZERO)
    first = period_for_month(13)
    cur.execute("""SELECT COALESCE(SUM(credit - debit) FILTER (WHERE account = %s), 0),
                          COALESCE(SUM(debit - credit) FILTER (WHERE account = %s), 0)
                   FROM ledger_entries WHERE period BETWEEN %s AND %s AND decision_time <= %s""",
                (Account.GROSS_SALES, Account.TRADE_PROMO_EXPENSE, first, period, at))
    gross, trade = cur.fetchone()
    months = live_month(period)
    net_annual = ((gross - trade) * 12 / months).quantize(Decimal("0.01")) if months > 0 else ZERO
    return {"liability": liability, "net_sales_annualized": net_annual,
            "ratio": (liability / net_annual) if net_annual else ZERO}


def drivers(cur: psycopg.Cursor, period: str, at: datetime) -> list[dict]:
    """What moved the liability this month beyond ordinary accruals and claims: restatements."""
    start = datetime.combine(period_end(add_months(period, -1)), time.max)
    cur.execute("""SELECT journal_id, program_id, SUM(credit - debit) FROM ledger_entries
                   WHERE account = %s AND entry_type = 'restatement' AND decision_time > %s AND decision_time <= %s
                   GROUP BY 1, 2 ORDER BY 1""", (Account.ACCRUED_TRADE_PROMO, start, at))
    return [{"kind": "restatement", "journal_id": j, "program_id": p, "amount": a} for j, p, a in cur.fetchall()]


def review(cur: psycopg.Cursor, period: str, at: datetime) -> dict:
    m = measure(cur, period, at)
    filing = latest_filing(at.date().isoformat())
    moved = drivers(cur, period, at)
    prior = one_row(cur, "SELECT ratio FROM analytical_reviews WHERE period = %s", (add_months(period, -1),))
    out = {"id": f"AR-{period}", "period": period, "measure": MEASURE, **m, "drivers": moved, "decision_time": at,
           "expectation": None, "low": None, "high": None, "within_range": None, "source": {}}
    lead = (f"Accrued trade promotion liability is {musd(m['liability'])}, {pct(m['ratio'])} of annualized net sales "
            f"({musd(m['net_sales_annualized'])}).")
    if filing is None:
        out["narrative"] = lead + " No General Mills 10-K was public yet to compare with."
        return out
    expected = trade_liability_ratio(filing)
    low, high = expected * (1 - ANALYTICAL_REVIEW_TOLERANCE), expected * (1 + ANALYTICAL_REVIEW_TOLERANCE)
    within = low <= m["ratio"] <= high
    out.update(expectation=expected, low=low, high=high, within_range=within, source={
        "fiscal_year": filing.fiscal_year, "filed": filing.filed, "accession": filing.accession, "url": filing.url,
        "accrued_trade_and_coupon_musd": filing.accrued_trade_and_coupon_musd, "net_sales_musd": filing.net_sales_musd,
        "quote": QUOTES["accrued_trade"] if filing.fiscal_year == 2026 else None})
    text = [lead,
            f"General Mills reports {pct(expected)} (${filing.accrued_trade_and_coupon_musd}M on "
            f"${filing.net_sales_musd:,}M net sales, FY{filing.fiscal_year} 10-K filed {filing.filed}).",
            f"{'Within' if within else 'Outside'} the review range of {pct(low)} to {pct(high)}"
            + ("." if within else "; the close reviewer explains the difference before signing.")]
    if prior:
        text.append(f"{'Up' if m['ratio'] >= prior['ratio'] else 'Down'} {abs(m['ratio'] - prior['ratio']) * 100:.2f} "
                    f"points from last month.")
    if moved:
        total = sum((d["amount"] for d in moved), ZERO)
        text.append(f"Restatements this month added {musd(total)} ({', '.join(d['journal_id'] for d in moved)}).")
    out["narrative"] = " ".join(text)
    return out


def write_review(cur: psycopg.Cursor, period: str, at: datetime) -> dict:
    r = review(cur, period, at)
    cur.execute(
        """INSERT INTO analytical_reviews (id, period, measure, liability, net_sales_annualized, ratio, expectation,
                                           low, high, within_range, source, drivers, narrative, decision_time)
           VALUES (%(id)s, %(period)s, %(measure)s, %(liability)s, %(net_sales_annualized)s, %(ratio)s, %(expectation)s,
                   %(low)s, %(high)s, %(within_range)s, %(source)s, %(drivers)s, %(narrative)s, %(decision_time)s)""",
        {**r, "source": json.dumps(r["source"], default=_jsonable), "drivers": json.dumps(r["drivers"], default=_jsonable)})
    return r
