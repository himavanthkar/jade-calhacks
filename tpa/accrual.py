"""Accrual math. Pure functions over plain rows: no database, no model, no floats.

The estimate for (program, origin period) is the liability the books should carry for
that period's promoted activity, on the terms and the volume known at the time:

* scan_back    Σ over rate segments: net cases × projected redemption × rate in force
               on the ship date. Segments split where an amendment changes the rate.
* display      the per-event fee for each month inside the window (one event a month)
* mdf          the annual fund spread evenly over the months of the window
* off_invoice  nothing: the allowance is taken at invoice and expensed there
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from tpa.constants import month_for_period, period_end, period_of, period_start

CENT = Decimal("0.01")
ZERO = Decimal("0")


def money(x) -> Decimal:
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def rate(x) -> Decimal:
    """A rate for prose: 3.800000 → 3.80, 0.920000 → 0.92, 0.0035 stays 0.0035."""
    d = Decimal(x).normalize()
    return d.quantize(CENT) if d.as_tuple().exponent >= -2 else d


@dataclass(frozen=True)
class Segment:
    """One rate's share of an origin period's scan-back estimate."""
    term_id: str
    rate: Decimal
    cases: int
    amount: Decimal


def net_cases(shipment: dict, returned: dict[str, int]) -> int:
    return shipment["cases"] - returned.get(shipment["id"], 0)


def scan_back_segments(shipments: Iterable[dict], returned: dict[str, int], projected: Decimal,
                       term_for: Callable[[date], dict]) -> list[Segment]:
    """Group a period's promoted shipments by the term in force on each ship date."""
    cases: dict[tuple[str, Decimal], int] = defaultdict(int)
    for s in shipments:
        t = term_for(s["ship_date"])
        cases[(t["id"], t["rate"])] += net_cases(s, returned)
    return [Segment(tid, rate, n, money(Decimal(n) * projected * rate))
            for (tid, rate), n in sorted(cases.items(), key=lambda kv: kv[0][0])]


def months_in_window(start: date, end: date) -> int:
    return month_for_period(period_of(end)) - month_for_period(period_of(start)) + 1


def fixed_fund_amount(term: dict, period: str) -> Decimal:
    """Monthly liability for a display or MDF program, zero outside its window."""
    if period_end(period) < term["window_start"] or period_start(period) > term["window_end"]:
        return ZERO
    if term["program_type"] == "display":
        return money(term["rate"])
    if term["program_type"] == "mdf":
        return money(term["rate"] / months_in_window(term["window_start"], term["window_end"]))
    raise ValueError(f"{term['program_type']} is not a fixed fund")


def restatement_delta(shipments: Iterable[dict], returned: dict[str, int], projected: Decimal,
                      old_term_for: Callable[[date], dict], new_term_for: Callable[[date], dict]) -> Decimal:
    """What a change of terms alone does to an origin period's scan-back estimate.

    Grouped by (old rate, new rate) so each group rounds once:
    round(net cases × projected × (new − old), 2) — the answer key's formula exactly.
    """
    cases: dict[tuple[Decimal, Decimal], int] = defaultdict(int)
    for s in shipments:
        cases[(old_term_for(s["ship_date"])["rate"], new_term_for(s["ship_date"])["rate"])] += net_cases(s, returned)
    return sum((money(Decimal(n) * projected * (new - old)) for (old, new), n in cases.items() if new != old), ZERO)


def backup_variance(amount: Decimal, scan_units: int, scan_rate: Decimal) -> Decimal:
    """|claimed − backup-supported| ÷ backup-supported, as a fraction (0.005 = 0.5%)."""
    supported = Decimal(scan_units) * scan_rate
    if supported == 0:
        return Decimal("1")
    return abs(amount - supported) / supported


def quarter_of(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3


def straddles_quarter_end(start: date | None, end: date | None) -> bool:
    return bool(start and end) and quarter_of(start) != quarter_of(end)


def activity_share(claim_start: date | None, claim_end: date | None, start: date, end: date) -> Decimal:
    """The part of a claim whose activity days fall in [start, end]: how a straddle is allocated.
    A claim without dates sits wholly in its claimed period."""
    if not (claim_start and claim_end):
        return Decimal("1")
    days = (claim_end - claim_start).days + 1
    inside = (min(end, claim_end) - max(start, claim_start)).days + 1
    return Decimal(max(inside, 0)) / Decimal(days)


def split_by_activity(amount: Decimal, claim_start: date, claim_end: date,
                      origins: list[tuple[date, date]]) -> list[Decimal]:
    """`amount` over consecutive origin months by activity days, to the cent. The last share takes
    the remainder, so the shares always sum to the amount."""
    shares, left = [], amount
    for i, (start, end) in enumerate(origins):
        share = left if i == len(origins) - 1 else money(amount * activity_share(claim_start, claim_end, start, end))
        left -= share
        shares.append(share)
    return shares


NICE_STEPS = (Decimal("1"), Decimal("2.5"), Decimal("5"))


def nice_ceiling(x: Decimal) -> Decimal:
    """The smallest 1 / 2.5 / 5 × 10ⁿ at or above x: how a person writes a threshold down."""
    if x <= 0:
        return ZERO
    exp = x.adjusted()
    for e in (exp - 1, exp, exp + 1):
        for step in NICE_STEPS:
            candidate = step.scaleb(e)
            if candidate >= x:
                return Decimal(int(candidate)) if candidate == candidate.to_integral() else candidate
    raise AssertionError("unreachable")
