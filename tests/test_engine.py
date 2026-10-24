"""Workstream B end to end on the real seed: onboarding, the monthly cycle, restatement.

One seeded run per module is shared between tests (the schema reset is the slow part),
so these tests read; they never step the clock themselves.
"""

from datetime import datetime
from decimal import Decimal

import psycopg
import pytest

from tpa import autopilot, restate
from tpa.asof import balances_as_of, entry_history, liability_outstanding
from tpa.constants import Account
from tpa.cycle import Hooks, run_through
from tpa.db import connect, reset_schema
from tpa.evaluate import metrics
from tpa.onboarding import mine
from tpa.rows import all_rows, one_row
from tpa.seed.generate import build
from tpa.seed.load import load

LIAB = Account.ACCRUED_TRADE_PROMO
ENTERED = datetime(2026, 8, 19, 9)
RESTATED_AT = datetime(2026, 8, 19, 11)
INBOX_APPROVAL = datetime(2026, 8, 31, 23)


@pytest.fixture(scope="module")
def ds():
    return build(1337, 24)


def run_all(ds, hooks, through: str = "2026-12") -> psycopg.Connection:
    """Seed the test database and step all twelve live months. Returns an autocommit connection,
    so reads never hold a lock that the next schema reset would wait on."""
    conn = connect()
    reset_schema(conn)
    load(conn, ds, load_terms=True)
    run_through(conn, through, hooks)
    conn.autocommit = True
    return conn


def moment_catch_ups(cur, ds, after: datetime = RESTATED_AT) -> dict[str, Decimal]:
    return {p["period"]: balances_as_of(cur, p["period"], ENTERED, "WMT")[LIAB]
            - balances_as_of(cur, p["period"], after, "WMT")[LIAB] for p in ds.answer_key["moment"]["periods"]}


def invariant_breaches(cur) -> dict[str, list]:
    cur.execute("SELECT journal_id FROM ledger_entries GROUP BY journal_id HAVING SUM(debit) <> SUM(credit)")
    unbalanced = cur.fetchall()
    cur.execute("""SELECT program_id, valid_time FROM ledger_entries WHERE account = %s
                   GROUP BY 1, 2 HAVING SUM(credit) - SUM(debit) < 0""", (LIAB,))
    over_cleared = cur.fetchall()
    cur.execute("""SELECT period, customer_id FROM periods WHERE signed_at IS NOT NULL AND EXISTS (
                     SELECT 1 FROM jsonb_each(gate_results) g WHERE (g.value ->> 'passed')::boolean = false)""")
    return {"unbalanced": unbalanced, "over_cleared": over_cleared, "signed_with_failed_gate": cur.fetchall()}


@pytest.fixture(scope="module")
def engine_alone(ds) -> dict:
    """The engine alone, with no one to approve or sign. Then a controller approves the restatement
    from the inbox at the end of August, and the year runs on. Reduced to plain values."""
    conn = run_all(ds, Hooks(), through="2026-08")
    with conn.cursor() as cur:
        pending = one_row(cur, "SELECT * FROM findings WHERE conflict_type = 'amendment_not_applied'")
        cur.execute("SELECT state, COUNT(*) FROM periods WHERE period >= '2026-01' GROUP BY 1")
        alone = {"states": dict(cur.fetchall()), "restatement_state": pending["state"]}
        cur.execute("SELECT COUNT(*) FROM ledger_entries WHERE approved_by IS NOT NULL AND decision_time >= '2026-01-01'")
        alone["approved_lines"] = cur.fetchone()[0]
        restate.apply(cur, pending["id"], "controller", INBOX_APPROVAL, period="2026-08")
    run_through(conn, "2026-12", Hooks())
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM period_signoffs")
        alone["signoffs"] = cur.fetchone()[0]
        f = one_row(cur, "SELECT * FROM findings WHERE id = %s", (pending["id"],))
        snap = {"alone": alone, "catch_ups": moment_catch_ups(cur, ds, after=INBOX_APPROVAL), "restatement": f,
                "invariants": invariant_breaches(cur), "metrics": metrics(cur, ds.answer_key, "month-12")}
    conn.close()
    return snap


@pytest.fixture(scope="module")
def with_standins(ds, engine_alone):
    """Stand-in humans answering as last year's did. Depends on engine_alone so that run is finished first."""
    conn = run_all(ds, autopilot.hooks())
    yield conn
    conn.close()


