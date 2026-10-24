"""The controls library. Every control is a consistency rule across two of the four sources —
program terms, shipments, deductions, claim backup. The rule is code and lives here; the
threshold, owner and precedents are mined from history by `tpa.onboarding` and live in the
`controls` table, so the same checks run in the onboarding replay and in the live cycle.

Checks return `Hit`s. A hit is only a candidate: `exceeds` compares its measure with the
mined threshold, and only hits over threshold become findings.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import psycopg

from tpa.accrual import backup_variance, rate, straddles_quarter_end
from tpa.asof import terms_as_of
from tpa.constants import Control as C, period_end, period_start
from tpa.policy import SEVERITY_BANDS, STRADDLE_CONFIDENCE, TERMS_READING_CONFIDENCE, VARIANCE_NOISE_FLOOR_PCT
from tpa.rows import all_rows, one_row

ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class Spec:
    name: str
    condition: str           # stored as controls.condition: the rule, written as an expression
    threshold_unit: str
    kind: str                # binary | tolerance | materiality | age | authority | drift


LIBRARY: dict[str, Spec] = {
    C.DED_GT_ACCRUAL: Spec(
        "Deduction exceeds accrued program liability",
        "sum(cleared + this deduction for program, origin) - accrued_liability(program, origin) > threshold",
        "usd", "materiality"),
    C.SCAN_NO_BACKUP: Spec(
        "Scan-back claim with no backup on file",
        "program.program_type = 'scan_back' and claim_backup(deduction) is null",
        "usd", "binary"),
    C.OUTSIDE_WINDOW: Spec(
        "Deduction taken outside the program window",
        "deduction.claimed_period not within [program.window_start, program.window_end]",
        "usd", "binary"),
    C.STALE_ACCRUAL: Spec(
        "Accrual aged beyond expected claim lag without a deduction",
        "liability(program, origin) > 0 and no deduction cleared and age(origin) - claim_lag(customer) > threshold",
        "periods", "age"),
    C.CLAIM_VS_BACKUP: Spec(
        "Claimed amount differs from scan backup",
        "abs(deduction.amount - backup.scan_units * backup.scan_rate) / (backup.scan_units * backup.scan_rate) * 100 > threshold",
        "pct", "tolerance"),
    C.DUPLICATE_DEDUCTION: Spec(
        "Duplicate deduction for one program period",
        "exists earlier deduction with same customer, program, claimed_period, claim dates, reason_code and amount",
        "usd", "binary"),
    C.RETURNS_NOT_NETTED: Spec(
        "Returns not netted from promoted volume",
        "return.available_at > period_end(shipment.period) and accrual(shipment.program, shipment.period) posted",
        "usd", "binary"),
    C.NO_PROOF: Spec(
        "Display claim without proof of performance",
        "program.requires_proof and not coalesce(backup.proof_of_performance, false)",
        "usd", "binary"),
    C.PERIOD_STRADDLE: Spec(
        "Claim spans a quarter end",
        "quarter(deduction.claim_start) <> quarter(deduction.claim_end)",
        "usd", "binary"),
    C.RATE_CONFLICT: Spec(
        "Claimed rate differs from program rate",
        "deduction.claimed_rate <> terms_as_of(program, claim_start).rate or backup.notes asserts a reading of the terms",
        "usd", "binary"),
    C.WRITEOFF_AUTHORITY: Spec(
        "Write-off over authority threshold",
        "dispute.disputed_amount - dispute.resolution_amount > threshold",
        "usd", "authority"),
    C.REDEMPTION_DRIFT: Spec(
        "Actual redemption diverges from projected rate",
        "abs(claimed_units(program, origin) / net_shipped(program, origin) - projected_redemption) / projected_redemption * 100 > threshold",
        "pct", "drift"),
}

# When several row checks fire on one deduction, the first listed is the root cause.
ROW_PRIORITY = (C.DUPLICATE_DEDUCTION, C.OUTSIDE_WINDOW, C.PERIOD_STRADDLE, C.SCAN_NO_BACKUP, C.NO_PROOF,
                C.RATE_CONFLICT, C.CLAIM_VS_BACKUP)

REASON_PROGRAM_TYPES = {"DISPLAY": "display", "MDF": "mdf"}


@dataclass
class Hit:
    control_id: str
    conflict_type: str               # precedent match key, with control_id and customer_id
    measure: Decimal | None          # compared with the control's threshold
    amount: Decimal | None           # the money the finding is about
    exposure: Decimal | None         # dollars at risk if we are wrong
    summary: str
    evidence: dict = field(default_factory=dict)
    confidence: Decimal = Decimal("1")


def exceeds(hit: Hit, threshold: Decimal | None) -> bool:
    if hit.measure is None:
        return True
    return hit.measure > (threshold or ZERO)


def severity(exposure: Decimal | None) -> str:
    e = exposure or ZERO
    return next((band for floor, band in SEVERITY_BANDS if e >= floor), "low")


# ── matching ────────────────────────────────────────────────────────────────
def program_type_for_reason(reason_code: str) -> str | None:
    if reason_code.startswith("SB-") or reason_code == "SB":
        return "scan_back"
    return REASON_PROGRAM_TYPES.get(reason_code)


def claim_dates(ded: dict) -> tuple[date, date]:
    return (ded["claim_start"] or period_start(ded["claimed_period"]),
            ded["claim_end"] or period_end(ded["claimed_period"]))


def match_program(cur: psycopg.Cursor, ded: dict, as_of: datetime) -> tuple[str | None, str]:
    """(program_id, how): the program the deduction cites, else the one its reason code and
    claim dates point to. 'unmatched' when neither works — the matching problem."""
    if ded["program_id"]:
        return ded["program_id"], "cited"
    ptype = program_type_for_reason(ded["reason_code"])
    if ptype is None:
        return None, "unmatched"
    program_id = program_on(cur, ded["customer_id"], ptype, claim_dates(ded)[0], as_of)
    return (program_id, "inferred") if program_id else (None, "unmatched")


def program_on(cur: psycopg.Cursor, customer_id: str, program_type: str | None, on: date,
               as_of: datetime) -> str | None:
    """The customer's program of this type whose window holds `on`, on the terms known at `as_of`."""
    row = one_row(
        cur,
        """SELECT program_id FROM program_terms
           WHERE customer_id = %s AND program_type = %s AND window_start <= %s AND window_end >= %s
             AND decision_time <= %s
           ORDER BY decision_time DESC LIMIT 1""",
        (customer_id, program_type, on, on, as_of),
    )
    return row["program_id"] if row else None


