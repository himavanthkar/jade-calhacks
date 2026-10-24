"""Workstream C: the SoD throw, the precedent loop, and the year with the model-played humans."""

from datetime import datetime
from decimal import Decimal

import pytest

from helpers import deduction
from test_engine import check_restatement, invariant_breaches, moment_catch_ups, run_all
from tpa import judgment, model, players
from tpa.constants import Control as C
from tpa.controls import Hit
from tpa.evaluate import metrics
from tpa.execute import finding, raise_finding
from tpa.rows import all_rows, one_row
from tpa.seed.generate import build
from tpa.sod import SegregationOfDutiesError, can_approve

AT = datetime(2026, 9, 30, 18)


@pytest.fixture
def people(base):
    with base.cursor() as cur:
        cur.execute("INSERT INTO actors VALUES ('agent', 'Trade promotion autonomy', 'agent', NULL)")
        cur.execute("INSERT INTO actors VALUES ('tpa.human', 'Trade promotion accountant', "
                    "'trade_promotion_accountant', NULL)")
        cur.execute("""INSERT INTO controls (id, name, condition, threshold, threshold_unit, owner_role, mined_at, learned)
                       VALUES (%s, 'Redemption drift', 'true', 0.5, 'pct', 'trade_promotion_accountant', %s, TRUE)""",
                    (C.REDEMPTION_DRIFT, AT))
    base.commit()
    return base


def drift(cur, origin: str) -> dict:
    hit = Hit(C.REDEMPTION_DRIFT, "redemption_drift", Decimal("1.6"), Decimal("42000"), Decimal("42000"),
              f"TP-0214 {origin}: sell-through above projection.", {"program_id": "TP-0214", "origin": origin})
    control = one_row(cur, "SELECT * FROM controls WHERE id = %s", (C.REDEMPTION_DRIFT,))
    return finding(cur, raise_finding(cur, hit, period="2026-09", customer_id="WMT", at=AT, control=control))


# ── segregation of duties ───────────────────────────────────────────────────
def test_the_negotiator_cannot_approve(people):
    with people.cursor() as cur:
        deduction(cur, "DD-1", "2026-02")
        with pytest.raises(SegregationOfDutiesError, match="negotiated TP-0214 for Walmart; approval routed to controller"):
            can_approve(cur, "sales.walmart", "deduction", "DD-1")
        with pytest.raises(SegregationOfDutiesError, match="never approves"):
            can_approve(cur, "agent", "deduction", "DD-1")
        can_approve(cur, "controller", "deduction", "DD-1")


def test_a_blocked_attempt_is_a_sod_finding(people):
    with people.cursor() as cur:
        deduction(cur, "DD-1", "2026-02")
        event = {"id": "EV-01", "actor_id": "sales.walmart", "action": "approve", "target_type": "deduction",
                 "target_id": "DD-1", "note": "approve it"}
        judgment.on_event(cur, event, AT)
        f = one_row(cur, "SELECT * FROM findings WHERE control_id = %s", (C.SOD,))
    assert (f["state"], f["escalation_type"]) == ("resolved", "sod")
    assert f["evidence"]["event_id"] == "EV-01" and f["evidence"]["negotiated_by"] == "sales.walmart"
    assert f["evidence"]["resolution"]["decision"] == "blocked"


# ── the precedent loop ──────────────────────────────────────────────────────
def test_answer_once_then_pass_silently(people):
    with people.cursor() as cur:
        first = drift(cur, "2026-04")
        judgment.judge(cur, first, AT)
        (esc,) = judgment.open_escalations(cur)
        assert esc["to_role"] == "trade_promotion_accountant"
        assert [o["id"] for o in esc["options"]] == ["acknowledge", "hold"]

        out = judgment.answer(cur, esc["id"], "acknowledge", "tpa.human", AT, reasoning="Fold it into the estimate.")
        p = one_row(cur, "SELECT * FROM precedents WHERE id = %s", (out["precedent_id"],))
        assert (p["decision"], p["reasoning"], p["from_escalation_id"]) == ("acknowledge", "Fold it into the estimate.",
                                                                            esc["id"])

        second = drift(cur, "2026-05")
        judgment.judge(cur, second, AT)
        assert judgment.open_escalations(cur) == []
        second = finding(cur, second["id"])
    assert second["state"] == "auto_resolved" and second["evidence"]["precedent_id"] == p["id"]


