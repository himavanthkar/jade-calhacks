"""Working with people: busy approvers get followed up, half-done handoffs get re-checked.
January runs with every card left waiting (inbox), handoffs land in February, February runs."""

import os

import pytest
from fastapi.testclient import TestClient

from tpa.api import app
from tpa.db import connect, reset_schema
from tpa.rows import all_rows, one_row
from tpa.seed.generate import build
from tpa.seed.load import load


@pytest.fixture(scope="module")
def february():
    os.environ["TPA_HUMANS"] = "inbox"
    conn = connect()
    reset_schema(conn)
    load(conn, build(1337, 24), load_terms=True)
    conn.commit()
    c = TestClient(app)
    c.post("/api/period/2026-01/step").raise_for_status()
    held = next(e for e in c.get("/api/escalations").json() if e["control_id"] == "CTL-SCAN-NO-BACKUP")
    no_backup, its_program = held["evidence"]["deduction_ids"][0], held["evidence"]["program_id"]
    example = next(e for e in c.get("/api/scenario/examples").json() if e["kind"] == "handoff")
    ids = {}
    for name, payload in (("instalment", example["payload"]),
                          ("wrong_program", {"from_actor": "tpa.human", "deduction_id": no_backup,
                                             "proposed_program_id": "TP-0214", "day": 5}),
                          ("no_backup", {"from_actor": "tpa.human", "deduction_id": no_backup,
                                         "proposed_program_id": its_program, "left_to_do": "Clear it.", "day": 5})):
        ids[name] = c.post("/api/scenario", json={"kind": "handoff", "payload": payload}).json()["created_ids"][0]
    step = c.post("/api/period/2026-02/step").json()
    conn.autocommit = True
    yield {"conn": conn, "ids": ids, "step": step, "example": example}
    conn.close()
    os.environ.pop("TPA_HUMANS", None)


def handoff(f, name):
    with f["conn"].cursor() as cur:
        return one_row(cur, "SELECT * FROM handoffs WHERE id = %s", (f["ids"][name],))


def test_a_checked_handoff_is_finished(february):
    h = handoff(february, "instalment")
    assert h["status"] == "completed"
    with february["conn"].cursor() as cur:
        cur.execute("""SELECT COALESCE(SUM(debit - credit), 0), COUNT(*) FILTER (WHERE entry_type = 'clearing'
                         AND program_id = %s) FROM ledger_entries WHERE deduction_id = %s AND account LIKE '1250%%'""",
                    (february["example"]["payload"]["proposed_program_id"], h["deduction_id"]))
        pending, clearings = cur.fetchone()
    assert pending == 0 and clearings == 1


def test_a_handoff_to_the_wrong_program_goes_back(february):
    h = handoff(february, "wrong_program")
    assert h["status"] == "returned" and "can't verify" in h["outcome"]["reason"]


def test_a_handoff_that_fails_a_control_goes_back_with_the_reason(february):
    h = handoff(february, "no_backup")
    assert h["status"] == "returned" and "CTL-SCAN-NO-BACKUP" in h["outcome"]["reason"]
    with february["conn"].cursor() as cur:
        f = one_row(cur, "SELECT * FROM findings WHERE id = %s", (h["outcome"]["finding_id"],))
    assert f["evidence"]["handoff"]["id"] == h["id"] and f["state"] in ("open", "escalated")


def test_unanswered_cards_go_up_to_the_controller(february):
    with february["conn"].cursor() as cur:
        moved = all_rows(cur, "SELECT * FROM escalations WHERE answer = 'routed:controller' ORDER BY id")
        up = all_rows(cur, "SELECT * FROM escalations WHERE question LIKE 'No answer from the %%' ORDER BY id")
    assert moved and all(m["to_role"] != "controller" for m in moved)
    assert len(up) == len(moved) and all(u["to_role"] == "controller" and "close is waiting on it" in u["question"]
                                         for u in up)
    assert any("moved to the controller" in line for line in february["step"]["log"])
