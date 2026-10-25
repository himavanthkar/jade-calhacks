"""Backtest on real data: General Mills' accrued trade promotion liability, fiscal 2021-2026.

Walk forward one year-end close at a time. At each close the estimators see only what was public
before that year's 10-K was filed (every earlier 10-K), plus the year's own net sales, which the
company knows at its close. The estimate is then scored against the liability the 10-K reported.

    naive          last year's liability, carried forward
    annual_ratio   last year's liability / net sales, times this year's net sales: the measure the
                   close's analytical review uses (`tpa.review`)
    q4_ratio       the same ratio on fourth-quarter sales: trade claims settle within months, so the
                   year-end balance follows the last quarter's shipments
    mean_q4_ratio  q4_ratio with the ratio averaged over every year public so far

Two controls replayed on the real books, which were audited, so any flag is a false alarm:
    analytical review  the liability ratio against the prior 10-K's, at ANALYTICAL_REVIEW_TOLERANCE
    restatement        a year end reported once, then stated differently as the prior year a year later

Company level only: this scores the top-down estimate and the controls, never deduction matching.
"""

from collections.abc import Callable, Sequence
from decimal import ROUND_HALF_EVEN, Decimal

from tpa.filings import BALANCE_SHEET, YEARS, Year
from tpa.policy import ANALYTICAL_REVIEW_TOLERANCE

ZERO = Decimal("0")
Estimator = Callable[[Sequence[Year], Year], Decimal]


def ratio(y: Year) -> Decimal:
    return Decimal(y.accrued_trade_musd) / y.net_sales_musd


def q4_ratio(y: Year) -> Decimal:
    return Decimal(y.accrued_trade_musd) / y.q4_net_sales_musd


ESTIMATORS: dict[str, Estimator] = {
    "naive": lambda known, y: Decimal(known[-1].accrued_trade_musd),
    "annual_ratio": lambda known, y: ratio(known[-1]) * y.net_sales_musd,
    "q4_ratio": lambda known, y: q4_ratio(known[-1]) * y.q4_net_sales_musd,
    "mean_q4_ratio": lambda known, y: sum(map(q4_ratio, known), ZERO) / len(known) * y.q4_net_sales_musd,
}


def known_at(years: Sequence[Year], close: Year) -> list[Year]:
    """Every 10-K public before this close's own 10-K was filed."""
    return [y for y in years if y.filed < close.filed]


def r(x: Decimal, places: str = "0.1") -> Decimal:
    return x.quantize(Decimal(places), ROUND_HALF_EVEN)


def summary(errors: list[Decimal], actuals: list[Decimal]) -> dict:
    pcts = [e / a for e, a in zip(errors, actuals)]
    return {"mae_musd": r(sum(map(abs, errors), ZERO) / len(errors)),
            "mape": r(sum(map(abs, pcts), ZERO) / len(pcts), "0.0001"),
            "bias": r(sum(pcts, ZERO) / len(pcts), "0.0001"),
            "worst": r(max(pcts, key=abs), "0.0001")}


def run(years: Sequence[Year] = YEARS, tolerance: Decimal = ANALYTICAL_REVIEW_TOLERANCE) -> dict:
    closes, errors, actuals = [], {k: [] for k in ESTIMATORS}, []
    for y in years:
        known = known_at(years, y)
        if not known:
            continue
        actual = Decimal(y.accrued_trade_musd)
        estimates = {k: f(known, y) for k, f in ESTIMATORS.items()}
        drift = ratio(y) / ratio(known[-1]) - 1
        for k, e in estimates.items():
            errors[k].append(e - actual)
        actuals.append(actual)
        closes.append({"fiscal_year": y.fiscal_year, "period_end": y.period_end, "filed": y.filed,
                       "known_filings": [k.fiscal_year for k in known], "actual_musd": y.accrued_trade_musd,
                       "net_sales_musd": y.net_sales_musd, "estimates_musd": {k: r(e) for k, e in estimates.items()},
                       "ratio": r(ratio(y), "0.0001"), "review_drift": r(drift, "0.0001"),
                       "review_flagged": abs(drift) > tolerance, "source": y.url})
    restated = [{"fiscal_year": prev.fiscal_year, "first_filed_musd": prev.accrued_trade_musd,
                 "restated_musd": nxt.accrued_trade_prior_musd, "restated_in": nxt.fiscal_year}
                for prev, nxt in zip(years, years[1:]) if prev.accrued_trade_musd != nxt.accrued_trade_prior_musd]
    scores = {k: summary(errors[k], actuals) for k in ESTIMATORS}
    return {"closes": closes,
            "scores": scores,
            "best": min(scores, key=lambda k: scores[k]["mape"]),
            "analytical_review": {"tolerance": tolerance,
                                  "false_alarms": sum(c["review_flagged"] for c in closes),
                                  "largest_drift": max((c["review_drift"] for c in closes), key=abs)},
            "restatements": restated}


def history(series=BALANCE_SHEET) -> dict:
    """Sixteen year ends of the balance-sheet line: the ratio each year, the year-on-year drift the
    analytical review would have seen, and the tolerance that would have stayed quiet on audited books."""
    years = [{"fiscal_year": b.fiscal_year, "liability_musd": b.accrued_trade_and_consumer_musd,
              "net_sales_musd": b.net_sales_musd,
              "ratio": r(b.accrued_trade_and_consumer_musd / b.net_sales_musd, "0.0001"), "accession": b.accession}
             for b in series]
    exact = [b.accrued_trade_and_consumer_musd / b.net_sales_musd for b in series]
    for i, (prev, y) in enumerate(zip(years, years[1:]), start=1):
        y["drift"] = r(exact[i] / exact[i - 1] - 1, "0.0001")
        y["naive_error"] = r(prev["liability_musd"] / y["liability_musd"] - 1, "0.0001")
    drifts = [abs(y["drift"]) for y in years[1:]]
    return {"years": years, "largest_drift": max(drifts), "quiet_tolerance": max(drifts),
            "mean_abs_drift": r(sum(drifts, ZERO) / len(drifts), "0.0001")}