def test_answers_are_checked(people):
    with people.cursor() as cur:
        judgment.judge(cur, drift(cur, "2026-04"), AT)
        (esc,) = judgment.open_escalations(cur)
        with pytest.raises(PermissionError, match="cannot answer a card addressed to the trade_promotion_accountant"):
            judgment.answer(cur, esc["id"], "acknowledge", "sales.walmart", AT, reasoning="fine")
        with pytest.raises(ValueError, match="carries its reasoning"):
            judgment.answer(cur, esc["id"], "acknowledge", "tpa.human", AT, reasoning=" ")
        with pytest.raises(ValueError, match="not an option"):
            judgment.answer(cur, esc["id"], "approve", "tpa.human", AT, reasoning="fine")


def test_a_bigger_case_asks_again():
    p = {"decision": "top_up_and_clear", "exposure_limit": Decimal("100"), "standing_limit": Decimal("100")}
    assert judgment.covers(p, {"exposure": Decimal("100")})
    assert not judgment.covers(p, {"exposure": Decimal("100.01")})
    assert judgment.covers({**p, "decision": "dispute"}, {"exposure": Decimal("1e9")})


def test_one_clause_never_decides_another():
    f = {"control_id": C.RATE_CONFLICT, "conflict_type": "terms_reading", "evidence": {"source_clause_id": "TP-0232#3.1"}}
    g = {**f, "evidence": {"source_clause_id": "TP-0233#3.4"}}
    assert judgment.conflict_key(f) != judgment.conflict_key(g)


# ── the model is optional and never trusted with facts ──────────────────────
def test_model_off_by_default(monkeypatch):
    monkeypatch.delenv("TPA_USE_MODEL", raising=False)
    assert model.ask("system", "prompt") is None


def test_a_rewrite_that_changes_a_number_is_dropped():
    card = "DD-0171 claims $4.20/case; TP-0214 says $3.80/case. $50,814.00 is held."
    assert model.keeps_facts(card, "TP-0214 says $3.80/case but DD-0171 claims $4.20/case, holding $50,814.00.")
    assert not model.keeps_facts(card, "DD-0171 claims $4.20/case; TP-0214 says $3.80/case. $50,000 is held.")


def test_the_played_role_must_pick_a_real_option(monkeypatch):
    esc = {"question": "?", "options": [{"id": "program", "label": "Program", "decision": "dispute"}]}
    monkeypatch.setattr(model, "ask_json", lambda *a, **k: {"option_id": "approve_everything", "reasoning": "yes"})
    assert players.played({"evidence": {}}, esc, "persona") is None
    monkeypatch.setattr(model, "ask_json", lambda *a, **k: {"option_id": "program", "reasoning": "as signed"})
    assert players.played({"evidence": {}}, esc, "persona") == ("program", "as signed")


def test_overruling_the_recommendation_needs_a_reason(people):
    with people.cursor() as cur:
        judgment.judge(cur, drift(cur, "2026-04"), AT)
        (esc,) = judgment.open_escalations(cur)
        assert esc["recommended"] == "acknowledge"
        assert [o["recommended"] for o in esc["options"]] == [True, False]
        hold = next(o for o in esc["options"] if o["id"] == "hold")
        with pytest.raises(ValueError, match="Overruling the recommendation"):
            judgment.answer(cur, esc["id"], "hold", "tpa.human", AT, reasoning=hold["label"])
        out = judgment.answer(cur, esc["id"], "hold", "tpa.human", AT, reasoning="Wait for two more months of scans.")
    assert out["overrode"] == "acknowledge"


# ── the year, with judgment and the model-played humans ─────────────────────
@pytest.fixture(scope="module")
def year():
    ds = build(1337, 24)
    conn = run_all(ds, players.hooks())
    yield ds, conn
    conn.close()


def test_the_year_catches_every_planted_error(year):
    ds, conn = year
    with conn.cursor() as cur:
        m = metrics(cur, ds.answer_key, "month-12")
    assert m["recall"] == 1.0 and m["missed"] == []
    assert m["precision"] == 1.0 and m["false_positives"] == []


