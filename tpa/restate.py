"""Restatement — a control that fires on the system's own prior conclusions.

Event-driven. When an amendment lands whose valid time reaches back into periods already
accrued, those accruals were right on what we knew and are wrong on what we know now:

1. Re-derive the terms as of the amendment's valid time (program_terms is bitemporal)
2. Re-evaluate each accrued period: the same volume, the terms its accrual was made on
   versus the terms we hold now
3. Propose one catch-up (or clawback) per period, restating that period's own accrual lines
4. Raise it for the controller; post only once approved (`hooks.approve`, or C later via `apply`)
5. Release the claims we held because they disagreed with the old terms

Both reasonings stay on the ledger. The original accrual's memo says what it was based on
and when; the catch-up's memo says what changed, when it was true, and when we learned it.
`balances_as_of(period, before)` and `balances_as_of(period, after)` are the two answers.
"""

import json
from datetime import datetime
from decimal import Decimal

import psycopg

from tpa.accrual import ZERO, rate, restatement_delta
from tpa.asof import terms_as_of
from tpa.constants import Control as C, period_end, period_of
from tpa.controls import Hit
from tpa.execute import (
    _jsonable, accrual_key, authorise, controls, finding, original_accrual, raise_finding, set_finding_state,
    withdraw_dispute,
)
from tpa.ledger import post_catch_up
from tpa.rows import all_rows, one_row


def propose(cur: psycopg.Cursor, amendment: dict, at: datetime) -> list[dict]:
    """One item per accrued period the amendment reaches back into, with its catch-up."""
    program_id = amendment["program_id"]
    origins = [r["period"] for r in all_rows(
        cur,
        """SELECT DISTINCT period FROM ledger_entries
           WHERE entry_type = 'accrual' AND program_id = %s AND valid_time >= %s
             AND to_char(valid_time, 'YYYY-MM') = period
           ORDER BY period""",
        (program_id, period_end(period_of(amendment["effective_date"]))),
    )]
    items = []
    for origin in origins:
        orig = original_accrual(cur, program_id, origin)
        basis = orig["decision_time"]
        shipments = all_rows(cur, "SELECT * FROM shipments WHERE program_id = %s AND period = %s AND available_at <= %s",
                             (program_id, origin, at.date()))
        cur.execute("SELECT shipment_id, SUM(cases) FROM returns WHERE shipment_id = ANY(%s) AND available_at <= %s "
                    "GROUP BY shipment_id", ([s["id"] for s in shipments], at.date()))
        returned = dict(cur.fetchall())
        old_for = lambda on, b=basis: terms_as_of(cur, program_id, on, b)
        new_for = lambda on: terms_as_of(cur, program_id, on, at)
        projected = new_for(period_end(origin))["projected_redemption"]
        delta = restatement_delta(shipments, returned, projected, old_for, new_for)
        if delta == 0:
            continue
        changed = [s for s in shipments if old_for(s["ship_date"])["rate"] != new_for(s["ship_date"])["rate"]]
        net = sum(s["cases"] - returned.get(s["id"], 0) for s in changed)
        old_rate, new_rate = old_for(changed[0]["ship_date"])["rate"], new_for(changed[0]["ship_date"])["rate"]
        state = one_row(cur, "SELECT state, signed_by, signed_at FROM periods WHERE period = %s AND customer_id = %s",
                        (origin, orig["liability"]["customer_id"]))
        items.append({
            "origin": origin, "journal_id": orig["journal_id"],
            "expense_line": orig["expense"]["id"], "liability_line": orig["liability"]["id"],
            "original_amount": orig["liability"]["credit"], "original_known_at": basis,
            "net_cases_changed": net, "first_changed_ship_date": min(s["ship_date"] for s in changed),
            "old_rate": old_rate, "new_rate": new_rate, "projected_redemption": projected,
            "catch_up": delta, "period_state": state["state"], "signed_by": state["signed_by"],
        })
    return items


def held_claims(cur: psycopg.Cursor, program_id: str, rate: Decimal | None = None) -> list[str]:
    """Deductions on this program still held by a claimed-rate conflict."""
    rows = all_rows(
        cur,
        """SELECT DISTINCT jsonb_array_elements_text(evidence -> 'deduction_ids') AS id FROM findings
           WHERE control_id = %s AND conflict_type = 'claimed_rate' AND state IN ('open', 'escalated')
             AND evidence ->> 'program_id' = %s
             AND (%s::text IS NULL OR evidence ->> 'claimed_rate' = %s)""",
        (C.RATE_CONFLICT, program_id, str(rate) if rate else None, str(rate) if rate else None),
    )
    return sorted(r["id"] for r in rows)


