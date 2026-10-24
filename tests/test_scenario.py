"""Live scenarios through the API: a judge's session, played once for the module.

Jan–Mar run as seeded; every example is injected into April; April runs; the backup for the
no-backup claim arrives in May; May runs. The tests read what the engine did.
"""

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tpa.api import app
from tpa.db import connect, reset_schema
from tpa.evaluate import metrics
from tpa.seed.generate import build
from tpa.seed.load import load


@pytest.fixture(scope="module")
def session():
    import os
    os.environ["TPA_HUMANS"] = "players"
    ds = build(1337, 24)
    conn = connect()
    reset_schema(conn)
    load(conn, ds, load_terms=False)
    conn.commit()
    c = TestClient(app)
    for m in ("01", "02", "03"):
        c.post(f"/api/period/2026-{m}/step").raise_for_status()
    made = {}
    for e in c.get("/api/scenario/examples").json():
        r = c.post("/api/scenario", json={"kind": e["kind"], "payload": e["payload"], "injected_by": "judge"})
        assert r.status_code == 200, r.json()
        made[e["kind"] + (":rate" if e["payload"].get("claimed_rate") else "")] = r.json()["created_ids"]
    c.post("/api/period/2026-04/step").raise_for_status()
    no_backup = made["deduction"][0]
    later = c.post("/api/scenario", json={"kind": "backup", "step": True,
                                          "payload": {"deduction_id": no_backup, "scan_units": 13700, "scan_rate": "3.50",
                                                      "day": 3}}).json()
    conn.autocommit = True
    yield {"client": c, "conn": conn, "made": made, "later": later, "ds": ds}
    conn.close()
    os.environ.pop("TPA_HUMANS", None)


def findings_citing(session, ids, period="2026-04"):
    rows = session["client"].get(f"/api/period/{period}").json()["findings"]
    return [f for f in rows if set(json.dumps(f["evidence"]).replace('"', " ").split()) & set(ids)]


def test_bad_scenarios_are_refused_with_a_reason(session):
    c = session["client"]
    for body, reason in (({"kind": "nope", "payload": {}}, "kind must be one of"),
                         ({"kind": "deduction", "payload": {"customer_id": "WMT"}}, "missing amount"),
                         ({"kind": "deduction", "payload": {"customer_id": "WMT", "amount": "-5"}}, "must be positive"),
                         ({"kind": "deduction", "payload": {"customer_id": "KR", "amount": "5", "program_id": "TP-0214"}},
                          "is WMT's program"),
                         ({"kind": "return", "payload": {"shipment_id": "SH-00001", "cases": 10 ** 7}}, "could still come back"),
                         ({"kind": "amendment", "payload": {"program_id": "TP-0231", "new_rate": "1", "effective_date":
                                                            "2026-01-01"}}, "only scan-back"),
                         ({"kind": "deduction", "payload": {"customer_id": "WMT", "amount": "5", "day": 40}}, "day must be")):
        r = c.post("/api/scenario", json=body)
        assert r.status_code == 422 and reason in r.json()["detail"], (body, r.json())


def test_each_injection_meets_the_control_built_for_it(session):
    m = session["made"]
    expect = {"deduction": "CTL-SCAN-NO-BACKUP", "deduction:rate": "CTL-RATE-CONFLICT", "duplicate": "CTL-DUPLICATE-DEDUCTION",
              "approval_attempt": "CTL-SOD", "return": "CTL-RETURNS-NOT-NETTED", "amendment": "CTL-DED-GT-ACCRUAL"}
    for kind, control in expect.items():
        assert control in {f["control_id"] for f in findings_citing(session, m[kind])}, kind


def test_the_self_approval_throws(session):
    (f,) = [f for f in findings_citing(session, session["made"]["approval_attempt"]) if f["control_id"] == "CTL-SOD"]
    assert f["escalation_type"] == "sod" and "approval routed to controller" in f["evidence"]["summary"]


def test_a_retroactive_rate_cut_claws_back_closed_months(session):
    (f,) = [f for f in findings_citing(session, session["made"]["amendment"]) if f["conflict_type"] == "amendment_not_applied"]
    assert Decimal(f["amount"]) < 0 and f["state"] == "resolved"
    with session["conn"].cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ledger_entries WHERE entry_type = 'restatement' AND source_finding_id = %s", (f["id"],))
        assert cur.fetchone()[0] > 0


def test_backup_arriving_late_reverses_our_own_dispute(session):
    ded = session["made"]["deduction"][0]
    assert any("our dispute withdrawn" in line for line in session["later"]["step"]["log"])
    with session["conn"].cursor() as cur:
        cur.execute("""SELECT COALESCE(SUM(debit - credit) FILTER (WHERE account LIKE '1250%%'), 0),
                              COALESCE(SUM(debit - credit) FILTER (WHERE account LIKE '1260%%'), 0),
                              COUNT(*) FILTER (WHERE entry_type = 'clearing')
                       FROM ledger_entries WHERE deduction_id = %s""", (ded,))
        pending, disputed, clearings = cur.fetchone()
    assert (pending, disputed) == (0, 0) and clearings > 0


def test_one_whole_stream_is_not_a_whole_month(session):
    """The injected claim covers March in one stream; Walmart sends two. No drift is judged on half."""
    assert not [f for f in findings_citing(session, session["made"]["deduction"]) if f["control_id"] == "CTL-REDEMPTION-DRIFT"]


def test_the_judges_scenario_is_scored_apart(session):
    with session["conn"].cursor() as cur:
        m = metrics(cur, session["ds"].answer_key, "month-5")
    assert m["counts"]["scenario_findings"] >= 6
    assert m["precision"] == 1.0 and m["missed"] == []
