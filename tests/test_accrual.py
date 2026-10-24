"""The accrual math is pure: tested without a database."""

from datetime import date
from decimal import Decimal

from tpa.accrual import (
    backup_variance, fixed_fund_amount, money, nice_ceiling, rate, restatement_delta, scan_back_segments,
    straddles_quarter_end,
)

OLD = {"id": "PT-old", "rate": Decimal("3.80")}
NEW = {"id": "PT-new", "rate": Decimal("4.20")}


def shipments():
    return [{"id": "SH-1", "ship_date": date(2026, 2, 10), "cases": 1000},
            {"id": "SH-2", "ship_date": date(2026, 2, 16), "cases": 2000},
            {"id": "SH-3", "ship_date": date(2026, 2, 20), "cases": 500}]


def amended(on: date) -> dict:
    return NEW if on >= date(2026, 2, 14) else OLD


def test_segments_split_where_the_rate_changes():
    segs = scan_back_segments(shipments(), {"SH-2": 100}, Decimal("0.92"), amended)
    assert [(s.rate, s.cases) for s in segs] == [(Decimal("4.20"), 2400), (Decimal("3.80"), 1000)]
    assert segs[0].amount == money(2400 * Decimal("0.92") * Decimal("4.20"))


def test_restatement_delta_is_the_answer_key_formula():
    """round(net cases on or after the effective date × projected × (new − old), 2)"""
    delta = restatement_delta(shipments(), {"SH-2": 100}, Decimal("0.92"), lambda on: OLD, amended)
    assert delta == money(Decimal(2400) * Decimal("0.92") * Decimal("0.40")) == Decimal("883.20")


def test_no_change_no_delta():
    assert restatement_delta(shipments(), {}, Decimal("0.92"), lambda on: OLD, lambda on: OLD) == 0


def test_fixed_funds():
    display = {"program_type": "display", "rate": Decimal("165000"), "window_start": date(2026, 4, 1),
               "window_end": date(2026, 6, 30)}
    mdf = {"program_type": "mdf", "rate": Decimal("2400000"), "window_start": date(2026, 1, 1),
           "window_end": date(2026, 12, 31)}
    assert fixed_fund_amount(display, "2026-05") == Decimal("165000.00")
    assert fixed_fund_amount(display, "2026-07") == 0
    assert fixed_fund_amount(mdf, "2026-03") == Decimal("200000.00")


def test_backup_variance_and_straddles():
    assert backup_variance(Decimal("1005.00"), 1000, Decimal("1.00")) == Decimal("0.005")
    assert straddles_quarter_end(date(2026, 3, 28), date(2026, 4, 3))
    assert not straddles_quarter_end(date(2026, 4, 28), date(2026, 5, 3))


def test_thresholds_are_written_the_way_people_write_them():
    assert nice_ceiling(Decimal("0.434")) == Decimal("0.5")
    assert nice_ceiling(Decimal("7860")) == Decimal("10000")
    assert nice_ceiling(Decimal("2177.08")) == Decimal("2500")
    assert nice_ceiling(Decimal("1")) == Decimal("1")


def test_rates_read_cleanly():
    assert str(rate(Decimal("3.800000"))) == "3.80"
    assert str(rate(Decimal("0.920000"))) == "0.92"
    assert str(rate(Decimal("0.0035"))) == "0.0035"


def test_activity_split_to_the_cent():
    from tpa.accrual import split_by_activity
    shares = split_by_activity(Decimal("100.01"), date(2026, 3, 28), date(2026, 4, 6),
                               [(date(2026, 3, 1), date(2026, 3, 31)), (date(2026, 4, 1), date(2026, 4, 30))])
    assert shares == [Decimal("40.00"), Decimal("60.01")]          # 4 days / 6 days; the remainder lands last
