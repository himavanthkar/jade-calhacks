"""Precision, recall, escalation rate and autonomy against the answer key.

Matching is by evidence: a finding counts against a planted row when the finding's
`evidence` JSON mentions any of the row's specific ids (deductions, returns, shipments,
events, amendments, accrual keys). Program ids are too broad to match on. The shape
of `evidence` is free: every string inside it is collected.

Contracts the other workstreams rely on:
* A segregation-of-duties block is recorded as a finding with escalation_type 'sod'
  whose evidence names the scripted event or the target.
* A gate failure is caught when `periods.gate_results` for that customer, in the
  expected period or later, carries a violation keyed with the row's accrual key.
* The moment is caught by a finding citing AM-02 or its claims, or by any
  restatement journal on TP-0214.
* Findings on rows injected live (`scenario_injections`) are left out of precision and counted
  as `scenario_findings`: the answer key never planted them.
"""

import json
from collections import defaultdict

import psycopg

from tpa.constants import live_month, period_end, period_for_month
from tpa.seed import fiction as F

NOT_SPECIFIC = set(F.PROGRAM_BY_ID)


def ids_in(obj) -> set[str]:
    if isinstance(obj, str):
        return {obj}
    if isinstance(obj, dict):
        return set().union(*(ids_in(v) for v in obj.values())) if obj else set()
    if isinstance(obj, (list, tuple)):
        return set().union(*(ids_in(v) for v in obj)) if obj else set()
    return set()


def resolve_period(spec: str) -> str:
    """'month-9' → '2026-09'; '2026-09' passes through."""
    if spec.startswith("month-"):
        return period_for_month(12 + int(spec.split("-", 1)[1]))
    return spec


