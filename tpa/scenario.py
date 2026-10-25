"""Live scenarios: a person adds source rows to the month the clock is on, and the engine meets them
on the next step exactly as it meets seeded data. Nothing here decides or posts; it only writes what
the outside world would send: a deduction, its backup, a duplicate, a late return, an amendment, an
approval attempt.

    inject(cur, "deduction", {"customer_id": "WMT", "amount": "48000", "program_id": "TP-0214"})

Each injection is recorded in `scenario_injections` with the ids it made, so the evaluator can score
it apart from the planted errors, and the UI can show which rows came from the judge.
"""

import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

import psycopg

from tpa.asof import sim_clock, terms_as_of
from tpa.constants import CUSTOMERS, add_months, period_end, period_of, period_start
from tpa.cycle import last_period
from tpa.rows import all_rows, one_row

KINDS = ("deduction", "duplicate", "backup", "return", "amendment", "approval_attempt", "handoff")
REASON_FOR = {"scan_back": "SB-SUPERCENTER", "display": "DISPLAY", "mdf": "MDF"}


class ScenarioError(ValueError):
    pass


def _id(cur, table: str, prefix: str, width: int) -> str:
    cur.execute(f"SELECT COALESCE(MAX(substring(id FROM %s)::int), 0) + 1 FROM {table}", (rf"^{prefix}-(\d+)$",))
    return f"{prefix}-{cur.fetchone()[0]:0{width}d}"


def _money(v, field: str) -> Decimal:
    try:
        d = Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as err:
        raise ScenarioError(f"{field} must be an amount") from err
    if d <= 0:
        raise ScenarioError(f"{field} must be positive")
    return d


def _date(v, field: str) -> date:
    try:
        return date.fromisoformat(str(v))
    except ValueError as err:
        raise ScenarioError(f"{field} must be YYYY-MM-DD") from err


def _need(p: dict, *fields: str) -> None:
    missing = [f for f in fields if p.get(f) in (None, "")]
    if missing:
        raise ScenarioError(f"missing {', '.join(missing)}")


def landing_day(cur, day: int | None) -> tuple[str, date]:
    """The period the clock is on (not yet run) and the day in it the rows arrive."""
    period, _ = sim_clock(cur)
    if period > last_period(cur):
        raise ScenarioError(f"the simulation ended at {last_period(cur)}")
    start, end = period_start(period), period_end(period)
    d = start + timedelta(days=(day or 1) - 1)
    if not start <= d <= end:
        raise ScenarioError(f"day must be 1 to {end.day} of {period}")
    return period, d


