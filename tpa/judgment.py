"""The judgment engine: every finding passes through the same gate.

    finding
      └─ mechanical control (duplicates, no proof, late returns)?  → the agent disputes / re-estimates
      └─ match precedent(control_id, conflict key, customer_id)?
           ├─ HIT  → apply the stored decision, log it, continue silently
           └─ MISS → classify the escalation
                       ├─ source conflict → customer team analyst: "Which is the source of truth?"
                       ├─ low confidence  → controller, the ambiguity quoted
                       └─ authority       → the control's mined owner (restatements: controller)
                     → a human answers (`answer`) → precedent row → the next match passes silently

Segregation of duties is checked on every answer (`tpa.sod.can_approve`); a blocked attempt is
its own finding, escalation_type 'sod'. Postings go through `tpa.execute` and `tpa.restate`; this
module decides who decides, never how much.

Policy, not GAAP: LOW_CONFIDENCE (tpa.policy) and which conflicts count as source-of-truth
questions (here) are company choices.
"""

import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from functools import partial

import psycopg

from tpa import model, restate
from tpa.autopilot import PRECEDENT_ANSWERS
from tpa.constants import Control as C, Prefix, period_of
from tpa.cycle import MECHANICAL, Hooks, default_judge
from tpa.execute import _jsonable, execute, finding, next_id, set_finding_state
from tpa.policy import LOW_CONFIDENCE
from tpa.rows import all_rows, one_row
from tpa.sod import SegregationOfDutiesError, actor, can_approve, record_block

# Policy: conflicts where two sources disagree and a person must say which one wins.
SOURCE_CONFLICTS = {"claimed_rate", "terms_reading"}
# Decisions that post on the decider's own authority. A precedent applies them silently only
# up to the exposure the human decided on; anything larger asks again.
AUTHORITY_DECISIONS = {"top_up_and_clear", "release_accrual", "apply_candidates", "clear", "approve"}
# Answers that decide nothing for next time.
NOT_PRECEDENT = {"hold", "escalate"}
RESTATEMENT = "amendment_not_applied"

Respond = Callable[[psycopg.Cursor, dict, datetime], None]


# ── options: what each card offers, and the decision each option executes ───
def _o(option_id: str, label: str, decision: str) -> dict:
    return {"id": option_id, "label": label, "decision": decision}


HOLD = _o("hold", "Hold until more evidence arrives", "hold")
TO_CONTROLLER = _o("escalate", "Escalate to controller", "escalate")
OPTIONS = {
    (C.RATE_CONFLICT, "claimed_rate"): [_o("program", "Program as signed", "dispute_difference"),
                                        _o("customer", "Customer's claimed rate", "clear"), HOLD, TO_CONTROLLER],
    (C.RATE_CONFLICT, "terms_reading"): [_o("program", "Our reading of the program", "dispute"),
                                         _o("customer", "The customer's reading", "clear"), HOLD, TO_CONTROLLER],
    (C.DED_GT_ACCRUAL, RESTATEMENT): [_o("approve", "Approve the restatement", "approve"),
                                      _o("reject", "Reject: leave the closed periods as booked", "reject"), HOLD],
    (C.DED_GT_ACCRUAL, "over_claim"): [_o("top_up", "Top up the accrual and clear", "top_up_and_clear"),
                                       _o("dispute", "Dispute the claim", "dispute"), HOLD],
    (C.SCAN_NO_BACKUP, None): [_o("dispute", "Dispute until scan data arrives", "dispute"),
                               _o("clear", "Clear without backup", "clear"), HOLD],
    (C.OUTSIDE_WINDOW, None): [_o("dispute", "Dispute: outside the program window", "dispute"),
                               _o("clear", "Clear as an exception", "clear"), HOLD],
    (C.PERIOD_STRADDLE, None): [_o("allocate", "Allocate across periods by activity days", "allocate"),
                                _o("dispute", "Dispute: ask the customer to split the claim", "dispute"), HOLD],
    (C.CLAIM_VS_BACKUP, None): [_o("backup", "Backup as the source: dispute the difference", "dispute_difference"),
                                _o("claim", "Clear the claim as taken", "clear"), HOLD],
    (C.STALE_ACCRUAL, None): [_o("release", "Release the accrual", "release_accrual"),
                              _o("keep", "Keep it: claims are still expected", "hold")],
    (C.REDEMPTION_DRIFT, None): [_o("acknowledge", "Acknowledge; re-estimate at the next close", "acknowledge"), HOLD],
}
DEFAULT_OPTIONS = [_o("clear", "Clear", "clear"), _o("dispute", "Dispute", "dispute"), HOLD]