def _ratio(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def judgment_record(cur: psycopg.Cursor, as_of: str, skip: set[str]) -> dict:
    """Did answers stick? A repeat is a finding whose (control, conflict key, customer) a person had
    already answered before it was raised. Repeats should settle silently by precedent; one that is
    asked again should have a reason (a larger exposure than the standing approval covers). The
    first time a situation appears it should be asked: those are counted apart."""
    from tpa.cycle import MECHANICAL
    from tpa.judgment import conflict_key

    cur.execute("SELECT control_id, conflict_type, customer_id, decided_at, exposure_limit FROM precedents")
    answered = defaultdict(list)
    for control, key, customer, at, limit in cur.fetchall():
        answered[(control, key, customer)].append((at, limit))
    cur.execute("""SELECT f.id, f.control_id, f.conflict_type, f.customer_id, f.evidence, f.created_at, f.exposure,
                          EXISTS (SELECT 1 FROM escalations e WHERE e.finding_id = f.id)
                   FROM findings f WHERE f.period <= %s AND f.escalation_type IS DISTINCT FROM 'sod' ORDER BY f.id""",
                (as_of,))
    repeats, silent, again, first = 0, 0, [], 0
    for fid, control, ctype, customer, evidence, created, exposure, asked in cur.fetchall():
        if fid in skip or control in MECHANICAL:
            continue
        ev = evidence if not isinstance(evidence, str) else json.loads(evidence)
        key = (control, conflict_key({"conflict_type": ctype, "evidence": ev}), customer)
        before = [limit for at, limit in answered.get(key, []) if at < created]
        if before:
            repeats += 1
            if ev.get("precedent_id") and not asked:
                silent += 1
            elif asked:
                limits = [x for x in before if x is not None]
                standing = max(limits) if limits else None
                again.append({"finding_id": fid, "exposure": exposure, "standing_approval": standing,
                              "reason": "larger than the standing approval" if standing is not None and exposure
                              and exposure > standing else "no precedent applied"})
        elif asked:
            first += 1
    return {"repeat_findings": repeats, "settled_by_precedent": silent, "asked_again": len(again),
            "asked_again_detail": again, "precedent_hit_rate": _ratio(silent, repeats), "first_time_questions": first}


def metrics(cur: psycopg.Cursor, answer_key: dict, as_of: str) -> dict:
    as_of = resolve_period(as_of)
    in_window = lambda row: row["period"] <= as_of

    planted = [r for r in answer_key["planted"] if in_window(r)]
    errors = [r for r in planted if r["expected_outcome"] != "pass"]
    negatives = [r for r in planted if r["expected_outcome"] == "pass"]
    behavioural = [r for r in answer_key["behavioural"] if in_window(r)]

    index = defaultdict(list)   # specific evidence id → [(kind, row)]
    for kind, rows in (("error", errors), ("negative", negatives), ("behavioural", behavioural)):
        for row in rows:
            for ev in set(row["evidence"]) - NOT_SPECIFIC:
                index[ev].append((kind, row))

    cur.execute(
        """SELECT f.id, f.period, f.customer_id, f.control_id, f.escalation_type, f.evidence,
                  EXISTS (SELECT 1 FROM escalations e WHERE e.finding_id = f.id)
           FROM findings f WHERE f.period <= %s ORDER BY f.id""",
        (as_of,),
    )
    findings = cur.fetchall()
    # Findings on rows a person injected live are the judge's scenario, not the answer key's: scored apart.
    cur.execute("SELECT created_ids FROM scenario_injections")
    injected = {i for (ids,) in cur.fetchall() for i in ids}
    scenario = [f for f in findings if ids_in(f[5] if not isinstance(f[5], str) else json.loads(f[5])) & injected]
    findings = [f for f in findings if f not in scenario]

    caught: set[str] = set()
    true_pos, false_pos = 0, []
    for fid, period, customer_id, control_id, esc_type, evidence, _ in findings:
        ev = ids_in(evidence if not isinstance(evidence, str) else json.loads(evidence)) - NOT_SPECIFIC
        hits = [hit for e in ev for hit in index.get(e, [])]
        real = [row for kind, row in hits if kind in ("error", "behavioural")]
        if real:
            true_pos += 1
            # A self-approval is only caught by the SoD block itself, not by a finding on its target.
            caught |= {row["error_id"] for row in real if "error_id" in row
                       and (row["expected_outcome"] != "throw" or esc_type == "sod")}
        else:
            false_pos.append({"finding_id": fid, "period": period, "control_id": control_id,
                              "matched_negative": [row["error_id"] for kind, row in hits if kind == "negative"]})

    # Gate failures and restatements are caught outside the findings table.
    cur.execute("SELECT period, customer_id, gate_results FROM periods WHERE period <= %s", (as_of,))
    gate_keys = defaultdict(set)   # (customer, period) → violation keys
    for period, customer_id, results in cur.fetchall():
        for gate in (results or {}).values():
            for v in gate.get("violations", []):
                if "key" in v:
                    gate_keys[(customer_id, period)].add(v["key"])
    cur.execute(
        """SELECT EXISTS (SELECT 1 FROM ledger_entries WHERE entry_type = 'restatement'
                          AND program_id = %s AND decision_time <= %s)""",
        (F.AMENDMENT.program_id, period_end(as_of)),
    )
    restated = cur.fetchone()[0]
    for row in errors:
        if row["expected_outcome"] == "gate_fail":
            keys = {e for e in row["evidence"] if e.startswith("accrual:")}
            if any(keys & k for (c, p), k in gate_keys.items() if c == row["customer_id"] and p >= row["period"]):
                caught.add(row["error_id"])
        elif row["expected_outcome"] == "restate" and restated:
            caught.add(row["error_id"])

    # Escalation rate for the as-of month alone: it should fall as precedents accumulate.
    month = [f for f in findings if f[1] == as_of]
    escalated_month = sum(1 for f in month if f[6])

    # Autonomy: live customer-periods signed with no escalation raised in them.
    cur.execute(
        """SELECT p.period, p.customer_id,
                  p.signed_at IS NOT NULL AND NOT EXISTS (
                    SELECT 1 FROM escalations e JOIN findings f ON f.id = e.finding_id
                    WHERE f.period = p.period AND f.customer_id = p.customer_id)
           FROM periods p WHERE p.period >= %s AND p.period <= %s""",
        (period_for_month(13), as_of),
    )
    periods = cur.fetchall()

    judged = judgment_record(cur, as_of, {f[0] for f in scenario})

    missed = [{"error_id": r["error_id"], "type": r["type"], "period": r["period"],
               "customer_id": r["customer_id"], "expected_outcome": r["expected_outcome"]}
              for r in errors if r["error_id"] not in caught]
    return {
        "as_of": as_of,
        "live_month": live_month(as_of),
        "precision": _ratio(true_pos, len(findings)),
        "recall": _ratio(len(caught & {r["error_id"] for r in errors}), len(errors)),
        "escalation_rate": _ratio(escalated_month, len(month)),
        "autonomy": _ratio(sum(1 for *_, auto in periods if auto), len(periods)),
        "counts": {
            "findings": len(findings), "true_positive_findings": true_pos, "false_positive_findings": len(false_pos),
            "planted_errors": len(errors), "caught": len(caught), "true_negatives": len(negatives),
            "findings_this_month": len(month), "escalated_this_month": escalated_month,
            "customer_periods": len(periods), "scenario_findings": len(scenario),
        },
        "judgment": judged,
        "missed": missed,
        "false_positives": false_pos,
    }
