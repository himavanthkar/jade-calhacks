"""The monthly cycle: a period state machine per customer, not an agent loop.

    OPEN → ACCRUED → CONTROLLED → ESCALATED → REVIEWED → SIGNED → CLOSED
                                     ↑                            │
                                     └────── RESTATED ────────────┘

`step` runs one simulated month. Source rows are handled on the day they land, in the
order the business would see them, and the period closes on its last day:

  each day   08:00  late returns   → RETURNS-NOT-NETTED, origin accrual re-made net of them
             10:00  amendments     → restatement of every accrued period they reach back into
             12:00  deductions     → recorded, matched, row controls, cleared if authorised
             15:00  scripted human actions, handed to `hooks.on_event`
  close      18:00  revenue; accruals (spec steps 1–5); clearing deferred to the accrual
             20:00  gates; sign-off of every customer-period with nothing left open
             21:00  flux commentary for accounts over materiality; the analytical review

Judgment is workstream C's (`tpa.judgment`). It plugs in through `Hooks`. Alone, the engine
decides only what a mined control lets the agent decide (mechanical disputes and re-estimates);
it never approves and never signs: restatements wait for the controller, clean periods stop at
REVIEWED. Stand-ins (`tpa.autopilot`) and played humans (`tpa.players`) opt in to both.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import psycopg

from tpa.accrual import fixed_fund_amount, rate
from tpa.asof import sim_clock, terms_as_of
from tpa.constants import Account, Control as C, CUSTOMERS, add_months, period_end, period_start
from tpa.controls import (
    Hit, program_on, check_deduction, check_late_return, check_redemption, exceeds,
    match_program, root_cause,
)
from tpa.execute import (
    accrual_posted, authorise, controls, execute, finding, raise_finding, record_deduction, scan_back_estimate,
    segments_memo,
)
from tpa.flux import write_flux
from tpa.review import write_review
from tpa.gates import GateFailure, no_stale_accruals, run_gates, sign_period
from tpa.ledger import Line, post_journal
from tpa.onboarding import ensure_onboarded, learn_control
from tpa.policy import DRIFT_OWNER, DRIFT_TOLERANCE_PCT
from tpa.restate import on_amendment
from tpa.rows import all_rows, one_row

RETURNS_AT, AMENDMENTS_AT, DEDUCTIONS_AT, EVENTS_AT = time(8), time(10), time(12), time(15)
CLOSE_AT, SIGN_AT, FLUX_AT = time(18), time(20), time(21)
UNRESOLVED = ("open", "escalated")

# Controls whose prior-year precedents all took the same mechanical action: the agent applies it.
MECHANICAL = {C.DUPLICATE_DEDUCTION: "dispute", C.NO_PROOF: "dispute", C.RETURNS_NOT_NETTED: "reestimate"}


def at(d: date, t: time) -> datetime:
    return datetime.combine(d, t)


# ── hooks: where workstream C plugs in ──────────────────────────────────────
def default_judge(cur: psycopg.Cursor, f: dict, when: datetime) -> None:
    """Stand-in judgment: apply a mechanical precedent, otherwise leave the finding open for C."""
    decision = MECHANICAL.get(f["control_id"])
    if decision and f["state"] == "open":
        precedents = (f["evidence"] or {}).get("control", {}).get("precedent_ids", [])
        execute(cur, f["id"], decision, "agent", when,
                note=f"mined control {f['control_id']}: {len(precedents)} prior cases all resolved this way")


def ignore_event(cur: psycopg.Cursor, event: dict, when: datetime) -> None:
    return None


def await_approval(cur: psycopg.Cursor, f: dict, when: datetime) -> str | None:
    """The engine never approves: the restatement stays escalated until a person answers."""
    return None


def await_signature(cur: psycopg.Cursor, period: str, customer_id: str, when: datetime) -> str | None:
    """The engine never signs: a clean period stops at REVIEWED until a named reviewer signs."""
    return None


@dataclass
class Hooks:
    judge: Callable[[psycopg.Cursor, dict, datetime], None] = default_judge
    on_event: Callable[[psycopg.Cursor, dict, datetime], None] = ignore_event
    approve: Callable[[psycopg.Cursor, dict, datetime], str | None] = await_approval
    sign: Callable[[psycopg.Cursor, str, str, datetime], str | None] = await_signature


@dataclass
class Run:
    cur: psycopg.Cursor
    period: str
    hooks: Hooks
    deferred: list = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def judge(self, finding_id: str | None, when: datetime) -> None:
        if finding_id:
            self.hooks.judge(self.cur, finding(self.cur, finding_id), when)


# ── period state ────────────────────────────────────────────────────────────
def set_state(cur: psycopg.Cursor, period: str, customer_id: str, state: str) -> None:
    """Move an unsigned period forward. Signed, closed and restated periods move only by signing."""
    cur.execute("UPDATE periods SET state = %s WHERE period = %s AND customer_id = %s AND signed_at IS NULL",
                (state, period, customer_id))


def unresolved(cur: psycopg.Cursor, period: str, customer_id: str) -> int:
    cur.execute("SELECT COUNT(*) FROM findings WHERE period = %s AND customer_id = %s AND state = ANY(%s)",
                (period, customer_id, list(UNRESOLVED)))
    return cur.fetchone()[0]


# ── the day ─────────────────────────────────────────────────────────────────
def on_return(run: Run, ret: dict, when: datetime) -> None:
    lib = controls(run.cur)
    hit = check_late_return(run.cur, ret)
    if hit is None or C.RETURNS_NOT_NETTED not in lib or not accrual_posted(run.cur, hit.evidence["program_id"],
                                                                             hit.evidence["origin"]):
        return
    hit.evidence["accrual_key"] = f"accrual:{hit.evidence['program_id']}:{hit.evidence['origin']}"
    sh = one_row(run.cur, "SELECT customer_id FROM shipments WHERE id = %s", (ret["shipment_id"],))
    run.judge(raise_finding(run.cur, hit, period=run.period, customer_id=sh["customer_id"], at=when,
                            control=lib[C.RETURNS_NOT_NETTED]), when)


def rate_conflict_group(cur: psycopg.Cursor, hit, period: str, ded: dict) -> str | None:
    """Claims at the same disputed rate for the same origin share one finding: one question for the customer team."""
    if hit.control_id != C.RATE_CONFLICT or hit.conflict_type != "claimed_rate":
        return None
    row = one_row(cur, """SELECT id, evidence FROM findings WHERE control_id = %s AND conflict_type = 'claimed_rate'
                            AND period = %s AND customer_id = %s AND state = ANY(%s)
                            AND evidence ->> 'program_id' = %s AND evidence ->> 'origin' = %s
                            AND evidence ->> 'claimed_rate' = %s""",
                  (C.RATE_CONFLICT, period, ded["customer_id"], list(UNRESOLVED), hit.evidence["program_id"],
                   ded["claimed_period"], hit.evidence["claimed_rate"]))
    if row is None:
        return None
    ids = row["evidence"]["deduction_ids"] + [ded["id"]]
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM deductions WHERE id = ANY(%s)", (ids,))
    total = cur.fetchone()[0]
    ev = hit.evidence
    summary = (f"{len(ids)} deductions claim {ded['claimed_period']} at ${rate(ev['claimed_rate'])}/case on "
               f"{ev['program_id']}; as we hold it, {ev['program_id']} says ${rate(ev['program_rate'])}/case "
               f"({ev['source_clause_id']}). "
               f"${total:,} is held. Which is the source of truth?")
    cur.execute("""UPDATE findings SET amount = amount + %s, exposure = exposure + %s,
                     evidence = evidence || jsonb_build_object('deduction_ids', %s::jsonb, 'summary', %s::text)
                   WHERE id = %s""",
                (hit.amount, hit.exposure, json.dumps(ids), summary, row["id"]))
    return row["id"]


def on_deduction(run: Run, ded: dict, when: datetime) -> None:
    cur = run.cur
    program_id, how = match_program(cur, ded, when)
    record_deduction(cur, ded, program_id, run.period, when)
    if program_id is None:
        run.log.append(f"{ded['id']} unmatched ({ded['reason_code']}); held in 1250")
        return
    lib = controls(cur)
    hits = [h for h in root_cause(check_deduction(cur, ded, program_id, when))
            if h.control_id in lib and exceeds(h, lib[h.control_id]["threshold"])]
    if not hits:
        run.judge(authorise(cur, ded, program_id, run.period, when, deferred=run.deferred), when)
        return
    top = hits[0]
    top.evidence.update(matched=how, also=[h.control_id for h in hits[1:]])
    fid = rate_conflict_group(cur, top, run.period, ded) or raise_finding(
        cur, top, period=run.period, customer_id=ded["customer_id"], at=when, control=lib[top.control_id])
    run.judge(fid, when)


def run_day(run: Run, d: date) -> None:
    cur = run.cur
    for ret in all_rows(cur, "SELECT * FROM returns WHERE available_at = %s ORDER BY id", (d,)):
        on_return(run, ret, at(d, RETURNS_AT))
    for am in all_rows(cur, "SELECT * FROM program_amendments WHERE available_at = %s ORDER BY id", (d,)):
        fid = on_amendment(cur, am, run.period, at(d, AMENDMENTS_AT), run.hooks.approve)
        run.log.append(f"{am['id']} landed: restatement finding {fid}")
    for ded in all_rows(cur, "SELECT * FROM deductions WHERE available_at = %s ORDER BY id", (d,)):
        on_deduction(run, ded, at(d, DEDUCTIONS_AT))
    for ev in all_rows(cur, "SELECT * FROM scripted_events WHERE sim_date = %s ORDER BY id", (d,)):
        run.hooks.on_event(cur, ev, at(d, EVENTS_AT))


# ── the close ───────────────────────────────────────────────────────────────
def post_revenue(cur: psycopg.Cursor, customer_id: str, period: str, when: datetime) -> str | None:
    cur.execute("SELECT COALESCE(SUM(gross_amount), 0), COALESCE(SUM(off_invoice_amount), 0) FROM invoices "
                "WHERE customer_id = %s AND period = %s", (customer_id, period))
    gross, off_invoice = cur.fetchone()
    cur.execute("""SELECT COALESCE(SUM(r.cases * s.gross_price), 0) FROM returns r JOIN shipments s ON s.id = r.shipment_id
                   WHERE r.customer_id = %s AND r.available_at BETWEEN %s AND %s""",
                (customer_id, period_start(period), period_end(period)))
    returned = round(cur.fetchone()[0], 2)
    if gross == 0:
        return None
    lines = [Line(Account.ACCOUNTS_RECEIVABLE, debit=gross - off_invoice, memo=f"Invoices {period}, net of off-invoice"),
             Line(Account.GROSS_SALES, credit=gross, memo=f"Gross sales {period}")]
    if off_invoice:
        lines.insert(1, Line(Account.TRADE_PROMO_EXPENSE, debit=off_invoice, memo=f"Off-invoice allowances {period}"))
    if returned:
        lines += [Line(Account.GROSS_SALES, debit=returned, memo=f"Returns landed {period}"),
                  Line(Account.ACCOUNTS_RECEIVABLE, credit=returned, memo=f"Returns landed {period}")]
    return post_journal(cur, entry_type="revenue", period=period, customer_id=customer_id, decision_time=when,
                        lines=lines)


def post_accruals(cur: psycopg.Cursor, customer_id: str, period: str, when: datetime) -> list[str]:
    """Spec steps 1–5: gather the period's volume, project redemption, accrue each open program."""
    journals = []
    for p in all_rows(cur, """SELECT DISTINCT program_id FROM program_terms
                               WHERE customer_id = %s AND window_start <= %s AND window_end >= %s AND decision_time <= %s
                               ORDER BY program_id""",
                      (customer_id, period_end(period), period_start(period), when)):
        program_id = p["program_id"]
        if accrual_posted(cur, program_id, period):
            continue
        term = terms_as_of(cur, program_id, period_start(period), when)
        if term is None or term["program_type"] == "off_invoice":
            continue
        if term["program_type"] == "scan_back":
            amount, segs, _ = scan_back_estimate(cur, program_id, period, when, when)
            memo = segments_memo(program_id, period, segs, term["projected_redemption"], when)
        else:
            amount = fixed_fund_amount(term, period)
            memo = (f"Accrue {program_id} {period}: "
                    + (f"one feature event at ${term['rate']:,}" if term["program_type"] == "display"
                       else f"${term['rate']:,} fund over the window, monthly share")
                    + f" ({term['source_clause_id']}, terms as known {when:%Y-%m-%d})")
        if amount <= 0:
            continue
        journals.append(post_journal(
            cur, entry_type="accrual", period=period, customer_id=customer_id, program_id=program_id,
            decision_time=when,
            lines=[Line(Account.TRADE_PROMO_EXPENSE, debit=amount, memo=memo),
                   Line(Account.ACCRUED_TRADE_PROMO, credit=amount, memo=memo)]))
    return journals


