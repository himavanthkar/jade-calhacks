"""The controller says no: the agent recommends last year's handling, she overrules it with a reason,
and the next matching cases follow her without asking. Played through June."""

import pytest

from test_engine import run_all
from tpa import explain, players
from tpa.rows import all_rows, one_row
from tpa.seed.generate import build


@pytest.fixture(scope="module")
def half_year():
    conn = run_all(build(1337, 24), players.hooks(players.CONTROLLER_SAYS_NO), through="2026-06")
    yield conn
    conn.close()


def straddles(cur, customer_id):
    return all_rows(cur, """SELECT f.*, e.id AS escalation_id, e.recommended, e.answer, e.question FROM findings f
                            LEFT JOIN escalations e ON e.finding_id = f.id
                            WHERE f.control_id = 'CTL-PERIOD-STRADDLE' AND f.customer_id = %s ORDER BY f.id""",
                    (customer_id,))


def test_she_overrules_the_recommendation_once(half_year):
    with half_year.cursor() as cur:
        first, *later = straddles(cur, "WMT")
        p = one_row(cur, "SELECT * FROM precedents WHERE from_escalation_id = %s", (first["escalation_id"],))
    assert first["recommended"] == "allocate" and first["answer"] == "dispute"
    assert "I'd recommend: allocate across periods by activity days" in first["question"]
    assert (p["decision"], p["overrode"], p["decided_by"]) == ("dispute", "allocate", "controller")
    assert "quarter end" in p["reasoning"]
    assert later and all(f["escalation_id"] is None and f["state"] == "auto_resolved"
                         and f["evidence"]["precedent_id"] == p["id"] for f in later)


def test_her_no_does_not_reach_another_customer(half_year):
    with half_year.cursor() as cur:
        (kroger,) = straddles(cur, "KR")
    assert kroger["escalation_id"] and kroger["recommended"] == "allocate" and kroger["answer"] == "allocate"


def test_the_interrogation_box_answers_what_if_she_said_no(half_year):
    with half_year.cursor() as cur:
        a = explain.ask(cur, "What if the controller had said no?")
    (o,) = a["knowledge"]["overrulings"]
    assert (o["recommended"], o["decided"], o["later_cases_following_it"]) == ("allocate", "dispute", 3)
    assert "overruled the agent" in a["answer"]