def backup_for(cur: psycopg.Cursor, deduction_id: str, as_of_date: date) -> dict | None:
    return one_row(cur, "SELECT * FROM claim_backup WHERE deduction_id = %s AND available_at <= %s "
                        "ORDER BY available_at DESC, id DESC LIMIT 1", (deduction_id, as_of_date))


# ── row checks on one deduction ─────────────────────────────────────────────
def check_deduction(cur: psycopg.Cursor, ded: dict, program_id: str | None, as_of: datetime) -> list[Hit]:
    """Every row-level rule that fires on this deduction, measures attached, thresholds not applied."""
    hits: list[Hit] = []
    start, end = claim_dates(ded)
    backup = backup_for(cur, ded["id"], as_of.date())
    base = {"deduction_ids": [ded["id"]], "program_id": program_id, "claimed_period": ded["claimed_period"],
            "origin": ded["claimed_period"]}
    amount = ded["amount"]

    dup = one_row(
        cur,
        """SELECT id FROM deductions
           WHERE customer_id = %s AND id <> %s AND available_at <= %s
             AND claimed_period = %s AND amount = %s AND reason_code = %s
             AND claim_start IS NOT DISTINCT FROM %s AND claim_end IS NOT DISTINCT FROM %s
             AND (available_at, id) < (%s, %s)
           ORDER BY available_at, id LIMIT 1""",
        (ded["customer_id"], ded["id"], ded["available_at"], ded["claimed_period"], amount, ded["reason_code"],
         ded["claim_start"], ded["claim_end"], ded["available_at"], ded["id"]),
    )
    if dup:
        hits.append(Hit(C.DUPLICATE_DEDUCTION, "duplicate", None, amount, amount,
                        f"{ded['id']} repeats {dup['id']}: same program period, claim dates and amount ${amount:,}.",
                        {**base, "deduction_ids": [ded["id"], dup["id"]], "duplicate_of": dup["id"]}))

    terms = terms_as_of(cur, program_id, start, as_of) if program_id else None
    if program_id and terms is not None and not (
            terms["window_start"] <= period_start(ded["claimed_period"])
            and period_end(ded["claimed_period"]) <= terms["window_end"]):
        hits.append(Hit(C.OUTSIDE_WINDOW, "outside_window", None, amount, amount,
                        f"{ded['id']} claims {ded['claimed_period']} against {program_id}, whose window is "
                        f"{terms['window_start']} to {terms['window_end']}.",
                        {**base, "window": [terms["window_start"].isoformat(), terms["window_end"].isoformat()]}))

    if straddles_quarter_end(ded["claim_start"], ded["claim_end"]):
        hits.append(Hit(C.PERIOD_STRADDLE, "quarter_straddle", None, amount, amount,
                        f"{ded['id']} covers {start} to {end}, across a quarter end; the claimed period "
                        f"{ded['claimed_period']} cannot be verified on its own.",
                        {**base, "claim_start": start.isoformat(), "claim_end": end.isoformat()},
                        confidence=STRADDLE_CONFIDENCE))

    if terms is None:
        return hits
    ptype = terms["program_type"]

    if ptype == "scan_back" and backup is None:
        hits.append(Hit(C.SCAN_NO_BACKUP, "no_backup", None, amount, amount,
                        f"Scan-back deduction {ded['id']} for ${amount:,} has no scan data on file.", base))

    if terms["requires_proof"] and not (backup and backup["proof_of_performance"]):
        hits.append(Hit(C.NO_PROOF, "no_proof", None, amount, amount,
                        f"{ded['id']} claims ${amount:,} under {program_id}, which requires proof of performance; "
                        f"none on file{': ' + repr(backup['notes']) if backup and backup['notes'] else ''}.",
                        {**base, **({"backup_id": backup["id"]} if backup else {})}))
    elif backup and backup["notes"]:
        hits.append(Hit(C.RATE_CONFLICT, "terms_reading", None, amount, amount,
                        f"{ded['id']}: the customer's backup reads {program_id} as {backup['notes']!r}. "
                        f"Our terms do not settle it. Which is the source of truth?",
                        {**base, "backup_id": backup["id"], "customer_reading": backup["notes"],
                         "source_clause_id": terms["source_clause_id"]},
                        confidence=TERMS_READING_CONFIDENCE))

    if ded["claimed_rate"] is not None and ptype == "scan_back" and ded["claimed_rate"] != terms["rate"]:
        diff = ded["claimed_rate"] - terms["rate"]
        units = backup["scan_units"] if backup and backup["scan_units"] else None
        exposure = abs(diff) * units if units else amount
        hits.append(Hit(C.RATE_CONFLICT, "claimed_rate", None, amount, exposure.quantize(Decimal("0.01")),
                        f"{ded['id']} claims {ded['claimed_period']} at ${rate(ded['claimed_rate'])}/case. "
                        f"{program_id} as we hold it says ${rate(terms['rate'])}/case "
                        f"({terms['source_clause_id']}). Which is the source of truth?",
                        {**base, "claimed_rate": str(ded["claimed_rate"]), "program_rate": str(terms["rate"]),
                         "term_id": terms["id"], "source_clause_id": terms["source_clause_id"]}))

    if backup and backup["scan_units"] and backup["scan_rate"]:
        v = backup_variance(amount, backup["scan_units"], backup["scan_rate"]) * HUNDRED
        if v > VARIANCE_NOISE_FLOOR_PCT:
            supported = (Decimal(backup["scan_units"]) * backup["scan_rate"]).quantize(Decimal("0.01"))
            hits.append(Hit(C.CLAIM_VS_BACKUP, "backup_variance", v.quantize(Decimal("0.0001")), amount,
                            abs(amount - supported),
                            f"{ded['id']} claims ${amount:,}; backup supports ${supported:,} "
                            f"({backup['scan_units']:,} units × ${rate(backup['scan_rate'])}), {v:.2f}% apart.",
                            {**base, "backup_id": backup["id"], "supported": str(supported),
                             "variance_pct": str(v.quantize(Decimal("0.0001")))}))
    return hits


