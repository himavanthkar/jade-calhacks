"""The HTTP surface the UI reads (workstream D's contract in spec.md, as frontend/src/api expects it).

    GET  /api/clock                    → where the simulation is
    GET  /api/period/{period}          → { state, customers[], postings[], findings[], gates{}, flux[], analytical_review }
    POST /api/period/{period}/step     → run that period (must be the one the clock points at)
    POST /api/period/{period}/sign     → { customer_id, signed_by } a named reviewer signs a clean period
    GET  /api/period/{period}/package  → the sign-off package (?as_of=), per customer
    GET  /api/period/{period}/export/{file}.csv → the package as CSV with Excel check rows
    GET  /api/controls                 → [{ id, name, threshold, owner, precedent_ids, fired_count, learned }]
    GET  /api/escalations?open=true    → [{ id, to_role, question, options[], evidence{} }]
    POST /api/escalations/{id}/answer  → { answer, answered_by?, reasoning? } ⇒ writes the precedent
    GET  /api/explain/{entry_id}       → the evidence chain
    POST /api/ask                      → { question } the interrogation box
    GET  /api/metrics?as_of={period}   → { precision, recall, escalation_rate, autonomy }
    GET  /api/scenario/examples        → ready-made scenarios against the books as they stand
    POST /api/scenario                 → { kind, payload, step? } add source rows to the month the clock is on
    GET  /api/scenario                 → everything injected so far

Decimals go out as strings, never floats. Who answers a step's escalations is TPA_HUMANS:
'inbox' (default: cards wait for a person), 'players' (the model-played humans) or 'autopilot'.

    uv run uvicorn tpa.api:app --reload
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path as P
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from tpa import autopilot, explain, export, judgment, players, scenario
from tpa.package import package as signoff_package
from tpa.asof import sim_clock
from tpa.constants import live_month, period_end, period_start
from tpa.cycle import UNRESOLVED, last_period, step
from tpa.db import connect
from tpa.evaluate import metrics as evaluate_metrics, resolve_period
from tpa.gates import GateFailure, sign_period
from tpa.rows import all_rows, one_row
from tpa.sod import SegregationOfDutiesError

ROOT = Path(__file__).resolve().parent.parent
ANSWER_KEY = ROOT / "data" / "answer_key.json"
STATE_ORDER = ("OPEN", "ACCRUED", "CONTROLLED", "ESCALATED", "REVIEWED", "SIGNED", "CLOSED", "RESTATED")
PERIOD = r"^\d{4}-(0[1-9]|1[0-2])$"


def _plain(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    raise TypeError(type(v).__name__)


class Json(JSONResponse):
    """JSON with decimals as strings, so no amount is ever rounded through a float."""
    def render(self, content) -> bytes:
        return json.dumps(content, default=_plain, ensure_ascii=False).encode()


def out(content) -> Json:
    """Return through Json directly: FastAPI's own encoder would turn every Decimal into a float."""
    return Json(content=content)


app = FastAPI(title="Trade promotion autonomy", default_response_class=Json)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def db() -> Iterator[psycopg.Connection]:
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@app.exception_handler(SegregationOfDutiesError)
def _sod(_, err: SegregationOfDutiesError):
    return Json(status_code=403, content={"detail": str(err), "kind": "segregation_of_duties"})


@app.exception_handler(PermissionError)
def _forbidden(_, err: PermissionError):
    return Json(status_code=403, content={"detail": str(err)})


@app.exception_handler(GateFailure)
def _gate(_, err: GateFailure):
    return Json(status_code=409, content={"detail": str(err), "kind": "gate_failure"})


def now(cur) -> datetime:
    """When a person acts between steps: the morning of the period the clock points at, before it runs."""
    period, _ = sim_clock(cur)
    return datetime.combine(period_start(period), time(7, 0))


def hooks():
    mode = os.environ.get("TPA_HUMANS", "inbox")
    if mode == "players":
        says_no = os.environ.get("TPA_CONTROLLER_SAYS_NO") == "1"
        return players.hooks(players.CONTROLLER_SAYS_NO if says_no else None)
    if mode == "autopilot":
        return autopilot.hooks()
    return judgment.hooks()


# ── the clock and the period ────────────────────────────────────────────────
@app.get("/api/clock")
def clock(conn=Depends(db)):
    with conn.cursor() as cur:
        period, sim_date = sim_clock(cur)
        return out({"current_period": period, "sim_date": sim_date, "live_month": live_month(period),
                    "last_period": last_period(cur), "humans": os.environ.get("TPA_HUMANS", "inbox")})