def raise_stale(run: Run, customer_id: str, when: datetime) -> None:
    """STALE-ACCRUAL as a finding, once per accrual, before the gate that enforces it blocks the close."""
    cur, lib = run.cur, controls(run.cur)
    if C.STALE_ACCRUAL not in lib:
        return
    for v in no_stale_accruals(cur, run.period, customer_id, when).violations:
        if one_row(cur, "SELECT 1 AS x FROM findings WHERE control_id = %s AND evidence ->> 'accrual_key' = %s",
                   (C.STALE_ACCRUAL, v["key"])):
            continue
        pending = all_rows(cur, """SELECT d.id FROM deductions d WHERE d.customer_id = %s AND d.claimed_period = %s
                                     AND d.available_at <= %s AND (d.program_id = %s OR d.program_id IS NULL)
                                     AND NOT EXISTS (SELECT 1 FROM ledger_entries e WHERE e.deduction_id = d.id
                                                     AND e.entry_type IN ('clearing', 'dispute'))
                                   ORDER BY d.id""",
                           (customer_id, v["origin"], when.date(), v["program_id"]))
        # The claim may have arrived citing another program of the same kind (an old or neighbouring one).
        miscited = all_rows(cur, """SELECT d.id, d.program_id FROM deductions d
                                      JOIN trade_programs o ON o.id = d.program_id
                                      JOIN trade_programs p ON p.id = %s AND p.program_type = o.program_type
                                    WHERE d.customer_id = %s AND d.claimed_period = %s AND d.available_at <= %s
                                      AND d.program_id <> p.id ORDER BY d.id""",
                            (v["program_id"], customer_id, v["origin"], when.date()))
        hit = Hit(C.STALE_ACCRUAL, "stale_accrual", Decimal(v["age_periods"] - v["allowed_periods"] + 2),
                  v["outstanding"], v["outstanding"],
                  f"{v['key']} still carries ${v['outstanding']:,} after {v['age_periods']} periods with no deduction "
                  f"cleared against it (allowed {v['allowed_periods']})."
                  + (f" Unmatched deductions that may belong to it: {', '.join(p['id'] for p in pending)}." if pending else "")
                  + (f" Claimed for {v['origin']} against another program: "
                     f"{', '.join(m['id'] + ' (' + m['program_id'] + ')' for m in miscited)}." if miscited else ""),
                  {"accrual_key": v["key"], "program_id": v["program_id"], "origin": v["origin"],
                   "outstanding": v["outstanding"], "age_periods": v["age_periods"],
                   "candidate_deduction_ids": [p["id"] for p in pending],
                   "miscited_deduction_ids": [m["id"] for m in miscited]})
        run.judge(raise_finding(cur, hit, period=run.period, customer_id=customer_id, at=when,
                                control=lib[C.STALE_ACCRUAL]), when)