def root_cause(hits: list[Hit]) -> list[Hit]:
    """Order hits so the root cause comes first."""
    return sorted(hits, key=lambda h: ROW_PRIORITY.index(h.control_id) if h.control_id in ROW_PRIORITY else 99)


# ── redemption drift: the control the live year teaches ─────────────────────
# History cannot teach this tolerance; it is stated policy (tpa.policy.DRIFT_TOLERANCE_PCT).


def check_redemption(cur: psycopg.Cursor, program_id: str, origin: str, as_of: datetime) -> Hit | None:
    """Actual sell-through for an origin whose claims have landed, against the projection we accrue at."""
    term = terms_as_of(cur, program_id, period_end(origin), as_of)
    if term is None or term["program_type"] != "scan_back" or not term["projected_redemption"]:
        return None
    cur.execute("""SELECT COALESCE(SUM(s.cases), 0) - COALESCE((SELECT SUM(r.cases) FROM returns r JOIN shipments s2
                     ON s2.id = r.shipment_id WHERE s2.program_id = %s AND s2.period = %s AND r.available_at <= %s), 0)
                   FROM shipments s WHERE s.program_id = %s AND s.period = %s""",
                (program_id, origin, as_of.date(), program_id, origin))
    net = cur.fetchone()[0]
    if not net:
        return None
    start, end = period_start(origin), period_end(origin)
    units, ids, covered = Decimal("0"), [], {}
    for d in all_rows(cur, """SELECT * FROM deductions WHERE customer_id = %s AND available_at <= %s
                                AND (claimed_period = %s OR (claim_start <= %s AND claim_end >= %s)) ORDER BY id""",
                      (term["customer_id"], as_of.date(), origin, end, start)):
        if match_program(cur, d, as_of)[0] not in (program_id, None) and d["claimed_period"] == origin:
            continue
        if any(h.control_id == C.DUPLICATE_DEDUCTION for h in check_deduction(cur, d, program_id, as_of)):
            continue
        cs, ce = claim_dates(d)
        lo, hi = max(cs, start), min(ce, end)
        if hi < lo:
            continue
        if cs < start or ce > end:
            # A claim spanning months mixes two months' volume: allocation by days is fine for the
            # books but too coarse to measure sell-through within a point. Not a clean month.
            return None
        share = Decimal((hi - lo).days + 1) / Decimal((ce - cs).days + 1)
        b = backup_for(cur, d["id"], as_of.date())
        claimed = Decimal(b["scan_units"]) if b and b["scan_units"] else (
            d["amount"] / d["claimed_rate"] if d["claimed_rate"] else Decimal("0"))
        units += claimed * share
        ids.append(d["id"])
        days = covered.setdefault(d["reason_code"], set())
        days.update(range(lo.toordinal(), hi.toordinal() + 1))
    # Judge sell-through only once every claim stream covers every day of the origin.
    month = set(range(start.toordinal(), end.toordinal() + 1))
    if not covered or any(days != month for days in covered.values()):
        return None
    if not ids:
        return None
    projected = term["projected_redemption"]
    actual = (units / Decimal(net)).quantize(Decimal("0.0001"))
    drift = ((actual - projected) / projected * HUNDRED).quantize(Decimal("0.01"))
    exposure = (abs(actual - projected) * Decimal(net) * term["rate"]).quantize(Decimal("0.01"))
    return Hit(C.REDEMPTION_DRIFT, "redemption_drift", abs(drift), exposure, exposure,
               f"{program_id} {origin}: claims show {actual:.2%} sell-through against the {projected:.0%} we accrue at "
               f"({'+' if drift > 0 else ''}{drift}%). Each open month is {'under' if drift > 0 else 'over'}-accrued by "
               f"about ${exposure:,}.",
               {"program_id": program_id, "origin": origin, "actual_redemption": actual, "projected_redemption": projected,
                "drift_pct": drift, "net_cases": net, "claimed_units": units.quantize(Decimal("1")), "deduction_ids": ids})


# ── returns ─────────────────────────────────────────────────────────────────
def check_late_return(cur: psycopg.Cursor, ret: dict) -> Hit | None:
    """A return that reached us after its shipment's period was accrued."""
    sh = one_row(cur, "SELECT * FROM shipments WHERE id = %s", (ret["shipment_id"],))
    if not sh or not sh["program_id"] or ret["available_at"] <= period_end(sh["period"]):
        return None
    return Hit(C.RETURNS_NOT_NETTED, "late_return", None, None, None,
               f"{ret['cases']:,} cases returned on {sh['id']} ({sh['period']}) reached us on "
               f"{ret['available_at']}, after that period was accrued.",
               {"return_id": ret["id"], "shipment_id": sh["id"], "program_id": sh["program_id"],
                "origin": sh["period"], "returned_cases": ret["cases"]})


def landed_deductions(cur: psycopg.Cursor, *, customer_id: str | None = None, through: date) -> list[dict]:
    return all_rows(cur, "SELECT * FROM deductions WHERE available_at <= %s AND (%s::text IS NULL OR customer_id = %s) "
                         "ORDER BY available_at, id", (through, customer_id, customer_id))