@app.get("/api/period/{period}")
def get_period(period: str = P(..., pattern=PERIOD), as_of: str | None = None, conn=Depends(db)):
    """The period as the books stood at `as_of` (ISO date-time or 'month-N'); default: as they stand now."""
    if as_of and as_of.startswith("month-"):
        known = datetime.combine(period_end(resolve_period(as_of)), time.max)
    else:
        known = datetime.fromisoformat(as_of) if as_of else datetime.max
    with conn.cursor() as cur:
        customers = all_rows(cur, """SELECT period, customer_id, state, signed_by, signed_at, gate_results
                                     FROM periods WHERE period = %s ORDER BY customer_id""", (period,))
        if not customers:
            raise HTTPException(404, f"no period {period}")
        postings = all_rows(cur, "SELECT * FROM ledger_entries WHERE period = %s AND decision_time <= %s ORDER BY id",
                            (period, known))
        findings = all_rows(cur, "SELECT * FROM findings WHERE period = %s AND created_at <= %s ORDER BY id",
                            (period, known))
        flux = all_rows(cur, "SELECT * FROM flux_commentary WHERE period = %s AND decision_time <= %s ORDER BY id",
                        (period, known))
        review = one_row(cur, "SELECT * FROM analytical_reviews WHERE period = %s AND decision_time <= %s",
                         (period, known))
    gates: dict = {}
    for c in customers:
        for name, g in (c["gate_results"] or {}).items():
            merged = gates.setdefault(name, {"name": name, "description": g.get("description", ""), "passed": True,
                                             "violations": []})
            merged["passed"] = merged["passed"] and g.get("passed", False)
            merged["violations"] += [{**v, "customer_id": c["customer_id"]} for v in g.get("violations", [])]
    state = min((c["state"] for c in customers), key=STATE_ORDER.index)
    return out({"period": period, "state": state, "customers": customers, "postings": postings, "findings": findings,
                "gates": gates, "flux": flux, "analytical_review": review})


@app.post("/api/period/{period}/step")
def step_period(period: str = P(..., pattern=PERIOD), conn=Depends(db)):
    with conn.cursor() as cur:
        current, _ = sim_clock(cur)
    if period != current:
        raise HTTPException(409, f"the clock is at {current}; step that period first")
    try:
        return out(step(conn, hooks()))
    except RuntimeError as err:
        raise HTTPException(409, str(err)) from err


class Signature(BaseModel):
    customer_id: str
    signed_by: str = "close_reviewer"


@app.post("/api/period/{period}/sign")
def sign(body: Signature, period: str = P(..., pattern=PERIOD), conn=Depends(db)):
    with conn.cursor() as cur:
        row = one_row(cur, "SELECT * FROM periods WHERE period = %s AND customer_id = %s", (period, body.customer_id))
        if row is None:
            raise HTTPException(404, f"no period {period} for {body.customer_id}")
        if row["signed_at"]:
            raise HTTPException(409, f"{period} {body.customer_id} is already signed")
        cur.execute("SELECT COUNT(*) FROM findings WHERE period = %s AND customer_id = %s AND state = ANY(%s)",
                    (period, body.customer_id, list(UNRESOLVED)))
        if cur.fetchone()[0]:
            raise HTTPException(409, f"{period} {body.customer_id} still has unresolved findings")
        result = sign_period(cur, period, body.customer_id, body.signed_by, now(cur))
        cur.execute("SELECT bool_and(state = 'SIGNED') FROM periods WHERE period = %s", (period,))
        if cur.fetchone()[0]:
            cur.execute("UPDATE periods SET state = 'CLOSED' WHERE period = %s AND state = 'SIGNED'", (period,))
    return out(result)


@app.get("/api/period/{period}/package")
def get_package(period: str = P(..., pattern=PERIOD), as_of: str | None = None, conn=Depends(db)):
    with conn.cursor() as cur:
        return out(signoff_package(cur, period, export.parse_as_of(as_of)))


