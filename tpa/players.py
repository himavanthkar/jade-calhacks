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
from functools import partial

import psycopg

from tpa import judgment, model
from tpa.autopilot import ACTOR_FOR_ROLE, CUSTOMER_TEAM
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

# The demo's controller says no. Last year straddling claims were allocated across the quarter
# end by activity days, so that is what the agent recommends; this year's controller won't have it.
CONTROLLER_SAYS_NO = {
    (C.PERIOD_STRADDLE, "WMT"): ("dispute", "No. Allocating across a quarter end moves expense between two reported "
                                            "quarters on our own estimate of activity days. Dispute it and have Walmart "
                                            "split the claim at the quarter end, so each part clears in its own quarter."),
}


def actor_for(role: str, customer_id: str) -> str:
    return CUSTOMER_TEAM[customer_id] if role == "customer_team_analyst" else ACTOR_FOR_ROLE[role]


def standin(f: dict, esc: dict) -> tuple[str, str]:
    """(option_id, reasoning): the role takes the agent's recommendation, as last year's people would have."""
    return esc["recommended"], esc["recommendation_basis"]


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


def respond(cur: psycopg.Cursor, esc: dict, at: datetime, overrides: dict | None = None) -> dict | None:
    f = finding(cur, esc["finding_id"])
    scripted = (overrides or {}).get((f["control_id"], f["customer_id"]))
    if scripted and any(o["id"] == scripted[0] for o in esc["options"]):
        return judgment.answer(cur, esc["id"], scripted[0], actor_for(esc["to_role"], f["customer_id"]), at,
                               reasoning=scripted[1])
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


def hooks(overrides: dict | None = None) -> Hooks:
    """`overrides`: {(control_id, customer_id): (option_id, reasoning)} answers that overrule the
    recommendation, e.g. CONTROLLER_SAYS_NO."""
    h = judgment.hooks(respond=partial(respond, overrides=overrides) if overrides else respond)
    h.sign = sign
    return h