def watch_redemption(run: Run, when: datetime) -> None:
    """Origins whose claims landed this period: compare sell-through with the projection. The
    first divergence beyond tolerance teaches the library a control history could not."""
    cur = run.cur
    for o in all_rows(cur, """SELECT DISTINCT d.customer_id, d.claimed_period FROM deductions d
                               WHERE d.available_at BETWEEN %s AND %s AND d.reason_code LIKE 'SB-%%'
                               ORDER BY 1, 2""", (period_start(run.period), period_end(run.period))):
        program_id = program_on(cur, o["customer_id"], "scan_back", period_start(o["claimed_period"]), when)
        hit = program_id and check_redemption(cur, program_id, o["claimed_period"], when)
        if not hit or hit.measure <= DRIFT_TOLERANCE_PCT:
            continue
        if learn_control(cur, C.REDEMPTION_DRIFT, DRIFT_TOLERANCE_PCT, DRIFT_OWNER, when):
            run.log.append(f"learned {C.REDEMPTION_DRIFT}: {hit.summary}")
        run.judge(raise_finding(cur, hit, period=run.period, customer_id=o["customer_id"], at=when,
                                control=controls(cur)[C.REDEMPTION_DRIFT]), when)


def try_sign(run: Run, period: str, customer_id: str, when: datetime) -> str:
    """Gates always run (their results are the evidence); sign only a clean, fully judged period."""
    cur = run.cur
    results = run_gates(cur, period, customer_id, when)
    failed = [name for name, r in results.items() if not r.passed]
    if unresolved(cur, period, customer_id):
        set_state(cur, period, customer_id, "ESCALATED")
        return "ESCALATED"
    if failed:
        run.log.append(f"{period} {customer_id} blocked by gates: {', '.join(failed)}")
        set_state(cur, period, customer_id, "CONTROLLED")
        return "BLOCKED"
    set_state(cur, period, customer_id, "REVIEWED")
    signer = run.hooks.sign(cur, period, customer_id, when)
    if not signer:
        return "REVIEWED"
    try:
        sign_period(cur, period, customer_id, signer, when)
    except GateFailure as e:
        run.log.append(str(e))
        return "BLOCKED"
    cur.execute("SELECT bool_and(state = 'SIGNED') FROM periods WHERE period = %s", (period,))
    if cur.fetchone()[0]:
        cur.execute("UPDATE periods SET state = 'CLOSED' WHERE period = %s AND state = 'SIGNED'", (period,))
    return "SIGNED"