APPLY_CANDIDATES = _o("apply", "Apply the unmatched deductions named here, release the rest", "apply_candidates")


# Where last year has no answer, what the agent recommends and why.
WITHOUT_HISTORY = {
    (C.RATE_CONFLICT, "terms_reading"): ("customer", "The clause is ambiguous and we drafted it, so it reads the "
                                                     "customer's way. Tighten the wording at renewal."),
    (C.DED_GT_ACCRUAL, RESTATEMENT): ("approve", "The amendment was signed and is in force from its effective date; "
                                                 "the closed periods were booked on terms we now know were superseded."),
    (C.REDEMPTION_DRIFT, None): ("acknowledge", "Real sell-through is running above projection; take it into the "
                                                "next estimate."),
}


def recommend(f: dict, options: list[dict], precedent: dict | None = None) -> tuple[str, str]:
    """(option_id, basis): what the agent would do, for a person to confirm or overrule.
    This year's answer on the same key first, then last year's handling, then policy."""
    by_decision = {o["decision"]: o for o in options}
    if precedent and precedent["decision"] in by_decision:
        return by_decision[precedent["decision"]]["id"], (
            f"As {precedent['decided_by']} decided in {precedent['id']}: {precedent['reasoning']}")
    if "apply_candidates" in by_decision:
        # Rule 03: never release an accrual while a claim that may settle it sits unapplied.
        return by_decision["apply_candidates"]["id"], ("The unmatched deduction is this accrual's claim: same customer, "
                                                       "same period, close to the instalment.")
    prior = PRECEDENT_ANSWERS.get((f["control_id"], f["conflict_type"])) or PRECEDENT_ANSWERS.get((f["control_id"], None))
    if prior and prior[1] in by_decision:
        taught = ((f["evidence"] or {}).get("control") or {}).get("precedent_ids", [])
        cited = ", ".join(taught[:3]) + ("…" if len(taught) > 3 else "")
        option = by_decision[prior[1]]
        return option["id"], (f"Last year {len(taught)} cases{f' ({cited})' if cited else ''} were resolved this way: "
                              f"{option['label'].lower()}.")
    choice = WITHOUT_HISTORY.get((f["control_id"], f["conflict_type"])) or WITHOUT_HISTORY.get((f["control_id"], None))
    if choice and any(o["id"] == choice[0] for o in options):
        return choice
    hold = by_decision.get("hold") or options[-1]
    return hold["id"], "Not enough to decide on; I'd hold for more evidence."


def options_for(f: dict) -> list[dict]:
    options = OPTIONS.get((f["control_id"], f["conflict_type"])) or OPTIONS.get((f["control_id"], None)) \
        or DEFAULT_OPTIONS
    if f["control_id"] == C.STALE_ACCRUAL and (f["evidence"] or {}).get("candidate_deduction_ids"):
        return [APPLY_CANDIDATES, *options]
    return options


# ── precedents ──────────────────────────────────────────────────────────────
def conflict_key(f: dict) -> str:
    """The precedent match key alongside control and customer. Specific enough that an answer
    about one clause, rate pair or amendment never silently decides another."""
    ev, ct = f["evidence"] or {}, f["conflict_type"] or "-"
    if ct == "terms_reading":
        return f"{ct}:{ev.get('source_clause_id')}"
    if ct == "claimed_rate":
        return f"{ct}:{ev.get('claimed_rate')}/{ev.get('program_rate')}"
    if ct == RESTATEMENT:
        return f"{ct}:{ev.get('amendment_id')}"
    return ct


def find_precedent(cur: psycopg.Cursor, f: dict) -> dict | None:
    """The latest decision on the key. Its standing limit is the largest exposure anyone has
    decided the same way on that key, so a smaller later case doesn't shrink it."""
    return one_row(cur, """SELECT p.*, (SELECT MAX(q.exposure_limit) FROM precedents q
                                        WHERE (q.control_id, q.conflict_type, q.customer_id, q.decision)
                                            = (p.control_id, p.conflict_type, p.customer_id, p.decision)) AS standing_limit
                           FROM precedents p WHERE p.control_id = %s AND p.conflict_type = %s AND p.customer_id = %s
                           ORDER BY p.decided_at DESC, p.id DESC LIMIT 1""",
                   (f["control_id"], conflict_key(f), f["customer_id"]))


