"""Segregation of duties: a capability check in code that throws, not a prompt instruction.

`can_approve` raises when the actor negotiated the program the target arises from, and when the
actor is the agent itself. Every approval path calls it first: answering an escalation, applying
a restatement, a scripted human action. A blocked attempt is recorded as a finding with
escalation_type 'sod' so the attempt itself is on the record, and the approval stays with the
controller.
"""

import json
from datetime import datetime
from decimal import Decimal

import psycopg

from tpa.constants import Control as C, period_of
from tpa.controls import Hit
from tpa.execute import _jsonable, raise_finding
from tpa.rows import all_rows, one_row

SOD_CONTROL = {
    "id": C.SOD, "name": "Approver negotiated the program the claim arises from",
    "condition": "approver.id = program.negotiated_by OR approver.role = 'agent'",
    "threshold": Decimal("0"), "threshold_unit": "usd", "owner_role": "controller",
}


class SegregationOfDutiesError(PermissionError):
    def __init__(self, message: str, *, actor: dict, program: dict | None, target_type: str, target_id: str):
        super().__init__(message)
        self.actor, self.program, self.target_type, self.target_id = actor, program, target_type, target_id


def actor(cur: psycopg.Cursor, actor_id: str) -> dict:
    row = one_row(cur, "SELECT * FROM actors WHERE id = %s", (actor_id,))
    if row is None:
        raise PermissionError(f"unknown actor {actor_id!r}")
    return row


def program_of(cur: psycopg.Cursor, target_type: str, target_id: str) -> dict | None:
    """The trade program an approval target arises from."""
    if target_type == "deduction":
        row = one_row(cur, "SELECT program_id FROM deductions WHERE id = %s", (target_id,))
        program_id = row and row["program_id"]
        if program_id is None:
            hit = one_row(cur, """SELECT evidence ->> 'program_id' AS program_id FROM findings
                                  WHERE evidence -> 'deduction_ids' ? %s AND evidence ->> 'program_id' IS NOT NULL
                                  ORDER BY id LIMIT 1""", (target_id,))
            program_id = hit and hit["program_id"]
    elif target_type == "restatement":
        row = one_row(cur, "SELECT program_id FROM program_amendments WHERE id = %s", (target_id,)) or \
            one_row(cur, "SELECT evidence ->> 'program_id' AS program_id FROM findings WHERE id = %s", (target_id,))
        program_id = row and row["program_id"]
    elif target_type == "finding":
        row = one_row(cur, "SELECT evidence ->> 'program_id' AS program_id FROM findings WHERE id = %s", (target_id,))
        program_id = row and row["program_id"]
    else:
        raise ValueError(f"unknown approval target {target_type!r}")
    if not program_id:
        return None
    return one_row(cur, """SELECT p.*, c.name AS customer FROM trade_programs p JOIN customers c ON c.id = p.customer_id
                           WHERE p.id = %s""", (program_id,))


def can_approve(cur: psycopg.Cursor, actor_id: str, target_type: str, target_id: str) -> None:
    a = actor(cur, actor_id)
    program = program_of(cur, target_type, target_id)
    if a["role"] == "agent":
        raise SegregationOfDutiesError(f"The agent cannot approve {target_id}; it never approves its own conclusions.",
                                       actor=a, program=program, target_type=target_type, target_id=target_id)
    if program and program["negotiated_by"] == a["id"]:
        raise SegregationOfDutiesError(
            f"{a['name']} negotiated {program['id']} for {program['customer']}; approval routed to controller.",
            actor=a, program=program, target_type=target_type, target_id=target_id)


def ensure_control(cur: psycopg.Cursor, at: datetime) -> dict:
    cur.execute(
        """INSERT INTO controls (id, name, condition, threshold, threshold_unit, owner_role, precedent_ids,
                                 mined_at, learned, status)
           VALUES (%(id)s, %(name)s, %(condition)s, %(threshold)s, %(threshold_unit)s, %(owner_role)s, '{}',
                   %(at)s, FALSE, 'active') ON CONFLICT (id) DO NOTHING""",
        {**SOD_CONTROL, "at": at},
    )
    return one_row(cur, "SELECT * FROM controls WHERE id = %s", (C.SOD,))


def related_findings(cur: psycopg.Cursor, target_type: str, target_id: str) -> list[str]:
    if target_type == "deduction":
        rows = all_rows(cur, "SELECT id FROM findings WHERE evidence -> 'deduction_ids' ? %s ORDER BY id", (target_id,))
    elif target_type == "restatement":
        rows = all_rows(cur, "SELECT id FROM findings WHERE id = %s OR evidence ->> 'amendment_id' = %s ORDER BY id",
                        (target_id, target_id))
    else:
        rows = [{"id": target_id}]
    return [r["id"] for r in rows if r["id"]]


def target_amount(cur: psycopg.Cursor, target_type: str, target_id: str, related: list[str]) -> Decimal | None:
    if target_type == "deduction":
        row = one_row(cur, "SELECT amount FROM deductions WHERE id = %s", (target_id,))
        return row and row["amount"]
    row = one_row(cur, "SELECT amount FROM findings WHERE id = ANY(%s) AND amount IS NOT NULL ORDER BY id LIMIT 1",
                  (related,))
    return row and row["amount"]


def record_block(cur: psycopg.Cursor, err: SegregationOfDutiesError, at: datetime, *,
                 event_id: str | None = None) -> str:
    """The blocked attempt as a finding: resolved (nothing to decide, the block is the outcome),
    escalation_type 'sod', evidence naming the actor, the program and what they tried to approve."""
    control = ensure_control(cur, at)
    related = related_findings(cur, err.target_type, err.target_id)
    amount = target_amount(cur, err.target_type, err.target_id, related)
    program = err.program
    summary = f"{err} Blocked {at:%Y-%m-%d %H:%M}; nothing was posted."
    hit = Hit(C.SOD, "self_approval", None, amount, amount, summary, {
        "event_id": event_id, "actor_id": err.actor["id"], "actor_role": err.actor["role"],
        "target_type": err.target_type, "target_id": err.target_id,
        "program_id": program and program["id"], "negotiated_by": program and program["negotiated_by"],
        "routed_to": "controller", "blocked_finding_ids": related,
        "deduction_ids": [err.target_id] if err.target_type == "deduction" else [],
        "amendment_id": err.target_id if err.target_type == "restatement" else None,
    })
    customer_id = program["customer_id"] if program else err.actor["customer_id"]
    fid = raise_finding(cur, hit, period=period_of(at.date()), customer_id=customer_id, at=at, control=control)
    cur.execute(
        """UPDATE findings SET state = 'resolved', escalation_type = 'sod',
                  evidence = evidence || jsonb_build_object('resolution', %s::jsonb) WHERE id = %s""",
        (json.dumps({"decision": "blocked", "by": "agent", "at": at, "note": str(err)}, default=_jsonable), fid),
    )
    return fid