def close(run: Run) -> dict:
    cur, period = run.cur, run.period
    end = period_end(period)
    customers = list(CUSTOMERS)
    for cid in customers:
        post_revenue(cur, cid, period, at(end, CLOSE_AT))
        post_accruals(cur, cid, period, at(end, CLOSE_AT))
        set_state(cur, period, cid, "ACCRUED")
    for ded, program_id in run.deferred:
        run.judge(authorise(cur, ded, program_id, period, at(end, CLOSE_AT)), at(end, CLOSE_AT))
    run.deferred.clear()
    watch_redemption(run, at(end, CLOSE_AT))
    # Anything still unjudged — including follow-ups a decision raised mid-month — gets judged now.
    for f in all_rows(cur, "SELECT * FROM findings WHERE state = 'open' AND period <= %s ORDER BY id", (period,)):
        run.hooks.judge(cur, f, at(end, CLOSE_AT))
    states = {}
    for cid in customers:
        set_state(cur, period, cid, "CONTROLLED")
        raise_stale(run, cid, at(end, CLOSE_AT))
        states[cid] = try_sign(run, period, cid, at(end, SIGN_AT))
    # Periods left open earlier may be clean now that their escalations are answered.
    for row in all_rows(cur, "SELECT period, customer_id FROM periods WHERE period < %s AND period >= '2026-01' "
                             "AND signed_at IS NULL ORDER BY period, customer_id", (period,)):
        try_sign(run, row["period"], row["customer_id"], at(end, SIGN_AT))
    write_flux(cur, period, at(end, FLUX_AT))
    write_review(cur, period, at(end, FLUX_AT))
    return states


