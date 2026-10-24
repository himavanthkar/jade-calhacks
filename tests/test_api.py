"""The HTTP surface on a real seed: January stepped with the cards left for people."""

import pytest
from fastapi.testclient import TestClient

from tpa.api import app
from tpa.seed.generate import build
from tpa.seed.load import load, write_files


@pytest.fixture
def api(conn, tmp_path, monkeypatch):
    ds = build(1337, 24)
    load(conn, ds, load_terms=True)
    conn.commit()
    write_files(ds, tmp_path)
    monkeypatch.setattr("tpa.api.ANSWER_KEY", tmp_path / "answer_key.json")
    monkeypatch.setenv("TPA_HUMANS", "inbox")
    c = TestClient(app)
    assert c.post("/api/period/2026-01/step").status_code == 200
    return c


def test_the_clock_only_steps_forward_in_order(api):
    assert api.get("/api/clock").json()["current_period"] == "2026-02"
    assert api.post("/api/period/2026-01/step").status_code == 409
    assert api.get("/api/period/2026-13").status_code == 422


def test_amounts_are_decimal_strings(api):
    period = api.get("/api/period/2026-01").json()
    assert period["postings"] and all(isinstance(p["debit"], str) for p in period["postings"])
    assert all(isinstance(c["fired_count"], int) for c in api.get("/api/controls").json())


def test_the_engine_left_its_cards_and_signed_nothing(api):
    period = api.get("/api/period/2026-01").json()
    assert {c["state"] for c in period["customers"]} <= {"ESCALATED", "REVIEWED"}
    assert any(f["escalation_type"] == "sod" for f in period["findings"])       # EV-01, the Kroger sales lead
    cards = api.get("/api/escalations").json()
    assert cards and all(isinstance(o, dict) and {"id", "label", "decision"} <= set(o) for c in cards for o in c["options"])


def test_answering_writes_a_precedent(api):
    card = api.get("/api/escalations").json()[0]
    wrong = api.post(f"/api/escalations/{card['id']}/answer", json={"answer": card["options"][0]["id"],
                                                                  "answered_by": "sales.walmart"})
    assert wrong.status_code == 403
    assert api.post(f"/api/escalations/{card['id']}/answer", json={"answer": "nope"}).status_code == 422
    ok = api.post(f"/api/escalations/{card['id']}/answer",
                  json={"answer": card["options"][0]["label"], "reasoning": "As the program says."}).json()
    assert ok["precedent_id"]
    assert card["id"] not in {c["id"] for c in api.get("/api/escalations").json()}
    again = api.post(f"/api/escalations/{card['id']}/answer", json={"answer": card["options"][0]["id"]})
    assert again.status_code == 422


def test_a_named_reviewer_signs_a_clean_period(api):
    period = api.get("/api/period/2026-01").json()
    clean = next(c["customer_id"] for c in period["customers"] if c["state"] == "REVIEWED")
    assert api.post("/api/period/2026-01/sign", json={"customer_id": clean, "signed_by": "sales.walmart"}).status_code == 403
    assert api.post("/api/period/2026-01/sign", json={"customer_id": clean}).status_code == 200
    assert api.post("/api/period/2026-01/sign", json={"customer_id": clean}).status_code == 409


def test_explain_and_ask(api):
    period = api.get("/api/period/2026-01").json()
    accrual = next(p for p in period["postings"] if p["entry_type"] == "accrual" and p["program_id"] == "TP-0214"
                   and p["credit"] != "0.00")
    ex = api.get(f"/api/explain/{accrual['id']}").json()
    assert ex["line"]["id"] == accrual["id"]
    assert [s["label"] for s in ex["chain"]["steps"]][:4] == ["rule", "terms", "inputs", "knew-at"]
    assert "TP-0214#4.2" in ex["text"]
    assert api.get("/api/explain/JE-0").status_code == 404
    answer = api.post("/api/ask", json={"question": f"Why did you post {accrual['journal_id']}?"}).json()
    assert answer["chains"][0]["entry_id"] == accrual["id"] and answer["drafted_by"] == "agent"
    assert api.post("/api/ask", json={"question": "hello?"}).json()["chains"] == []


def test_metrics(api):
    m = api.get("/api/metrics?as_of=month-1").json()
    assert m["as_of"] == "2026-01" and 0 <= m["recall"] <= 1


def test_the_package_matches_the_books(api, conn):
    from tpa.asof import balances_as_of
    from tpa.export import parse_as_of
    pkg = api.get("/api/period/2026-01/package?as_of=month-1").json()
    with conn.cursor() as cur:
        for c in pkg["customers"]:
            books = balances_as_of(cur, "2026-01", parse_as_of("month-1"), c["customer_id"])
            assert c["balances"] == {k: str(v) for k, v in books.items()}
            assert c["totals"]["debit"] == c["totals"]["credit"]
            assert all(r["ending"] == r["outstanding"] for r in c["reconciliation"])


def test_the_export_carries_excel_checks(api):
    text = api.get("/api/period/2026-01/export/ledger.csv?as_of=month-1").text
    total, check = text.strip().splitlines()[-2:]
    assert total.startswith("TOTAL,") and "=SUM(" in total
    assert check.startswith("CHECK,=") and check.endswith(",0.00")
    assert api.get("/api/period/2026-01/export/secrets.csv").status_code == 404