def covers(precedent: dict, f: dict) -> bool:
    limit = precedent.get("standing_limit", precedent["exposure_limit"])
    if precedent["decision"] not in AUTHORITY_DECISIONS or limit is None:
        return True
    return (f["exposure"] or Decimal("0")) <= limit


def write_precedent(cur: psycopg.Cursor, f: dict, decision: str, reasoning: str, decided_by: str, at: datetime,
                    escalation_id: str | None, overrode: str | None = None) -> str:
    pid = next_id(cur, "precedents", Prefix.PRECEDENT)
    cur.execute(
        """INSERT INTO precedents (id, control_id, conflict_type, customer_id, decision, reasoning, decided_by,
                                   decided_at, exposure_limit, overrode, from_escalation_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (pid, f["control_id"], conflict_key(f), f["customer_id"], decision, reasoning, decided_by, at,
         f["exposure"] if decision in AUTHORITY_DECISIONS else None, overrode, escalation_id),
    )
    return pid


def _note(cur: psycopg.Cursor, finding_id: str, **fields) -> None:
    cur.execute("UPDATE findings SET evidence = evidence || %s::jsonb WHERE id = %s",
                (json.dumps(fields, default=_jsonable), finding_id))


def decide(cur: psycopg.Cursor, f: dict, decision: str, decided_by: str, at: datetime, note: str) -> list[str]:
    """Carry out a decision. Restatements post through `restate.apply`; everything else through `execute`."""
    if decision == "approve":
        return restate.apply(cur, f["id"], decided_by, at, period=period_of(at.date()))["journals"]
    if decision == "reject":
        set_finding_state(cur, f["id"], "resolved", {"decision": "reject", "by": decided_by, "at": at, "note": note})
        return []
    return execute(cur, f["id"], decision, decided_by, at, note=note)


def apply_precedent(cur: psycopg.Cursor, f: dict, p: dict, at: datetime) -> list[str]:
    """A HIT: decide as the human did, cite them, and stay silent. A disputing decision is the
    agent's to make; one that posts on authority runs on the precedent's standing approval."""
    by = p["decided_by"] if p["decision"] in AUTHORITY_DECISIONS else "agent"
    can_approve(cur, p["decided_by"], "finding", f["id"])
    _note(cur, f["id"], precedent_id=p["id"])
    return decide(cur, f, p["decision"], by, at,
                  note=f"precedent {p['id']} ({p['decided_by']}, {p['decided_at']:%Y-%m-%d}): {p['reasoning']}")


# ── escalation ──────────────────────────────────────────────────────────────
def classify(f: dict) -> tuple[str, str]:
    """(escalation_type, to_role)."""
    if f["conflict_type"] == RESTATEMENT:
        return "authority", "controller"
    if f["conflict_type"] in SOURCE_CONFLICTS:
        return "source_conflict", "customer_team_analyst"
    if f["confidence"] is not None and f["confidence"] < LOW_CONFIDENCE:
        return "low_confidence", "controller"
    owner = ((f["evidence"] or {}).get("control") or {}).get("owner_role") or "controller"
    return "authority", owner


QUESTIONS = {
    "source_conflict": "Which is the source of truth?",
    "low_confidence": "I can't verify this from the agreement (confidence {confidence:.0%}). How should it be resolved?",
    "authority": "This needs your authority: {control} at ${exposure:,} against a mined threshold of {threshold}. "
                 "How should it be resolved?",
}


def draft_question(f: dict, kind: str) -> str:
    """The card's text: the finding's own summary, then the question for its lane. The model may
    rewrite the prose; a rewrite that changes any number or record id is thrown away."""
    ev = f["evidence"] or {}
    lede = ev.get("summary", "").strip()
    control = ev.get("control") or {}
    unit = control.get("threshold_unit")
    threshold = control.get("threshold")
    threshold = "any" if threshold in (None, "0", 0) else f"${Decimal(str(threshold)):,}" if unit == "usd" else \
        f"{threshold}{'%' if unit == 'pct' else ' periods'}"
    question = QUESTIONS[kind].format(confidence=f["confidence"] or 0, control=control.get("name", f["control_id"]),
                                      exposure=f["exposure"] or Decimal("0"), threshold=threshold)
    text = lede if lede.endswith(question) else f"{lede} {question}".strip()
    rewrite = model.ask(
        "You write escalation cards for a trade promotion accountant. Rewrite the card so a busy finance "
        "person understands it in ten seconds. Keep every number, dollar amount and record id exactly as "
        "written. Do not add facts. End with the question. Return only the card text.", text, max_tokens=300)
    return rewrite if rewrite and model.keeps_facts(text, rewrite) else text


def escalate(cur: psycopg.Cursor, f: dict, at: datetime, *, to_role: str | None = None,
             prefix: str = "", precedent: dict | None = None) -> dict:
    kind, role = classify(f)
    role = to_role or role
    eid = next_id(cur, "escalations", Prefix.ESCALATION)
    options = [o for o in options_for(f) if not (o["decision"] == "escalate" and role == "controller")]
    rec, basis = recommend(f, options, precedent)
    options = [{**o, "recommended": o["id"] == rec} for o in options]
    label = next(o["label"] for o in options if o["id"] == rec)
    question = f"{(prefix + draft_question(f, kind)).strip()} I'd recommend: {label.lower()}. {basis}"
    cur.execute(
        """INSERT INTO escalations (id, finding_id, to_role, question, options, recommended, recommendation_basis,
                                    created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (eid, f["id"], role, question, json.dumps(options), rec, basis, at),
    )
    cur.execute("UPDATE findings SET state = 'escalated', escalation_type = %s WHERE id = %s", (kind, f["id"]))
    return escalation(cur, eid)


def escalation(cur: psycopg.Cursor, escalation_id: str) -> dict:
    row = one_row(cur, "SELECT * FROM escalations WHERE id = %s", (escalation_id,))
    if row is None:
        raise KeyError(escalation_id)
    return row


def open_escalations(cur: psycopg.Cursor, to_role: str | None = None) -> list[dict]:
    return all_rows(cur, """SELECT e.*, f.customer_id, f.control_id, f.evidence FROM escalations e
                            JOIN findings f ON f.id = e.finding_id
                            WHERE e.answered_at IS NULL AND (%s::text IS NULL OR e.to_role = %s) ORDER BY e.id""",
                    (to_role, to_role))


# ── the gate ────────────────────────────────────────────────────────────────
def judge(cur: psycopg.Cursor, f: dict, at: datetime, *, respond: Respond | None = None) -> None:
    """The judge hook: called as each finding is raised, and at close for any still open."""
    if f["state"] != "open":
        return
    if f["control_id"] in MECHANICAL:
        default_judge(cur, f, at)
        return
    p = find_precedent(cur, f)
    if p and covers(p, f):
        apply_precedent(cur, f, p, at)
        return
    prefix = (f"Precedent {p['id']} ({p['decision']}) covers up to ${p['standing_limit']:,}; "
              f"this one is ${f['exposure']:,}. ") if p else ""
    esc = escalate(cur, f, at, prefix=prefix, precedent=p)
    if respond:
        respond(cur, esc, at)


def request_approval(cur: psycopg.Cursor, f: dict, at: datetime, *, respond: Respond | None = None) -> None:
    """The approve hook for restatements: always a controller's call, so it goes to the inbox.
    Returns None so the engine waits; the answer posts it through `restate.apply`."""
    esc = escalate(cur, finding(cur, f["id"]), at)
    if respond:
        respond(cur, esc, at)
    return None


# ── the human's side ────────────────────────────────────────────────────────
def answer(cur: psycopg.Cursor, escalation_id: str, option_id: str, answered_by: str, at: datetime, *,
           reasoning: str) -> dict:
    """A human answers a card. Checks who may answer, executes, writes the precedent, and lets the
    precedent settle any other open card it now governs. Rejections must carry reasoning."""
    esc = escalation(cur, escalation_id)
    if esc["answered_at"] is not None:
        raise ValueError(f"{escalation_id} was already answered by {esc['answered_by']}")
    f = finding(cur, esc["finding_id"])
    option = next((o for o in esc["options"] if o["id"] == option_id), None)
    if option is None:
        raise ValueError(f"{option_id!r} is not an option on {escalation_id}")
    if not reasoning.strip():
        raise ValueError("an answer carries its reasoning; it becomes the precedent")
    overrode = esc["recommended"] if esc["recommended"] and option_id != esc["recommended"] else None
    if overrode and reasoning.strip() == option["label"]:
        rec = next(o["label"] for o in esc["options"] if o["id"] == overrode)
        raise ValueError(f"Overruling the recommendation ({rec.lower()}) needs your reasoning: "
                         f"it becomes the precedent the next case follows")
    who = actor(cur, answered_by)
    if who["role"] != esc["to_role"] and who["role"] != "controller":
        raise PermissionError(f"{who['name']} cannot answer a card addressed to the {esc['to_role']}")
    if who["customer_id"] and who["customer_id"] != f["customer_id"]:
        raise PermissionError(f"{who['name']} answers for {who['customer_id']}, not {f['customer_id']}")
    target = ("restatement", f["id"]) if f["conflict_type"] == RESTATEMENT else ("finding", f["id"])
    try:
        can_approve(cur, answered_by, *target)
    except SegregationOfDutiesError as err:
        record_block(cur, err, at)
        raise

    decision = option["decision"]
    result = {"escalation_id": escalation_id, "finding_id": f["id"], "decision": decision, "journals": [],
              "precedent_id": None, "settled": [], "escalated_to": None, "overrode": overrode}
    if decision == "escalate":
        _close(cur, escalation_id, option_id, answered_by, at, None)
        cur.execute("UPDATE findings SET state = 'open' WHERE id = %s", (f["id"],))
        result["escalated_to"] = escalate(cur, finding(cur, f["id"]), at, to_role="controller",
                                          prefix=f"{who['name']}: {reasoning.strip()} ")["id"]
        return result
    if decision == "hold":
        set_finding_state(cur, f["id"], "escalated", {"decision": "hold", "by": answered_by, "at": at, "note": reasoning})
        _close(cur, escalation_id, option_id, answered_by, at, None)
        return result

    result["journals"] = decide(cur, f, decision, answered_by, at, note=reasoning)
    pid = write_precedent(cur, f, decision, reasoning.strip(), answered_by, at, escalation_id, overrode)
    _close(cur, escalation_id, option_id, answered_by, at, pid)
    _note(cur, f["id"], precedent_id=pid)
    result["precedent_id"] = pid
    result["settled"] = settle_siblings(cur, pid, at)
    return result


def _close(cur, escalation_id, option_id, answered_by, at, precedent_id) -> None:
    cur.execute("""UPDATE escalations SET answer = %s, answered_by = %s, answered_at = %s, became_precedent_id = %s
                   WHERE id = %s""", (option_id, answered_by, at, precedent_id, escalation_id))


def settle_siblings(cur: psycopg.Cursor, precedent_id: str, at: datetime) -> list[str]:
    """Other open cards the new precedent governs are answered by it, citing it."""
    p = one_row(cur, """SELECT p.*, (SELECT MAX(q.exposure_limit) FROM precedents q
                                     WHERE (q.control_id, q.conflict_type, q.customer_id, q.decision)
                                         = (p.control_id, p.conflict_type, p.customer_id, p.decision)) AS standing_limit
                        FROM precedents p WHERE p.id = %s""", (precedent_id,))
    settled = []
    for esc in open_escalations(cur):
        f = finding(cur, esc["finding_id"])
        if (f["control_id"], conflict_key(f), f["customer_id"]) != (p["control_id"], p["conflict_type"], p["customer_id"]) \
                or not covers(p, f):
            continue
        apply_precedent(cur, f, p, at)
        _close(cur, esc["id"], f"precedent:{p['id']}", None, at, None)
        settled.append(esc["id"])
    return settled


def on_event(cur: psycopg.Cursor, event: dict, at: datetime, *, respond: Respond | None = None) -> None:
    """A scripted human action. Approvals go through the capability check like any other."""
    if event["action"] != "approve":
        return
    try:
        can_approve(cur, event["actor_id"], event["target_type"], event["target_id"])
    except SegregationOfDutiesError as err:
        record_block(cur, err, at, event_id=event["id"])
        return
    # Permitted: it is an answer to the open card on the target, if there is one.
    for esc in open_escalations(cur):
        ev = esc["evidence"] or {}
        if event["target_id"] in ev.get("deduction_ids", []) + [ev.get("amendment_id"), esc["finding_id"]]:
            option = next((o for o in esc["options"] if o["decision"] in ("approve", "clear")), None)
            if option:
                answer(cur, esc["id"], option["id"], event["actor_id"], at, reasoning=event["note"] or "Approved.")
            return


def hooks(respond: Respond | None = None) -> Hooks:
    """The engine's hooks with judgment plugged in. Without `respond`, escalations wait in the inbox
    for a person (the API) and periods wait for a signature; `tpa.players.hooks()` passes the
    model-played humans and the played close reviewer."""
    return Hooks(judge=partial(judge, respond=respond), on_event=partial(on_event, respond=respond),
                 approve=partial(request_approval, respond=respond))
