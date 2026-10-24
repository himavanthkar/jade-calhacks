"""The demo, on A's side: accrue Feb–Jul at the signed rate, close them, then restate when AM-02 lands.
B's accrual logic is stubbed with the simplest correct version so the ledger path is exercised end to end."""

from datetime import datetime, timedelta
from decimal import Decimal

from tpa.asof import balances_as_of, entry_history
from tpa.constants import Account, period_end
from tpa.ledger import Line, post_catch_up, post_journal
from tpa.seed.generate import build
from tpa.seed.load import load

LIAB = Account.ACCRUED_TRADE_PROMO


def test_amendment_restates_six_closed_periods(conn):
    ds = build(1337, 24)
    load(conn, ds, load_terms=True)
    moment = ds.answer_key["moment"]
    returned = {}
    for r in ds.tables["returns"]:
        returned[r["shipment_id"]] = returned.get(r["shipment_id"], 0) + r["cases"]

    accruals = {}
    with conn.cursor() as cur:
        for p in moment["periods"]:
            period = p["period"]
            net = sum(s["cases"] - returned.get(s["id"], 0) for s in ds.tables["shipments"]
                      if s["program_id"] == "TP-0214" and s["period"] == period)
            amount = (Decimal(net) * Decimal("0.92") * Decimal("3.80")).quantize(Decimal("0.01"))
            close = datetime.combine(period_end(period), datetime.min.time()) + timedelta(hours=18)
            accruals[period] = post_journal(
                cur, entry_type="accrual", period=period, customer_id="WMT", program_id="TP-0214",
                decision_time=close, approved_by="controller",
                lines=[Line(Account.TRADE_PROMO_EXPENSE, debit=amount), Line(LIAB, credit=amount)])
            cur.execute("UPDATE periods SET state = 'CLOSED', signed_by = 'controller', signed_at = %s "
                        "WHERE period = %s AND customer_id = 'WMT'", (close + timedelta(days=3), period))
        conn.commit()

        entered = datetime(2026, 8, 19, 10)
        catch_ups = [post_catch_up(cur, expense_line=f"{accruals[p['period']]}-1",
                                   liability_line=f"{accruals[p['period']]}-2", delta=Decimal(p["catch_up"]),
                                   decision_time=entered, approved_by="controller")
                     for p in moment["periods"]]
        conn.commit()

        total = Decimal("0")
        for p in moment["periods"]:
            before = balances_as_of(cur, p["period"], datetime(2026, 8, 1), customer_id="WMT")[LIAB]
            after = balances_as_of(cur, p["period"], entered, customer_id="WMT")[LIAB]
            assert before - after == Decimal(p["catch_up"])
            total += before - after
        assert total == Decimal(moment["total_catch_up"])
        assert total > Decimal("1390000")

        cur.execute("SELECT DISTINCT state FROM periods WHERE customer_id = 'WMT' AND period BETWEEN '2026-02' AND '2026-07'")
        assert cur.fetchall() == [("RESTATED",)]
        feb = entry_history(cur, f"{accruals['2026-02']}-2")
        assert [r["journal_id"] for r in feb["restated_by"]] == [catch_ups[0]]
