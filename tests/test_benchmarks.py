"""Benchmarks (tpa.benchmarks) are cited, and the comparison says which side of a range a figure is on."""

from decimal import Decimal

from tpa.benchmarks import BENCHMARKS, compare


def test_every_benchmark_is_cited_and_a_range():
    for b in BENCHMARKS:
        assert b.url.startswith("https://") and b.quote and b.source, b.metric
        assert b.low <= b.high and b.confidence in ("high", "medium", "low")


def test_vendor_figures_are_marked_and_never_trusted_highly():
    for b in BENCHMARKS:
        if not b.independent:
            assert b.confidence == "low", b.metric


def test_compare_places_a_figure_against_its_range():
    stats = {"trade_pct_gross": Decimal("0.073"), "auto_resolution": Decimal("0.71"), "true_up_pct_trade": None}
    where = {(r["metric"], r["where"]) for r in compare(stats)}
    assert ("trade_pct_gross", "below") in where
    assert ("auto_resolution", "inside") in where
    assert ("true_up_pct_trade", None) in where
