"""The model-played humans: controller, customer team analyst, and the accountants who own controls.

Each answers the cards addressed to its role through `judgment.answer`, the same path a person in
the UI takes, so segregation of duties, precedents and postings are identical. With the model on
(`tpa.model`), Claude plays the role: it reads the card and the evidence and must pick one of the
card's options, giving its reasoning. Off, or if its reply is not a valid option, the role answers
the way last year's people did, citing the prior-year decisions that taught the control.

    hooks = players.hooks()        # then cycle.step(conn, hooks)
"""

import json
from datetime import datetime

import psycopg

from tpa import judgment, model
from tpa.autopilot import ACTOR_FOR_ROLE, CUSTOMER_TEAM, PRECEDENT_ANSWERS
from tpa.constants import Control as C
from tpa.cycle import Hooks
from tpa.execute import _jsonable, finding

PERSONAS = {
    "controller": "You are the Controller at General Mills. You own restatements, exceptions and anything "
                  "material. You approve what the agreement and the evidence support and nothing more.",
    "customer_team_analyst": "You are the customer team analyst for {customer} at General Mills. You know "
                             "how this customer reads its programs and you settle which source is the truth.",
    "deduction_analyst": "You are the deduction analyst at General Mills. No claim clears without the backup "
                         "the program requires.",
    "trade_promotion_accountant": "You are the trade promotion accountant at General Mills. You own the "
                                  "accruals and their estimates.",
    "close_reviewer": "You are the close reviewer at General Mills. Nothing stays on the books that the "
                      "evidence does not support.",
}

# Where last year has no answer, what the role does and why.
NO_PRECEDENT = {
    (C.RATE_CONFLICT, "terms_reading"): ("customer", "The clause is ambiguous and we drafted it, so it reads "
                                                     "the customer's way. Tighten the wording at renewal."),
    (C.DED_GT_ACCRUAL, judgment.RESTATEMENT): ("approve", "The amendment was signed and is in force from its "
                                                          "effective date; the closed periods were booked on "
                                                          "terms we now know were superseded."),
    (C.REDEMPTION_DRIFT, None): ("acknowledge", "Real sell-through is running above projection; take it into "
                                                "the next estimate."),
}


def actor_for(role: str, customer_id: str) -> str:
    return CUSTOMER_TEAM[customer_id] if role == "customer_team_analyst" else ACTOR_FOR_ROLE[role]


def standin(f: dict, esc: dict) -> tuple[str, str]:
    """(option_id, reasoning) as last year's people would have answered."""
    options = esc["options"]
    key = (f["control_id"], f["conflict_type"])
    if any(o["decision"] == "apply_candidates" for o in options):
        # Rule 03: never release an accrual while a claim that may settle it sits unapplied.
        return "apply", ("The unmatched deduction is this accrual's claim: same customer, same period, close to "
                         "the instalment. Apply it and release only the residual.")
    prior = PRECEDENT_ANSWERS.get(key) or PRECEDENT_ANSWERS.get((f["control_id"], None))
    if prior:
        option = next((o for o in options if o["decision"] == prior[1]), None)
        if option:
            taught = ((f["evidence"] or {}).get("control") or {}).get("precedent_ids", [])
            cited = ", ".join(taught[:3]) + ("…" if len(taught) > 3 else "")
            return option["id"], (f"As last year: {len(taught)} prior cases{f' ({cited})' if cited else ''} were "
                                  f"resolved this way — {option['label'].lower()}.")
    choice = NO_PRECEDENT.get(key) or NO_PRECEDENT.get((f["control_id"], None))
    if choice and any(o["id"] == choice[0] for o in options):
        return choice
    hold = next(o for o in options if o["decision"] == "hold")
    return hold["id"], "Not enough to decide on; holding for more evidence."


def played(f: dict, esc: dict, persona: str) -> tuple[str, str] | None:
    reply = model.ask_json(
        persona + " You are answering an escalation from an autonomous accounting agent. Pick exactly one "
                  "of the options by id and explain your reasoning in two sentences, citing the evidence.",
        json.dumps({"question": esc["question"], "options": esc["options"], "evidence": f["evidence"]},
                   default=_jsonable, indent=1)
        + '\n\nShape: {"option_id": "...", "reasoning": "..."}')
    if not reply or not str(reply.get("reasoning", "")).strip():
        return None
    if not any(o["id"] == reply.get("option_id") for o in esc["options"]):
        return None
    return reply["option_id"], str(reply["reasoning"]).strip()


def respond(cur: psycopg.Cursor, esc: dict, at: datetime) -> dict | None:
    f = finding(cur, esc["finding_id"])
    cur.execute("SELECT name FROM customers WHERE id = %s", (f["customer_id"],))
    persona = PERSONAS.get(esc["to_role"], PERSONAS["controller"]).format(customer=cur.fetchone()[0])
    option_id, reasoning = played(f, esc, persona) or standin(f, esc)
    who = actor_for(esc["to_role"], f["customer_id"])
    return judgment.answer(cur, esc["id"], option_id, who, at, reasoning=reasoning)


def answer_open(cur: psycopg.Cursor, at: datetime) -> list[dict]:
    """Let every role clear its inbox: for a run where the cards were left waiting."""
    return [r for esc in judgment.open_escalations(cur) if (r := respond(cur, esc, at))]


def sign(cur: psycopg.Cursor, period: str, customer_id: str, at: datetime) -> str | None:
    """The played close reviewer signs a period the engine offers: every gate passed, nothing open."""
    return ACTOR_FOR_ROLE["close_reviewer"]


def hooks() -> Hooks:
    h = judgment.hooks(respond=respond)
    h.sign = sign
    return h