def on_amendment(cur: psycopg.Cursor, amendment: dict, period: str, at: datetime, approve) -> str | None:
    """The trigger. Returns the finding that carries the restatement, or None if nothing changed."""
    items = propose(cur, amendment, at)
    if not items:
        return None
    program = one_row(cur, "SELECT p.*, c.name AS customer FROM trade_programs p JOIN customers c "
                           "ON c.id = p.customer_id WHERE p.id = %s", (amendment["program_id"],))
    total = sum((i["catch_up"] for i in items), ZERO)
    first, last = items[0]["origin"], items[-1]["origin"]
    signed = [i["origin"] for i in items if i["signed_by"]]
    word = "Under" if total > 0 else "Over"
    summary = (f"{word}-accrued trade promotion liability, {program['customer']}: ${abs(total):,} across "
               f"{len(items)} periods ({first} to {last}). {amendment['id']} changed {program['id']}'s rate from "
               f"${rate(items[0]['old_rate'])} to ${rate(items[0]['new_rate'])}/case effective {amendment['effective_date']} "
               f"but reached us only on {amendment['available_at']}, so every accrual since then was booked "
               f"{'low' if total > 0 else 'high'}. {len(signed)} of those periods are signed; restating them "
               f"needs the controller.")
    hit = Hit(C.DED_GT_ACCRUAL, "amendment_not_applied", None, total, abs(total), summary, {
        "amendment_id": amendment["id"], "program_id": program["id"], "negotiated_by": program["negotiated_by"],
        "effective_date": amendment["effective_date"], "entered_on": amendment["available_at"],
        "periods": items, "journal_ids": [i["journal_id"] for i in items],
        "accrual_keys": [accrual_key(program["id"], i["origin"]) for i in items],
        "deduction_ids": held_claims(cur, program["id"]),
    })
    lib = controls(cur)
    finding_id = raise_finding(cur, hit, period=period, customer_id=program["customer_id"], at=at,
                               control=lib[C.DED_GT_ACCRUAL])
    cur.execute("UPDATE findings SET state = 'escalated', escalation_type = 'authority' WHERE id = %s", (finding_id,))
    approver = approve(cur, finding(cur, finding_id), at)
    if approver:
        apply(cur, finding_id, approver, at, period=period)
    return finding_id


def apply(cur: psycopg.Cursor, finding_id: str, approved_by: str, at: datetime, *, period: str) -> dict:
    """Post the approved catch-ups and release the claims the old terms were holding.

    The caller has already checked `approved_by` may approve (segregation of duties is C's
    capability layer); this refuses only the agent itself.
    """
    if approved_by == "agent":
        raise PermissionError("the agent never approves its own restatement")
    f = finding(cur, finding_id)
    ev = f["evidence"]
    journals = []
    for item in ev["periods"]:
        delta = Decimal(item["catch_up"])
        memo = (f"{'Catch-up' if delta > 0 else 'Clawback'} restating {item['journal_id']}: {ev['amendment_id']} "
                f"(effective {ev['effective_date']}, entered {ev['entered_on']}) moved {ev['program_id']} from "
                f"${rate(item['old_rate'])} to ${rate(item['new_rate'])}/case. {int(item['net_cases_changed']):,} net cases "
                f"shipped from {item['first_changed_ship_date']} × {rate(item['projected_redemption'])} × "
                f"${rate(Decimal(item['new_rate']) - Decimal(item['old_rate']))} = ${delta:,}. The original accrual was "
                f"right on the terms known {item['original_known_at'][:10]}.")
        journals.append(post_catch_up(cur, expense_line=item["expense_line"], liability_line=item["liability_line"],
                                      delta=delta, decision_time=at, approved_by=approved_by,
                                      source_finding_id=finding_id, memo=memo))
    set_finding_state(cur, finding_id, "resolved",
                      {"decision": "restate", "by": approved_by, "at": at, "journals": journals})
    released = release_held(cur, ev["program_id"], period, at, cause=ev["amendment_id"])
    cur.execute("UPDATE findings SET evidence = evidence || %s::jsonb WHERE id = %s",
                (json.dumps({"restatement_journals": journals, "released_deduction_ids": released["cleared"]},
                            default=_jsonable), finding_id))
    return {"journals": journals, **released}


def release_held(cur: psycopg.Cursor, program_id: str, period: str, at: datetime, *, cause: str) -> dict:
    """Re-check every rate conflict on the program against the terms we now hold. Where the
    customer's rate turned out to be right, resolve the conflict and clear the claims — and
    where we already disputed the difference on the old terms, withdraw our own dispute first."""
    cleared, over, withdrawn = [], [], []
    for f in all_rows(cur, """SELECT * FROM findings WHERE control_id = %s AND conflict_type = 'claimed_rate'
                                AND evidence ->> 'program_id' = %s
                                AND (state IN ('open', 'escalated')
                                     OR evidence -> 'resolution' ->> 'decision' = 'dispute_difference')
                              ORDER BY id""",
                      (C.RATE_CONFLICT, program_id)):
        deds = all_rows(cur, "SELECT * FROM deductions WHERE id = ANY(%s) ORDER BY available_at, id",
                        (f["evidence"]["deduction_ids"],))
        if not all(terms_as_of(cur, program_id, d["claim_start"] or period_end(d["claimed_period"]), at)["rate"]
                   == d["claimed_rate"] for d in deds):
            continue
        prior = (f["evidence"] or {}).get("resolution")
        for d in deds:
            j = withdraw_dispute(cur, d, program_id, period, at, finding_id=f["id"],
                                 memo=f"Withdraw our dispute on {d['id']}: {cause} confirms the customer's "
                                      f"${rate(d['claimed_rate'])}/case. The dispute was right on the terms we held when "
                                      f"{prior['by'] if prior else 'we'} answered.")
            if j:
                withdrawn.append(d["id"])
            (over if authorise(cur, d, program_id, period, at, finding_id=f["id"]) else cleared).append(d["id"])
        set_finding_state(cur, f["id"], "resolved",
                          {"decision": "superseded", "by": "agent", "at": at,
                           "note": f"{cause} confirms the customer's rate", "previous": prior,
                           "withdrawn_disputes": [x for x in withdrawn if x in f["evidence"]["deduction_ids"]]})
    return {"cleared": cleared, "over_claimed": over, "withdrawn_disputes": withdrawn}