def test_the_engine_alone_never_approves_or_signs(engine_alone):
    alone = engine_alone["alone"]
    assert alone["signoffs"] == 0 and alone["approved_lines"] == 0
    assert alone["restatement_state"] == "escalated"
    assert "SIGNED" not in alone["states"] and "CLOSED" not in alone["states"]
    assert alone["states"].get("REVIEWED", 0) > 0


# ── onboarding ──────────────────────────────────────────────────────────────
def test_miner_finds_every_control_history_can_teach(ds):
    conn = connect()
    reset_schema(conn)
    load(conn, ds, load_terms=True)
    with conn.cursor() as cur:
        out = mine(cur)
    conn.close()
    truth = {c["id"]: c for c in ds.answer_key["controls_truth"] if c["precedent_ids"]}
    mined = {c["id"]: c for c in out["controls"]}
    assert out["unexplained_decisions"] == []
    assert set(mined) == set(truth)
    for cid, t in truth.items():
        assert Decimal(str(mined[cid]["threshold"])) == Decimal(str(t["threshold"])), cid
        assert mined[cid]["owner_role"] == t["owner_role"], cid
        assert sorted(mined[cid]["precedent_ids"]) == sorted(t["precedent_ids"]), cid


# ── the moment ──────────────────────────────────────────────────────────────
def check_restatement(catch_ups: dict, f: dict, moment: dict) -> None:
    assert catch_ups == {p["period"]: Decimal(p["catch_up"]) for p in moment["periods"]}
    assert sum(catch_ups.values()) == Decimal(moment["total_catch_up"])
    assert (f["state"], f["escalation_type"], f["amount"]) == ("resolved", "authority", Decimal(moment["total_catch_up"]))


def test_amendment_restates_each_period_to_the_cent(ds, engine_alone, with_standins):
    check_restatement(engine_alone["catch_ups"], engine_alone["restatement"], ds.answer_key["moment"])
    with with_standins.cursor() as cur:
        check_restatement(moment_catch_ups(cur, ds),
                          one_row(cur, "SELECT * FROM findings WHERE conflict_type = 'amendment_not_applied'"),
                          ds.answer_key["moment"])


def test_both_reasonings_survive(with_standins):
    with with_standins.cursor() as cur:
        feb = one_row(cur, """SELECT * FROM ledger_entries WHERE entry_type = 'accrual' AND program_id = 'TP-0214'
                                AND period = '2026-02' AND valid_time = '2026-02-28' AND account = %s""", (LIAB,))
        assert "$3.80/case" in feb["memo"] and feb["decision_time"] < ENTERED
        (catch_up,) = entry_history(cur, feb["id"])["restated_by"]
        assert catch_up["approved_by"] == "controller"
        assert "right on the terms known 2026-02-28" in catch_up["memo"]
        states = [r["state"] for r in all_rows(cur, "SELECT state FROM periods WHERE customer_id = 'WMT' AND "
                                                    "period BETWEEN '2026-02' AND '2026-07'")]
        assert states == ["RESTATED"] * 6


def test_the_system_withdraws_its_own_disputes(with_standins):
    """July: the customer team answers 'program as signed', so the agent disputes $0.40/case.
    August: AM-02 lands, and the agent takes those disputes back and clears the claims."""
    with with_standins.cursor() as cur:
        rows = all_rows(cur, """SELECT * FROM findings WHERE control_id = 'CTL-RATE-CONFLICT'
                                  AND conflict_type = 'claimed_rate'""")
        assert rows and all(r["evidence"]["resolution"]["decision"] == "superseded" for r in rows)
        assert all(r["evidence"]["resolution"]["previous"]["decision"] == "dispute_difference" for r in rows)
        cur.execute("""SELECT COALESCE(SUM(debit) - SUM(credit), 0) FROM ledger_entries
                       WHERE account = %s AND deduction_id IN (SELECT jsonb_array_elements_text(evidence -> 'deduction_ids')
                                                              FROM findings WHERE conflict_type = 'claimed_rate')""",
                    (Account.DISPUTE_RECEIVABLE,))
        assert cur.fetchone()[0] == 0