# ── the kinds ───────────────────────────────────────────────────────────────
def _deduction(cur, p: dict, d: date, made: list[str]) -> None:
    _need(p, "customer_id", "amount")
    if p["customer_id"] not in CUSTOMERS:
        raise ScenarioError(f"customer_id must be one of {', '.join(CUSTOMERS)}")
    program = p.get("program_id") and one_row(cur, "SELECT * FROM trade_programs WHERE id = %s", (p["program_id"],))
    if p.get("program_id") and not program:
        # A retailer citing a program we don't have is the matching problem, not bad input: it lands
        # unmatched and the engine has to find it a home or hold it. The citation stays on the payload.
        p["note"] = f"{p['program_id']} is not a program on file: the deduction lands unmatched"
    if program and program["customer_id"] != p["customer_id"]:
        raise ScenarioError(f"{program['id']} is {program['customer_id']}'s program, not {p['customer_id']}'s")
    claimed = p.get("claimed_period") or add_months(period_of(d), -1)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", claimed):
        raise ScenarioError("claimed_period must be YYYY-MM")
    reason = p.get("reason_code") or (REASON_FOR.get(program["program_type"], "MISC") if program else "MISC")
    ded_id = _id(cur, "deductions", "DD", 4)
    cur.execute(
        """INSERT INTO deductions (id, invoice_id, customer_id, program_id, amount, reason_code, claimed_rate, taken_date,
                                   claimed_period, claim_start, claim_end, available_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (ded_id, p.get("invoice_id"), p["customer_id"], program and program["id"], _money(p["amount"], "amount"), reason,
         p.get("claimed_rate"), d, claimed,
         _date(p["claim_start"], "claim_start") if p.get("claim_start") else None,
         _date(p["claim_end"], "claim_end") if p.get("claim_end") else None, d))
    made.append(ded_id)
    if p.get("backup"):
        _backup(cur, {**p["backup"], "deduction_id": ded_id}, d, made)


def _duplicate(cur, p: dict, d: date, made: list[str]) -> None:
    _need(p, "deduction_id")
    src = one_row(cur, "SELECT * FROM deductions WHERE id = %s AND available_at < %s", (p["deduction_id"], d))
    if src is None:
        raise ScenarioError(f"no deduction {p['deduction_id']} has landed yet to duplicate")
    ded_id = _id(cur, "deductions", "DD", 4)
    cur.execute(
        """INSERT INTO deductions (id, invoice_id, customer_id, program_id, amount, reason_code, claimed_rate, taken_date,
                                   claimed_period, claim_start, claim_end, available_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (ded_id, src["invoice_id"], src["customer_id"], src["program_id"], src["amount"], src["reason_code"],
         src["claimed_rate"], d, src["claimed_period"], src["claim_start"], src["claim_end"], d))
    made.append(ded_id)


def _backup(cur, p: dict, d: date, made: list[str]) -> None:
    _need(p, "deduction_id")
    if not one_row(cur, "SELECT id FROM deductions WHERE id = %s", (p["deduction_id"],)):
        raise ScenarioError(f"no deduction {p['deduction_id']}")
    if p.get("scan_units") is not None and int(p["scan_units"]) <= 0:
        raise ScenarioError("scan_units must be positive")
    backup_id = _id(cur, "claim_backup", "CB", 4)
    cur.execute(
        """INSERT INTO claim_backup (id, deduction_id, scan_units, scan_rate, proof_of_performance, notes,
                                     received_date, available_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (backup_id, p["deduction_id"], p.get("scan_units"), p.get("scan_rate"), bool(p.get("proof_of_performance")),
         p.get("notes"), d, d))
    made.append(backup_id)


def _return(cur, p: dict, d: date, made: list[str]) -> None:
    _need(p, "shipment_id", "cases")
    s = one_row(cur, """SELECT s.*, s.cases - COALESCE((SELECT SUM(r.cases) FROM returns r WHERE r.shipment_id = s.id), 0)
                          AS left FROM shipments s WHERE s.id = %s AND s.available_at < %s""", (p["shipment_id"], d))
    if s is None:
        raise ScenarioError(f"no shipment {p['shipment_id']} has landed yet")
    cases = int(p["cases"])
    if not 0 < cases <= s["left"]:
        raise ScenarioError(f"{s['id']} has {s['left']:,} cases that could still come back")
    ret_id = _id(cur, "returns", "RT", 4)
    cur.execute("""INSERT INTO returns (id, shipment_id, customer_id, cases, return_date, available_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""", (ret_id, s["id"], s["customer_id"], cases, d, d))
    made.append(ret_id)


def _amendment(cur, p: dict, d: date, made: list[str]) -> None:
    """A signed change of rate that reaches us today, as a document. The engine reads it into terms
    (tpa.extract) on the day it lands, exactly as it reads AM-02: nothing here writes a term."""
    _need(p, "program_id", "new_rate", "effective_date")
    program = one_row(cur, "SELECT * FROM trade_programs WHERE id = %s", (p["program_id"],))
    if program is None:
        raise ScenarioError(f"no program {p['program_id']}")
    if program["program_type"] != "scan_back":
        raise ScenarioError("only scan-back rates can be amended live: the restatement path re-prices cases")
    effective = _date(p["effective_date"], "effective_date")
    if effective >= d:
        raise ScenarioError("effective_date must be before the day it lands, or there is nothing to restate")
    term = terms_as_of(cur, program["id"], effective, datetime.combine(d, time(8)))
    if term is None or not term["window_start"] <= effective <= term["window_end"]:
        raise ScenarioError(f"{effective} is outside {program['id']}'s window")
    new_rate = _money(p["new_rate"], "new_rate")
    if new_rate == term["rate"]:
        raise ScenarioError(f"{program['id']} is already ${term['rate']}/case on {effective}")
    signed = _date(p["signed_date"], "signed_date") if p.get("signed_date") else effective - timedelta(days=2)
    am_id = _id(cur, "program_amendments", "AM", 2)
    doc = (f"AMENDMENT {am_id} TO TRADE PROMOTION AGREEMENT {program['id']}\nSigned {signed.isoformat()}.\n\n"
           f"Clause 4.2 is replaced in full, effective {effective.isoformat()}:\n"
           f"4.2 The allowance is ${new_rate} per case-equivalent unit scanned.\nAll other terms are unchanged.\n")
    cur.execute("""INSERT INTO program_amendments (id, program_id, document_text, effective_date, signed_date, available_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""", (am_id, program["id"], doc, effective, signed, d))
    made.append(am_id)


def _approval_attempt(cur, p: dict, d: date, made: list[str]) -> None:
    _need(p, "actor_id", "target_type", "target_id")
    if p["target_type"] not in ("deduction", "restatement"):
        raise ScenarioError("target_type must be deduction or restatement")
    if not one_row(cur, "SELECT id FROM actors WHERE id = %s", (p["actor_id"],)):
        raise ScenarioError(f"no actor {p['actor_id']}")
    ev_id = _id(cur, "scripted_events", "EV", 2)
    cur.execute("""INSERT INTO scripted_events (id, sim_date, actor_id, action, target_type, target_id, note)
                   VALUES (%s, %s, %s, 'approve', %s, %s, %s)""",
                (ev_id, d, p["actor_id"], p["target_type"], p["target_id"], p.get("note") or "Approve it."))
    made.append(ev_id)


def _handoff(cur, p: dict, d: date, made: list[str]) -> None:
    """A colleague hands over a held deduction half done, proposing what to do with it."""
    _need(p, "from_actor", "deduction_id")
    actor = one_row(cur, "SELECT * FROM actors WHERE id = %s", (p["from_actor"],))
    if actor is None or actor["role"] == "agent":
        raise ScenarioError("from_actor must be one of the people")
    if not one_row(cur, "SELECT id FROM deductions WHERE id = %s AND available_at < %s", (p["deduction_id"], d)):
        raise ScenarioError(f"no deduction {p['deduction_id']} has landed yet to hand over")
    decision = p.get("proposed_decision", "clear")
    if decision not in ("clear", "dispute"):
        raise ScenarioError("proposed_decision must be clear or dispute")
    ho = _id(cur, "handoffs", "HO", 4)
    cur.execute("""INSERT INTO handoffs (id, sim_date, from_actor, deduction_id, proposed_program_id, proposed_decision,
                                         done, left_to_do) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (ho, d, actor["id"], p["deduction_id"], p.get("proposed_program_id"), decision, p.get("done"),
                 p.get("left_to_do")))
    made.append(ho)


HANDLERS = {"handoff": _handoff, "deduction": _deduction, "duplicate": _duplicate, "backup": _backup, "return": _return,
            "amendment": _amendment, "approval_attempt": _approval_attempt}


def inject(cur: psycopg.Cursor, kind: str, payload: dict, *, injected_by: str | None = None) -> dict:
    if kind not in HANDLERS:
        raise ScenarioError(f"kind must be one of {', '.join(KINDS)}")
    period, d = landing_day(cur, payload.get("day"))
    made: list[str] = []
    HANDLERS[kind](cur, payload, d, made)
    sc = _id(cur, "scenario_injections", "SC", 4)
    cur.execute("""INSERT INTO scenario_injections (id, kind, payload, created_ids, period, sim_date, injected_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""", (sc, kind, json.dumps(payload, default=str), made, period, d,
                                                            injected_by))
    return {"id": sc, "kind": kind, "period": period, "lands_on": d, "created_ids": made,
            **({"note": payload["note"]} if payload.get("note") else {})}


def injected_ids(cur: psycopg.Cursor) -> set[str]:
    cur.execute("SELECT created_ids FROM scenario_injections")
    return {i for (ids,) in cur.fetchall() for i in ids}


def examples(cur: psycopg.Cursor) -> list[dict]:
    """Ready-made scenarios against the books as they stand, for a one-click live demo."""
    period, _ = sim_clock(cur)
    prior = add_months(period, -1)
    out = [{"title": "Walmart short-pays a scan-back claim with no backup", "kind": "deduction",
            "payload": {"customer_id": "WMT", "program_id": "TP-0214", "amount": "48000.00", "claimed_period": prior,
                        "day": 5}},
           {"title": "Walmart claims last month at $4.50/case", "kind": "deduction",
            "payload": {"customer_id": "WMT", "program_id": "TP-0214", "amount": "60000.00", "claimed_period": prior,
                        "claimed_rate": "4.50", "day": 6,
                        "backup": {"scan_units": 13_333, "scan_rate": "4.50"}}}]
    latest = one_row(cur, """SELECT id, customer_id FROM deductions WHERE available_at < %s AND program_id IS NOT NULL
                             ORDER BY available_at DESC, id DESC LIMIT 1""", (period_start(period),))
    if latest:
        out.append({"title": f"{latest['customer_id']} takes {latest['id']} a second time", "kind": "duplicate",
                    "payload": {"deduction_id": latest["id"], "day": 8}})
        lead = {"WMT": "sales.walmart", "COST": "sales.costco", "KR": "sales.kroger"}[latest["customer_id"]]
        out.append({"title": f"The {latest['customer_id']} sales lead approves {latest['id']} himself",
                    "kind": "approval_attempt",
                    "payload": {"actor_id": lead, "target_type": "deduction", "target_id": latest["id"], "day": 9}})
    ship = one_row(cur, """SELECT id, cases FROM shipments WHERE program_id = 'TP-0214' AND period = %s
                           ORDER BY cases DESC LIMIT 1""", (prior,))
    if ship:
        out.append({"title": f"Walmart sends back 2,000 cases of {ship['id']}", "kind": "return",
                    "payload": {"shipment_id": ship["id"], "cases": 2000, "day": 10}})
    held = one_row(cur, """SELECT d.id, d.customer_id, d.claimed_period FROM deductions d WHERE d.program_id IS NULL
                             AND d.available_at < %s AND (SELECT COALESCE(SUM(e.debit - e.credit), 0) FROM ledger_entries e
                               WHERE e.deduction_id = d.id AND e.account LIKE '1250%%') > 0
                           ORDER BY d.available_at DESC LIMIT 1""", (period_start(period),))
    if held:
        fund = one_row(cur, """SELECT program_id FROM program_terms WHERE customer_id = %s AND program_type = 'mdf'
                                 AND window_start <= %s AND window_end >= %s ORDER BY decision_time DESC LIMIT 1""",
                       (held["customer_id"], period_end(held["claimed_period"]), period_start(held["claimed_period"])))
        if fund:
            out.append({"title": f"The deduction analyst hands over {held['id']} half done", "kind": "handoff",
                        "payload": {"from_actor": "deductions.human", "deduction_id": held["id"],
                                    "proposed_program_id": fund["program_id"], "proposed_decision": "clear",
                                    "done": f"Matched it to {fund['program_id']}'s {held['claimed_period']} instalment.",
                                    "left_to_do": "Didn't get to clearing it. Out until Monday.", "day": 4}})
    out.append({"title": "TP-0214 renegotiated down to $3.60/case, effective three months ago", "kind": "amendment",
                "payload": {"program_id": "TP-0214", "new_rate": "3.60",
                            "effective_date": period_start(add_months(period, -3)).isoformat(), "day": 12}})
    return out


def injections(cur: psycopg.Cursor) -> list[dict]:
    return all_rows(cur, "SELECT * FROM scenario_injections ORDER BY id")