def test_both_self_approvals_throw(year):
    _, conn = year
    with conn.cursor() as cur:
        rows = all_rows(cur, "SELECT * FROM findings WHERE escalation_type = 'sod' ORDER BY id")
        assert [(r["evidence"]["event_id"], r["evidence"]["actor_id"]) for r in rows] == \
            [("EV-01", "sales.kroger"), ("EV-02", "sales.walmart")]
        cur.execute("""SELECT COUNT(*) FROM ledger_entries e JOIN trade_programs p ON p.id = e.program_id
                       WHERE e.approved_by = p.negotiated_by""")
        assert cur.fetchone()[0] == 0
        cur.execute("""SELECT COUNT(*) FROM precedents x JOIN findings f ON f.customer_id = x.customer_id
                       JOIN trade_programs p ON p.id = f.evidence ->> 'program_id'
                       WHERE x.decided_by = p.negotiated_by""")
        assert cur.fetchone()[0] == 0


def test_the_controller_approves_the_restatement(year):
    ds, conn = year
    with conn.cursor() as cur:
        f = one_row(cur, "SELECT * FROM findings WHERE conflict_type = 'amendment_not_applied'")
        check_restatement(moment_catch_ups(cur, ds), f, ds.answer_key["moment"])
        esc = one_row(cur, "SELECT * FROM escalations WHERE finding_id = %s", (f["id"],))
    assert (esc["to_role"], esc["answer"], esc["answered_by"]) == ("controller", "approve", "controller")


def test_every_card_is_answered_and_teaches(year):
    _, conn = year
    with conn.cursor() as cur:
        rows = all_rows(cur, "SELECT * FROM escalations ORDER BY id")
        assert rows and all(r["answered_at"] for r in rows)
        assert all(r["became_precedent_id"] or r["answer"] in ("hold", "keep") or r["answer"].startswith("precedent:")
                   for r in rows)
        cur.execute("SELECT COUNT(*) FROM findings WHERE evidence ? 'precedent_id' AND state = 'auto_resolved'")
        assert cur.fetchone()[0] > 0                                  # answers came back as silent passes
        assert invariant_breaches(cur) == {"unbalanced": [], "over_cleared": [], "signed_with_failed_gate": []}


def test_a_stale_accrual_names_the_claim_filed_against_another_program(year):
    """Costco's February instalment cites last year's program, so this year's accrual looks unclaimed."""
    _, conn = year
    with conn.cursor() as cur:
        f = one_row(cur, "SELECT * FROM findings WHERE control_id = %s AND evidence ->> 'accrual_key' = %s",
                    (C.STALE_ACCRUAL, "accrual:TP-0222:2026-02"))
    assert f["evidence"]["miscited_deduction_ids"] == ["DD-0113"]
    assert "DD-0113 (TP-0122)" in f["evidence"]["summary"]


def test_an_unmatched_instalment_is_applied_before_the_accrual_is_released(year):
    """Rule 03: Costco's unmatched instalments settle their accruals; only the residual goes back."""
    _, conn = year
    with conn.cursor() as cur:
        cur.execute("""SELECT d.id, COALESCE(SUM(e.debit - e.credit), 0) FROM deductions d
                       LEFT JOIN ledger_entries e ON e.deduction_id = d.id AND e.account = '1250 Deductions pending resolution'
                       WHERE d.id IN ('DD-0101', 'DD-0125', 'DD-0178', 'DD-0190') GROUP BY d.id ORDER BY d.id""")
        assert [p for _, p in cur.fetchall()] == [0, 0, 0, 0]
        released = one_row(cur, """SELECT SUM(debit) AS released FROM ledger_entries
                                   WHERE entry_type = 'adjustment' AND account = '2300 Accrued trade promotion liability'
                                     AND program_id = 'TP-0222' AND valid_time = '2026-01-31'""")["released"]
    assert released == Decimal("1603.53")


def test_the_simulated_liability_sits_in_general_mills_range_all_year(year):
    _, conn = year
    with conn.cursor() as cur:
        rows = all_rows(cur, "SELECT * FROM analytical_reviews ORDER BY period")
    assert len(rows) == 12 and all(r["within_range"] for r in rows)
    assert [r["source"]["fiscal_year"] for r in rows] == [2025] * 6 + [2026] * 6       # FY2026 10-K filed 2026-07-01
    august = next(r for r in rows if r["period"] == "2026-08")
    assert [d["kind"] for d in august["drivers"]] == ["restatement"] * 6
    assert sum(Decimal(str(d["amount"])) for d in august["drivers"]) == Decimal("1391636.52")


def test_answers_stick(year):
    ds, conn = year
    with conn.cursor() as cur:
        j = metrics(cur, ds.answer_key, "month-12")["judgment"]
    assert j["repeat_findings"] > 20 and j["precedent_hit_rate"] >= 0.9
    assert all(a["reason"] == "larger than the standing approval" for a in j["asked_again_detail"])
