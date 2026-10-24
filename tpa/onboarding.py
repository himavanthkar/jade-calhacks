"""Onboarding: replay the history year, diff it against what the humans did, mine the controls.

1. Replay   re-run the library's checks on the subject of every historical decision, as the
            data stood when the human decided. The check that fires names the control the
            decision teaches; a decision no check explains is reported, never guessed.
2. Diff     what the humans accepted versus what they escalated gives each tolerance; who
            handled the escalated cases gives the owner.
3. Mine     one `controls` row per control, citing the decisions that taught it. Thresholds
            are derived from behaviour, never configured.
4. Priors   claim lag, dispute rate and backup arrival per customer; materiality per account.

Deterministic: the model has no part in this module.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal

import psycopg

from tpa.accrual import ZERO, activity_share, fixed_fund_amount, money, nice_ceiling
from tpa.asof import terms_as_of
from tpa.constants import (
    HISTORY_MONTHS, Account, Control as C, month_for_period, period_end, period_for_month, period_of,
    period_start,
)
from tpa.controls import LIBRARY, check_deduction, check_late_return, match_program, root_cause
from tpa.execute import scan_back_estimate
from tpa.gates import claim_lag_prior
from tpa.policy import MATERIALITY_RATE
from tpa.rows import all_rows, one_row

HISTORY_START = period_for_month(min(HISTORY_MONTHS))
HISTORY_END = period_for_month(max(HISTORY_MONTHS))
ONBOARDED_AT = datetime.combine(period_end(HISTORY_END), time(23, 30))
# An over-accrual smaller than a tenth of a percent of a month's accruals is not worth a human's time.
GATE_OWNER = "close_reviewer"


class OnboardingError(RuntimeError):
    pass


@dataclass
class Lesson:
    decision: dict
    control_id: str
    measure: Decimal | None


# ── replay: what each human decision was about ──────────────────────────────
def classify(cur: psycopg.Cursor, d: dict) -> Lesson | None:
    as_of = d["decided_at"]
    kind = d["subject_type"]
    if kind == "shipment":
        for ret in all_rows(cur, "SELECT * FROM returns WHERE shipment_id = %s AND available_at <= %s",
                            (d["subject_id"], as_of.date())):
            if check_late_return(cur, ret):
                return Lesson(d, C.RETURNS_NOT_NETTED, None)
        return None
    if kind == "accrual":
        program_id, origin = d["subject_id"].split(":")
        claimed = one_row(cur, "SELECT 1 FROM deductions WHERE program_id = %s AND claimed_period = %s "
                               "AND available_at <= %s", (program_id, origin, as_of.date()))
        if claimed:
            return None
        return Lesson(d, C.STALE_ACCRUAL, Decimal(month_for_period(period_of(as_of.date())) - month_for_period(origin)))
    if kind == "dispute":
        ds = one_row(cur, "SELECT * FROM disputes WHERE id = %s", (d["subject_id"],))
        if ds and ds["resolution"] == "partial" and ds["disputed_amount"] > ds["resolution_amount"]:
            return Lesson(d, C.WRITEOFF_AUTHORITY, ds["disputed_amount"] - ds["resolution_amount"])
        return None
    if kind == "deduction":
        ded = one_row(cur, "SELECT * FROM deductions WHERE id = %s", (d["subject_id"],))
        program_id, _ = match_program(cur, ded, as_of)
        hits = root_cause(check_deduction(cur, ded, program_id, as_of))
        if hits:
            return Lesson(d, hits[0].control_id, hits[0].measure)
        # Claims for one origin arrive over weeks, and a quarter-end straddle a month after the
        # rest: judge the over-claim with the whole history year in hand, as onboarding can.
        excess = over_claim(cur, program_id, ded["claimed_period"], max(as_of, ONBOARDED_AT))
        return Lesson(d, C.DED_GT_ACCRUAL, excess) if excess > 0 else None
    return None


def estimate(cur: psycopg.Cursor, program_id: str, origin: str, as_of: datetime) -> Decimal:
    """What the replay would have accrued for (program, origin) on what was known at `as_of`."""
    term = terms_as_of(cur, program_id, period_start(origin), as_of)
    if term is None:
        return ZERO
    if term["program_type"] in ("display", "mdf"):
        return fixed_fund_amount(term, origin)
    if term["program_type"] != "scan_back":
        return ZERO
    # The same estimator the live accrual uses, with volume and terms both as known at `as_of`.
    return scan_back_estimate(cur, program_id, origin, as_of, as_of)[0]


def over_claim(cur: psycopg.Cursor, program_id: str | None, origin: str, as_of: datetime) -> Decimal:
    """Sell-through claimed for (program, origin) beyond the replayed estimate. Claims that do
    not belong to this origin (duplicates, other windows) are left out; a rate conflict
    counts at the program's rate. A claim held for missing backup still counts: the volume
    was sold whether or not the paperwork has arrived."""
    if program_id is None:
        return ZERO
    start, end = period_start(origin), period_end(origin)
    claims = Decimal("0")
    for ded in all_rows(
            cur,
            """SELECT * FROM deductions WHERE customer_id = (SELECT customer_id FROM trade_programs WHERE id = %s)
                 AND available_at <= %s
                 AND (claimed_period = %s OR (claim_start <= %s AND claim_end >= %s))""",
            (program_id, as_of.date(), origin, end, start)):
        if match_program(cur, ded, as_of)[0] != program_id:
            continue
        hits = {h.control_id: h for h in check_deduction(cur, ded, program_id, as_of)}
        if C.DUPLICATE_DEDUCTION in hits or C.OUTSIDE_WINDOW in hits:
            continue
        amount = ded["amount"]
        rate = hits.get(C.RATE_CONFLICT)
        if rate and rate.conflict_type == "claimed_rate":
            amount -= rate.exposure
        claims += amount * activity_share(ded["claim_start"], ded["claim_end"], start, end)
    return money(claims) - estimate(cur, program_id, origin, as_of)


# ── priors ──────────────────────────────────────────────────────────────────
def derive_priors(cur: psycopg.Cursor) -> dict:
    """Per-customer behaviour and per-account materiality, all from the history year."""
    end = period_end(HISTORY_END)
    customers = [r["id"] for r in all_rows(cur, "SELECT id FROM customers ORDER BY id")]
    out: dict = {"customers": {}, "accounts": {}}
    monthly_accruals: dict[str, Decimal] = defaultdict(Decimal)
    for cid in customers:
        deds = all_rows(cur, "SELECT d.*, b.id AS backup_id FROM deductions d LEFT JOIN claim_backup b "
                             "ON b.deduction_id = d.id WHERE d.customer_id = %s AND d.available_at <= %s", (cid, end))
        disputes = one_row(cur, "SELECT COUNT(*) AS n FROM disputes ds JOIN deductions d ON d.id = ds.deduction_id "
                                "WHERE d.customer_id = %s AND ds.raised_date <= %s", (cid, end))["n"]
        needs_backup = [d for d in deds if d["reason_code"] != "MDF"]
        out["customers"][cid] = {
            "claim_lag_months": claim_lag_prior(cur, cid),
            "dispute_rate": round(disputes / len(deds), 4) if deds else 0.0,
            "backup_arrival_rate": round(sum(1 for d in needs_backup if d["backup_id"]) / len(needs_backup), 4)
            if needs_backup else None,
            "deductions": len(deds),
        }
        for m in HISTORY_MONTHS:
            period = period_for_month(m)
            for p in all_rows(cur, "SELECT id FROM trade_programs WHERE customer_id = %s", (cid,)):
                monthly_accruals[period] += estimate(cur, p["id"], period, ONBOARDED_AT)
    mean_month = sum(monthly_accruals.values(), ZERO) / len(HISTORY_MONTHS)
    out["accounts"][Account.ACCRUED_TRADE_PROMO] = {
        "mean_monthly_accrual": money(mean_month),
        "materiality": nice_ceiling(mean_month * MATERIALITY_RATE),
    }
    return out


# ── mining ──────────────────────────────────────────────────────────────────
def derive_threshold(control_id: str, lessons: list[Lesson], priors: dict) -> tuple[Decimal, str]:
    """(threshold, how it was derived)."""
    kind = LIBRARY[control_id].kind
    if kind == "binary":
        return ZERO, "acted on every case regardless of size: any"
    if kind == "tolerance":
        accepted = [l.measure for l in lessons if l.decision["action"] == "accept_variance"]
        escalated = [l.measure for l in lessons if l.decision["action"] != "accept_variance"]
        t = nice_ceiling(max(accepted))
        if escalated and t >= min(escalated):
            raise OnboardingError(f"{control_id}: accepted and escalated cases overlap at {t}")
        return t, (f"{len(accepted)} variances up to {max(accepted):.2f}% accepted, "
                   f"{len(escalated)} from {min(escalated):.1f}% escalated")
    if kind == "authority":
        lower = [l.measure for l in lessons if l.decision["decided_by"] != "controller"]
        upper = [l.measure for l in lessons if l.decision["decided_by"] == "controller"]
        t = nice_ceiling(max(lower))
        if upper and t >= min(upper):
            raise OnboardingError(f"{control_id}: delegated and controller cases overlap at {t}")
        return t, f"write-offs up to ${max(lower):,} signed by the analyst; ${min(upper):,} went to the controller"
    if kind == "age":
        youngest = min(l.measure for l in lessons)
        return youngest - 1, f"accruals released once {int(youngest)} periods old"
    if kind == "materiality":
        m = priors["accounts"][Account.ACCRUED_TRADE_PROMO]
        return m["materiality"], (f"every over-claim in history (${min(l.measure for l in lessons):,.0f} and up) "
                                  f"was topped up; tolerance set at account materiality, "
                                  f"{MATERIALITY_RATE:%} of ${m['mean_monthly_accrual']:,} a month")
    raise OnboardingError(f"{control_id}: no derivation for kind {kind}")


def derive_owner(control_id: str, lessons: list[Lesson], threshold: Decimal, roles: dict[str, str]) -> str:
    kind = LIBRARY[control_id].kind
    if kind == "age":
        return GATE_OWNER    # enforced as a verifiability gate: it blocks whoever signs the close
    above = [l for l in lessons if l.measure is None or l.measure > threshold]
    if kind == "tolerance":
        above = [l for l in lessons if l.decision["action"] != "accept_variance"]
    deciders = Counter(roles[l.decision["decided_by"]] for l in (above or lessons))
    return deciders.most_common(1)[0][0]


def mine(cur: psycopg.Cursor) -> dict:
    """Replay history, mine the controls and write them. Idempotent: replaces mined rows."""
    roles = {r["id"]: r["role"] for r in all_rows(cur, "SELECT id, role FROM actors")}
    decisions = all_rows(cur, "SELECT * FROM historical_decisions ORDER BY id")
    lessons: dict[str, list[Lesson]] = defaultdict(list)
    unexplained = []
    for d in decisions:
        lesson = classify(cur, d)
        if lesson is None:
            unexplained.append(d["id"])
        else:
            lessons[lesson.control_id].append(lesson)

    priors = derive_priors(cur)
    mined = []
    for control_id, ls in lessons.items():
        spec = LIBRARY[control_id]
        threshold, why = derive_threshold(control_id, ls, priors)
        mined.append({
            "id": control_id, "name": spec.name, "condition": spec.condition, "threshold": threshold,
            "threshold_unit": spec.threshold_unit, "owner_role": derive_owner(control_id, ls, threshold, roles),
            "precedent_ids": [l.decision["id"] for l in ls], "mined_at": ONBOARDED_AT, "learned": False,
            "status": "active", "derivation": why,
        })
    mined.sort(key=lambda c: list(LIBRARY).index(c["id"]))
    for c in mined:
        cur.execute(
            """INSERT INTO controls (id, name, condition, threshold, threshold_unit, owner_role, precedent_ids,
                                     mined_at, learned, status)
               VALUES (%(id)s, %(name)s, %(condition)s, %(threshold)s, %(threshold_unit)s, %(owner_role)s,
                       %(precedent_ids)s, %(mined_at)s, %(learned)s, %(status)s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, condition = EXCLUDED.condition,
                 threshold = EXCLUDED.threshold, threshold_unit = EXCLUDED.threshold_unit,
                 owner_role = EXCLUDED.owner_role, precedent_ids = EXCLUDED.precedent_ids,
                 mined_at = EXCLUDED.mined_at""",
            c,
        )
    return {"controls": mined, "priors": priors, "unexplained_decisions": unexplained,
            "decisions": len(decisions)}


def ensure_onboarded(cur: psycopg.Cursor) -> None:
    cur.execute("SELECT COUNT(*) FROM controls WHERE NOT learned")
    if cur.fetchone()[0] == 0:
        mine(cur)


def learn_control(cur: psycopg.Cursor, control_id: str, threshold: Decimal, owner_role: str, at: datetime) -> bool:
    """Add a control the history year could not teach. Returns True if it is new."""
    spec = LIBRARY[control_id]
    cur.execute(
        """INSERT INTO controls (id, name, condition, threshold, threshold_unit, owner_role, precedent_ids,
                                 mined_at, learned, status)
           VALUES (%s, %s, %s, %s, %s, %s, '{}', %s, TRUE, 'active') ON CONFLICT (id) DO NOTHING""",
        (control_id, spec.name, spec.condition, threshold, spec.threshold_unit, owner_role, at),
    )
    return cur.rowcount == 1