# ── stepping ────────────────────────────────────────────────────────────────
def last_period(cur: psycopg.Cursor) -> str:
    cur.execute("SELECT MAX(period) FROM periods")
    return cur.fetchone()[0]


def run_period(cur: psycopg.Cursor, period: str, hooks: Hooks) -> dict:
    run = Run(cur, period, hooks)
    d = period_start(period)
    while d <= period_end(period):
        run_day(run, d)
        d += timedelta(days=1)
    states = close(run)
    cur.execute("""SELECT control_id, state, COUNT(*) FROM findings WHERE period = %s
                   GROUP BY control_id, state ORDER BY control_id, state""", (period,))
    return {"period": period, "states": states, "findings": [list(r) for r in cur.fetchall()], "log": run.log}


def step(conn: psycopg.Connection, hooks: Hooks | None = None) -> dict:
    """Advance the clock one month: run the period the clock points at, then move it on."""
    hooks = hooks or Hooks()
    with conn.cursor() as cur:
        ensure_onboarded(cur)
        period, _ = sim_clock(cur)
        if period > last_period(cur):
            raise RuntimeError(f"the simulation ends at {last_period(cur)}")
        summary = run_period(cur, period, hooks)
        cur.execute("UPDATE sim_clock SET current_period = %s, sim_date = %s", (add_months(period, 1), period_end(period)))
    conn.commit()
    return summary


def run_through(conn: psycopg.Connection, through: str, hooks: Hooks | None = None) -> list[dict]:
    """Step until the period `through` ('2026-09' or 'month-9') has run."""
    if through.startswith("month-"):
        through = add_months("2026-01", int(through.split("-", 1)[1]) - 1)
    out = []
    while True:
        with conn.cursor() as cur:
            period, _ = sim_clock(cur)
        conn.commit()
        if period > through:
            return out
        out.append(step(conn, hooks))
