"""The close report (tpa.report) prints the package; it computes nothing new."""

from datetime import datetime
from decimal import Decimal

from tpa import report


def customer(cid, signed=None):
    return {"customer_id": cid, "signed_by": signed, "signed_at": datetime(2026, 11, 1) if signed else None,
            "totals": {"debit": Decimal("10.00"), "credit": Decimal("10.00")},
            "gates": {"journals_balance": {"passed": True}, "no_stale_accruals": {"passed": signed is not None}},
            "findings": [{"id": "FN-1", "control_id": "CTL-RATE-CONFLICT", "state": "resolved", "amount": Decimal("60003.00"),
                          "escalation_id": "ESC-1", "answer": "customer", "answered_by": "controller",
                          "became_precedent_id": "PR-1", "evidence": {"resolution": {"decision": "clear"}}}] if cid == "WMT" else [],
            "reconciliation": [{"program_id": "TP-0214", "opening": 0, "accruals": Decimal("100"), "estimate_adjustments": 0,
                                "settled": Decimal("40"), "ending": Decimal("60")}] if cid == "WMT" else []}


def test_the_report_prints_the_package():
    pkg = {"period": "2026-10", "as_of": datetime.max, "analytical_review": None,
           "flux": [{"account": "2300 Accrued trade promotion liability", "prior_balance": Decimal("100"),
                     "current_balance": Decimal("101.20"), "pct_change": Decimal("1.2"), "narrative": "Moved.",
                     "driver_entry_ids": ["JE-1-1"]}],
           "customers": [customer("COST", "close_reviewer"), customer("KR"), customer("WMT", "close_reviewer")]}
    html = report.html(pkg)
    assert "Trade promotion close · 2026-10" in html and "Signed for 2 of 3 customers" in html
    assert "(+1.2%)" in html and "JE-1-1" in html                    # the stored change is already a percentage
    assert "$60,003.00" in html and "PR-1" in html and ">clear<" in html
    assert "Books as they stand" in html and "9999" not in html
    assert "1 of 2 passed" in html                                    # Kroger's failing check is shown, not hidden