# ── the books ───────────────────────────────────────────────────────────────
def test_ledger_invariants(engine_alone, with_standins):
    assert engine_alone["invariants"] == {"unbalanced": [], "over_cleared": [], "signed_with_failed_gate": []}
    with with_standins.cursor() as cur:
        assert invariant_breaches(cur) == {"unbalanced": [], "over_cleared": [], "signed_with_failed_gate": []}


def test_scored_against_the_answer_key(ds, engine_alone, with_standins):
    with with_standins.cursor() as cur:
        standins = metrics(cur, ds.answer_key, "month-12")
    for m, autonomy in ((engine_alone["metrics"], 0.0), (standins, 0.9)):
        assert m["precision"] >= 0.95
        # Everything but the two segregation-of-duties throws, which are workstream C's.
        assert {r["type"] for r in m["missed"]} <= {"sales_lead_self_approval"}
        assert m["autonomy"] >= autonomy


# ── reconciliation (rule 03) ────────────────────────────────────────────────
def test_reconciliation_identity(with_standins):
    """Per (program, origin): ending accrual = opening + accruals + adjustments − settled claims,
    each term summed from its own entries, equal to the outstanding liability to the cent."""
    with with_standins.cursor() as cur:
        cur.execute("""SELECT program_id, valid_time, entry_type, SUM(credit) - SUM(debit) FROM ledger_entries
                       WHERE account = %s GROUP BY 1, 2, 3""", (LIAB,))
        terms: dict = {}
        for program_id, vt, kind, net in cur.fetchall():
            terms.setdefault((program_id, vt), {})[kind] = net
        outstanding = liability_outstanding(cur, datetime(2027, 1, 1))
    assert terms
    for key, t in terms.items():
        assert set(t) <= {"opening", "accrual", "reversal", "adjustment", "restatement", "clearing"}, key
        estimate_adjustments = t.get("reversal", 0) + t.get("adjustment", 0) + t.get("restatement", 0)
        settled = -t.get("clearing", 0)
        ending = t.get("opening", 0) + t.get("accrual", 0) + estimate_adjustments - settled
        assert ending == outstanding.get(key, 0), key
        assert ending >= 0, key                                          # nothing settled twice


def test_every_deduction_has_one_resolution(with_standins):
    """AR relieved once for the amount taken; every dollar then cleared against an accrual, disputed,
    or still pending — and anything pending is on a finding, never quietly parked."""
    with with_standins.cursor() as cur:
        cur.execute("""
            SELECT d.id, d.amount,
                   COALESCE(SUM(e.credit - e.debit) FILTER (WHERE e.account = %(ar)s), 0),
                   COALESCE(SUM(e.debit - e.credit) FILTER (WHERE e.account = %(pending)s), 0),
                   COALESCE(SUM(e.debit) FILTER (WHERE e.account = %(liab)s AND e.entry_type = 'clearing'), 0),
                   COALESCE(SUM(e.debit - e.credit) FILTER (WHERE e.account = %(disputed)s), 0),
                   EXISTS (SELECT 1 FROM findings f WHERE f.evidence::text LIKE '%%"' || d.id || '"%%')
            FROM deductions d LEFT JOIN ledger_entries e ON e.deduction_id = d.id
            WHERE d.available_at >= '2026-01-01' GROUP BY d.id, d.amount""",
                    {"ar": Account.ACCOUNTS_RECEIVABLE, "pending": Account.DEDUCTIONS_PENDING, "liab": LIAB,
                     "disputed": Account.DISPUTE_RECEIVABLE})
        rows = cur.fetchall()
    assert rows
    for ded_id, amount, ar, pending, cleared, disputed, cited in rows:
        assert ar == amount, ded_id
        assert pending + cleared + disputed == amount, ded_id
        assert pending == 0 or cited, ded_id


def test_trade_promotion_is_contra_revenue(with_standins):
    with with_standins.cursor() as cur:
        cur.execute("SELECT DISTINCT account FROM ledger_entries")
        accounts = {a for (a,) in cur.fetchall()}
        cur.execute("""SELECT COUNT(*) FROM ledger_entries WHERE account = %s
                         AND (approved_by IS NULL OR approved_by NOT IN (SELECT id FROM actors WHERE role = 'controller'))""",
                    (Account.WRITE_OFF,))
        unapproved_writeoffs = cur.fetchone()[0]
    assert all(a[0] in "124" or a == Account.WRITE_OFF for a in accounts), accounts   # no 5xxx/6xxx promo expense
    assert unapproved_writeoffs == 0