@app.get("/api/period/{period}/export/{name}")
def get_export(name: str, period: str = P(..., pattern=PERIOD), as_of: str | None = None, conn=Depends(db)):
    if name not in export.FILES:
        raise HTTPException(404, f"no export {name}; one of {', '.join(export.FILES)}")
    with conn.cursor() as cur:
        text = export.files(cur, period, export.parse_as_of(as_of))[name]
    return PlainTextResponse(text, media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{period}_{name}"'})


# ── controls and escalations ────────────────────────────────────────────────
@app.get("/api/controls")
def controls(conn=Depends(db)):
    with conn.cursor() as cur:
        return out(all_rows(cur, """SELECT c.id, c.name, c.condition, c.threshold, c.threshold_unit,
                                       c.owner_role AS owner, c.precedent_ids, c.learned, c.status, c.mined_at,
                                       (SELECT COUNT(*) FROM findings f WHERE f.control_id = c.id)::int AS fired_count,
                                       ARRAY(SELECT p.id FROM precedents p WHERE p.control_id = c.id ORDER BY p.id)
                                         AS live_precedent_ids
                                FROM controls c ORDER BY c.learned, c.id"""))


@app.get("/api/precedents/{kind}/{precedent_id}")
def precedent(kind: str, precedent_id: str, conn=Depends(db)):
    """A precedent cell's click: a prior-year decision (kind=history) or a live answer (kind=live)."""
    with conn.cursor() as cur:
        row = one_row(cur, "SELECT * FROM historical_decisions WHERE id = %s" if kind == "history" else
                      "SELECT * FROM precedents WHERE id = %s", (precedent_id,))
    if row is None:
        raise HTTPException(404, f"no {kind} precedent {precedent_id}")
    return out(row)


@app.get("/api/escalations")
def escalations(open: bool = True, conn=Depends(db)):
    with conn.cursor() as cur:
        return out(all_rows(cur, """SELECT e.*, f.period, f.customer_id, f.control_id, f.escalation_type, f.exposure,
                                       f.evidence
                                FROM escalations e JOIN findings f ON f.id = e.finding_id
                                WHERE NOT %s OR e.answered_at IS NULL ORDER BY e.id""", (open,)))


class Answer(BaseModel):
    answer: str                        # an option id, or its label
    answered_by: str | None = None     # default: the person the card is addressed to
    reasoning: str | None = None       # default: the option's label; it becomes the precedent's reasoning


@app.post("/api/escalations/{escalation_id}/answer")
def answer(escalation_id: str, body: Answer, conn=Depends(db)):
    with conn.cursor() as cur:
        try:
            esc = judgment.escalation(cur, escalation_id)
        except KeyError as err:
            raise HTTPException(404, f"no escalation {escalation_id}") from err
        option = next((o for o in esc["options"] if body.answer in (o["id"], o["label"])), None)
        if option is None:
            raise HTTPException(422, f"{body.answer!r} is not an option on {escalation_id}")
        customer = one_row(cur, "SELECT customer_id FROM findings WHERE id = %s", (esc["finding_id"],))["customer_id"]
        who = body.answered_by or players.actor_for(esc["to_role"], customer)
        try:
            result = judgment.answer(cur, escalation_id, option["id"], who, now(cur),
                                  reasoning=body.reasoning or option["label"])
        except SegregationOfDutiesError:
            conn.commit()                  # keep the record of the blocked attempt
            raise
        except ValueError as err:
            raise HTTPException(422, str(err)) from err
    return out(result)


# ── interrogation and metrics ───────────────────────────────────────────────
@app.get("/api/explain/{entry_id}")
def explain_entry(entry_id: str, conn=Depends(db)):
    with conn.cursor() as cur:
        history = explain.entry_history(cur, entry_id)
        if history is None:
            raise HTTPException(404, f"no entry {entry_id}")
        c = explain.chain(cur, entry_id)
    return out({**history, "chain": c, "text": explain.as_text(c)})


class Question(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: Question, conn=Depends(db)):
    with conn.cursor() as cur:
        return out(explain.ask(cur, body.question))


@app.get("/api/metrics")
def metrics(as_of: str, conn=Depends(db)):
    if not ANSWER_KEY.exists():
        raise HTTPException(404, "no answer key: run make seed")
    with conn.cursor() as cur:
        return out(evaluate_metrics(cur, json.loads(ANSWER_KEY.read_text()), as_of))


class Injection(BaseModel):
    kind: str
    payload: dict
    step: bool = False                 # also run the month, so the scenario plays out at once
    injected_by: str | None = None


@app.get("/api/scenario/examples")
def scenario_examples(conn=Depends(db)):
    with conn.cursor() as cur:
        return out(scenario.examples(cur))


@app.get("/api/scenario")
def scenario_list(conn=Depends(db)):
    with conn.cursor() as cur:
        return out(scenario.injections(cur))


@app.post("/api/scenario")
def inject(body: Injection, conn=Depends(db)):
    """The judge's own scenario: rows land in the month the clock is on and the engine meets them
    on the next step, as it meets everything else."""
    with conn.cursor() as cur:
        try:
            made = scenario.inject(cur, body.kind, body.payload, injected_by=body.injected_by)
        except scenario.ScenarioError as err:
            raise HTTPException(422, str(err)) from err
    conn.commit()
    if not body.step:
        return out(made)
    summary = step(conn, hooks())
    with conn.cursor() as cur:
        touched = all_rows(cur, """SELECT * FROM findings WHERE period = %s AND EXISTS (
                                     SELECT 1 FROM jsonb_array_elements_text(jsonb_path_query_array(evidence, 'strict $.**'))
                                     AS x(v) WHERE x.v = ANY(%s)) ORDER BY id""", (made["period"], made["created_ids"]))
    return out({**made, "step": summary, "findings": touched})


@app.post("/api/reset")
def reset():
    """Re-seed for a fresh run. Destroys the demo database, so it is off unless TPA_ALLOW_RESET=1."""
    if os.environ.get("TPA_ALLOW_RESET") != "1":
        raise HTTPException(403, "reset is disabled; set TPA_ALLOW_RESET=1")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "seed.py"), "--seed", "1337", "--months", "24"],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL)
    return out({"reset": True})
