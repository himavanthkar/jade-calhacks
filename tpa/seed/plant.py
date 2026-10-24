"""Planting: the history the miner learns from, and the 50 live errors it is scored on.

History plants write `historical_decisions` — what the prior-year humans did — and
each one is tagged with the control it should teach. Live plants write the answer
key. Every plant takes rows nobody else has planted on, so each error has exactly
one cause.
"""

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

from tpa.constants import (
    LIVE_MONTHS, PLANTED_ERROR_COUNTS, Control as C, add_months, month_for_period, period_end,
    period_for_month, period_of, period_start,
)
from tpa.seed import fiction as F
from tpa.seed.generate import Builder, SeedError, at, money

CONTROL_SPEC = {
    C.DED_GT_ACCRUAL: dict(name="Deduction exceeds accrued program liability",
                           threshold=Decimal("2500"), threshold_unit="usd", owner_role="trade_promotion_accountant"),
    C.SCAN_NO_BACKUP: dict(name="Scan-back claim with no backup on file",
                           threshold=Decimal("0"), threshold_unit="usd", owner_role="deduction_analyst"),
    C.OUTSIDE_WINDOW: dict(name="Deduction taken outside the program window",
                           threshold=Decimal("0"), threshold_unit="usd", owner_role="controller"),
    C.STALE_ACCRUAL: dict(name="Accrual aged beyond expected claim lag without a deduction",
                          threshold=Decimal("2"), threshold_unit="periods", owner_role="close_reviewer"),
    C.CLAIM_VS_BACKUP: dict(name="Claimed amount differs from scan backup",
                            threshold=Decimal("0.5"), threshold_unit="pct", owner_role="trade_promotion_accountant"),
    C.DUPLICATE_DEDUCTION: dict(name="Duplicate deduction for one program period",
                                threshold=Decimal("0"), threshold_unit="usd", owner_role="deduction_analyst"),
    C.RETURNS_NOT_NETTED: dict(name="Returns not netted from promoted volume",
                               threshold=Decimal("0"), threshold_unit="usd", owner_role="trade_promotion_accountant"),
    C.NO_PROOF: dict(name="Display claim without proof of performance",
                     threshold=Decimal("0"), threshold_unit="usd", owner_role="deduction_analyst"),
    C.PERIOD_STRADDLE: dict(name="Claim spans a quarter end",
                            threshold=Decimal("0"), threshold_unit="usd", owner_role="controller"),
    C.RATE_CONFLICT: dict(name="Claimed rate differs from program rate",
                          threshold=Decimal("0"), threshold_unit="usd", owner_role="customer_team_analyst"),
    C.WRITEOFF_AUTHORITY: dict(name="Write-off over authority threshold",
                               threshold=Decimal("10000"), threshold_unit="usd", owner_role="controller"),
    C.REDEMPTION_DRIFT: dict(name="Actual redemption diverges from projected rate",
                             threshold=Decimal("1.0"), threshold_unit="pct", owner_role="trade_promotion_accountant"),
}

QUARTER_ENDS = (date(2025, 3, 31), date(2025, 6, 30), date(2025, 9, 30), date(2025, 12, 31),
                date(2026, 3, 31), date(2026, 6, 30), date(2026, 9, 30))


# ── selection ───────────────────────────────────────────────────────────────
def pick(b: Builder, n: int, pred, label: str, table: str = "deductions") -> list[dict]:
    pool = [r for r in b.rows(table) if not r.get("_planted") and pred(r)]
    if len(pool) < n:
        raise SeedError(f"{label}: need {n} candidates, found {len(pool)}")
    chosen = b.rng.sample(pool, n)
    for r in chosen:
        r["_planted"] = label
    return chosen


def month_of(d: date) -> int:
    return month_for_period(period_of(d))


def in_history(b: Builder):
    return lambda r: month_of(r["available_at"]) <= 12


def in_live(b: Builder):
    return lambda r: 13 <= month_of(r["available_at"]) <= b.months


def kind(k: str):
    return lambda r: r.get("_kind") == k


def all_of(*preds):
    return lambda r: all(p(r) for p in preds)


def wmt_signed_rate(r: dict) -> bool:
    return r.get("_kind") == "wmt_scan" and r["claimed_rate"] == r["_program"].rate


# ── mutations ───────────────────────────────────────────────────────────────
def set_units(d: dict, units: int, rate: Decimal | None = None) -> None:
    rate = rate if rate is not None else d["claimed_rate"]
    d["_units"] = units
    d["amount"] = money(units * rate)
    d["_backup"]["scan_units"] = units


def drop_backup(d: dict) -> None:
    d["_backup"]["_deleted"] = True
    d["_backup"] = None


def clone_duplicate(b: Builder, d: dict, lag_days: int) -> dict:
    fields = {k: v for k, v in d.items() if not k.startswith("_") and k != "id"}
    taken = d["taken_date"] + timedelta(days=lag_days)
    fields.update(taken_date=taken, available_at=taken, invoice_id=b.invoice_before(d["customer_id"], taken))
    dup = b.add("deductions", **fields)
    dup.update(_kind=d["_kind"], _program=d["_program"], _units=d.get("_units"), _planted="duplicate")
    if d.get("_backup"):
        bk = {k: v for k, v in d["_backup"].items() if not k.startswith("_")}
        bk.update(deduction_id=dup, received_date=taken, available_at=taken)
        dup["_backup"] = b.add("claim_backup", **bk)
    return dup


def merge_across(b: Builder, quarter_end: date, stream: str, label: str) -> dict:
    """Walmart claims normally split at month end. Merge the two segments either side of a
    quarter end into one claim that straddles it."""
    def seg(pred):
        hits = [d for d in b.rows("deductions") if d.get("_kind") == "wmt_scan" and d["reason_code"] == stream
                and not d.get("_planted") and pred(d)]
        if len(hits) != 1:
            raise SeedError(f"{label}: no clean segment pair at {quarter_end} for {stream}")
        return hits[0]

    first = seg(lambda d: d["claim_end"] == quarter_end)
    second = seg(lambda d: d["claim_start"] == quarter_end + timedelta(days=1))
    units = first["_units"] + second["_units"]
    amount = first["amount"] + second["amount"]
    first.update(amount=amount, claim_end=second["claim_end"], taken_date=second["taken_date"],
                 available_at=second["available_at"], invoice_id=second["invoice_id"], _units=units,
                 claimed_rate=first["claimed_rate"] if first["claimed_rate"] == second["claimed_rate"] else None,
                 _planted=label)
    first["_backup"].update(scan_units=units, scan_rate=(amount / units).quantize(Decimal("0.000001")),
                            received_date=second["taken_date"], available_at=second["available_at"])
    second["_deleted"] = True
    second["_backup"]["_deleted"] = True
    return first


def transpositions(amount: Decimal, above: bool) -> list[Decimal]:
    """Adjacent-digit swaps of an amount whose variance lands above (or below) the 0.5% tolerance."""
    s = f"{amount:.2f}"
    options = []
    for i in range(len(s) - 1):
        if "." in (s[i], s[i + 1]) or s[i] == s[i + 1] or (i == 0 and s[1] == "0"):
            continue
        cand = Decimal(s[:i] + s[i + 1] + s[i] + s[i + 2:])
        v = abs(cand - amount) / amount
        if (above and v > Decimal("0.005")) or (not above and v < Decimal("0.005")):
            options.append(cand)
    return options


# ── records ─────────────────────────────────────────────────────────────────
def decide(b: Builder, control: str, *, subject, subject_type: str, action: str, reason: str,
           decided_by: str, decided_on: date, customer_id: str, amount=None, variance_pct=None) -> dict:
    return b.add("historical_decisions", period=period_of(decided_on), customer_id=customer_id,
                 subject_type=subject_type, subject_id=subject, action=action, amount=amount,
                 variance_pct=variance_pct, reason=reason, decided_by=decided_by,
                 decided_at=at(decided_on, 11), journal_id=None, _control=control)


def dispute(b: Builder, d: dict, *, disputed: Decimal, recovered: Decimal, resolution: str, raised: date,
            resolve_days: int = 35) -> dict:
    resolved = raised + timedelta(days=resolve_days)
    return b.add("disputes", deduction_id=d, disputed_amount=disputed, raised_date=raised,
                 resolution=resolution, resolved_date=resolved, resolution_amount=recovered,
                 available_at=resolved)


def planted(b: Builder, type_: str, *, period: str, customer_id: str, amount, control, escalation,
            outcome: str, evidence: list, owner_role: str | None = None, note: str = "") -> dict:
    row = {
        "error_id": f"E-{len(b.planted) + 1:02d}", "type": type_, "period": period,
        "customer_id": customer_id, "amount": amount, "expected_control_id": control,
        "expected_escalation_type": escalation, "expected_owner_role": owner_role,
        "expected_outcome": outcome, "evidence": evidence, "note": note,
    }
    b.planted.append(row)
    return row


def surfaced(d: dict) -> str:
    return period_of(d["available_at"])


# ── late returns: before claims are generated ───────────────────────────────
def late_returns(b: Builder) -> None:
    def wmt_shipment(months):
        return lambda s: s["customer_id"] == "WMT" and month_for_period(s["period"]) in months

    def plant_one(s: dict) -> tuple[dict, Decimal]:
        program = F.PROGRAM_BY_ID[s["program_id"]]
        cases = round(s["cases"] * b.rng.uniform(0.04, 0.06))
        nxt = period_start(add_months(s["period"], 1))
        r = b.add_return(s, cases, min(s["ship_date"] + timedelta(days=5), period_end(s["period"])),
                         nxt + timedelta(days=b.rng.randint(1, 6)))
        return r, money(cases * program.projected_redemption * program.rate)

    for s in pick(b, 4, wmt_shipment(range(1, 12)), "h_late_returns", "shipments"):
        r, overstated = plant_one(s)
        decide(b, C.RETURNS_NOT_NETTED, subject=s, subject_type="shipment", action="adjust", amount=overstated,
               reason=f"{r['cases']:,} returned cases reached us after the {s['period']} accrual; "
                      f"accrued liability reduced by ${overstated:,}.",
               decided_by="tpa.human", decided_on=r["available_at"] + timedelta(days=2), customer_id="WMT")

    last_live = min(b.months - 1, max(LIVE_MONTHS) - 1)
    for s in pick(b, 7, wmt_shipment(range(13, last_live + 1)), "late_returns", "shipments"):
        r, overstated = plant_one(s)
        planted(b, "returns_not_netted", period=period_of(r["available_at"]), customer_id="WMT",
                amount=overstated, control=C.RETURNS_NOT_NETTED, escalation=None, outcome="auto_resolve",
                evidence=[r, s], note="Returns landed after the shipment period was accrued.")


# ── history: what the prior-year team did ───────────────────────────────────
def history(b: Builder) -> None:
    hist = in_history(b)
    rate_of = lambda d: d["claimed_rate"]

    # Claims spanning a quarter end. Controller allocated by activity days. First, because
    # it needs two specific untouched segments.
    for qe in (date(2025, 3, 31), date(2025, 6, 30)):
        stream = b.rng.choice(F.WALMART_STREAMS)[0]
        d = merge_across(b, qe, stream, "h_straddle")
        decide(b, C.PERIOD_STRADDLE, subject=d, subject_type="deduction", action="escalate", amount=d["amount"],
               reason=f"Claim covers {d['claim_start']} to {d['claim_end']}, across the quarter end. "
                      f"Controller allocated it by activity days.",
               decided_by="controller", decided_on=d["available_at"] + timedelta(days=2), customer_id="WMT")

    # Kroger claims without proof, roughly a third of the time. Disputed and recovered.
    for d in pick(b, 3, all_of(hist, kind("kr_display")), "h_no_proof"):
        d["_backup"].update(proof_of_performance=False, notes="Proof of performance to follow.")
        raised = d["available_at"] + timedelta(days=4)
        dispute(b, d, disputed=d["amount"], recovered=d["amount"], resolution="recovered", raised=raised)
        decide(b, C.NO_PROOF, subject=d, subject_type="deduction", action="reverse_claim", amount=d["amount"],
               reason="Display claim arrived without a tear sheet or store photo; disputed and recovered.",
               decided_by="deductions.human", decided_on=raised, customer_id="KR")

    # Accruals that never saw a deduction: released by the accountant.
    stale_ok = lambda d: month_for_period(d["claimed_period"]) <= 9
    for d in (pick(b, 2, all_of(hist, kind("cost_mdf"), stale_ok), "h_stale")
              + pick(b, 2, all_of(hist, kind("kr_display"), stale_ok), "h_stale")):
        d["_deleted"] = True
        if d.get("_backup"):
            d["_backup"]["_deleted"] = True
        noticed = period_end(add_months(d["claimed_period"], 3))
        decide(b, C.STALE_ACCRUAL, subject=f"{d['_program'].id}:{d['claimed_period']}", subject_type="accrual",
               action="release_stale_accrual", amount=d["amount"],
               reason=f"No deduction against {d['_program'].id} for {d['claimed_period']} after three periods; "
                      f"accrual released.",
               decided_by="tpa.human", decided_on=noticed, customer_id=d["customer_id"])

    # One deduction citing a program whose window had already closed. Recovered.
    for d in pick(b, 1, all_of(hist, kind("kr_display"), lambda d: month_for_period(d["claimed_period"]) >= 4),
                  "h_outside_window"):
        prior = F.program_for("KR", "display", d["_program"].window_start - timedelta(days=1))
        d["program_id"] = prior.id
        raised = d["available_at"] + timedelta(days=3)
        dispute(b, d, disputed=d["amount"], recovered=d["amount"], resolution="recovered", raised=raised)
        decide(b, C.OUTSIDE_WINDOW, subject=d, subject_type="deduction", action="recover", amount=d["amount"],
               reason=f"Claim for {d['claimed_period']} cites {prior.id}, whose window ended "
                      f"{prior.window_end.isoformat()}. Controller recovered it.",
               decided_by="controller", decided_on=raised, customer_id="KR")

    # Duplicates: the same claim taken twice. Recovered.
    early = lambda d: d["available_at"] <= date(2025, 12, 5)
    for d in (pick(b, 2, all_of(hist, early, wmt_signed_rate), "h_duplicate_source")
              + pick(b, 1, all_of(hist, early, kind("kr_display")), "h_duplicate_source")):
        dup = clone_duplicate(b, d, b.rng.randint(15, 24))
        raised = dup["available_at"] + timedelta(days=3)
        dispute(b, dup, disputed=dup["amount"], recovered=dup["amount"], resolution="recovered", raised=raised)
        decide(b, C.DUPLICATE_DEDUCTION, subject=dup, subject_type="deduction", action="recover",
               amount=dup["amount"], reason=f"Same program, period and amount as an earlier deduction; recovered.",
               decided_by="deductions.human", decided_on=raised, customer_id=d["customer_id"])

    # Rate conflicts: Walmart claimed above the signed rate. Customer team: program as signed.
    for d in pick(b, 2, all_of(hist, wmt_signed_rate), "h_rate_conflict"):
        signed = rate_of(d)
        claimed = signed + Decimal("0.30")
        signed_amount = d["amount"]
        d["claimed_rate"] = claimed
        set_units(d, d["_units"], claimed)
        d["_backup"]["scan_rate"] = claimed
        raised = d["available_at"] + timedelta(days=5)
        dispute(b, d, disputed=d["amount"] - signed_amount, recovered=d["amount"] - signed_amount,
                resolution="recovered", raised=raised)
        decide(b, C.RATE_CONFLICT, subject=d, subject_type="deduction", action="escalate",
               amount=d["amount"] - signed_amount,
               reason=f"Claimed ${claimed}/case against ${signed}/case as signed. Customer team: the program "
                      f"as signed is the source of truth. Difference disputed and recovered.",
               decided_by=F.CUSTOMER_TEAM["WMT"], decided_on=raised, customer_id="WMT")

    # Scan-backs with no backup: reversed. Partial recoveries leave write-offs, one over authority.
    resolvable = lambda d: d["available_at"] <= date(2025, 10, 31)
    for d, write_off in zip(pick(b, 3, all_of(hist, resolvable, wmt_signed_rate), "h_no_backup"),
                            (Decimal("4210.00"), Decimal("7860.00"), Decimal("18400.00"))):
        drop_backup(d)
        raised = d["available_at"] + timedelta(days=3)
        ds = dispute(b, d, disputed=d["amount"], recovered=d["amount"] - write_off, resolution="partial",
                     raised=raised)
        decide(b, C.SCAN_NO_BACKUP, subject=d, subject_type="deduction", action="reverse_claim", amount=d["amount"],
               reason="Scan-back deduction with no scan data on file; reversed pending backup.",
               decided_by="deductions.human", decided_on=raised, customer_id="WMT")
        approver = "controller" if write_off > CONTROL_SPEC[C.WRITEOFF_AUTHORITY]["threshold"] else "deductions.human"
        decide(b, C.WRITEOFF_AUTHORITY, subject=ds, subject_type="dispute", action="write_off", amount=write_off,
               reason=f"Unrecovered remainder of ${write_off:,} written off"
                      + (" — over $10,000, approved by the controller." if approver == "controller" else "."),
               decided_by=approver, decided_on=ds["resolved_date"], customer_id="WMT")

    # Claims above accrued liability: the accountant topped up the accrual. One per claimed period.
    for m in range(1, 8):
        period = period_for_month(m)
        (d,) = pick(b, 1, all_of(hist, wmt_signed_rate, lambda d: d["claimed_period"] == period), "h_over_accrual")
        extra = money(b.rng.uniform(3100, 42000))
        extra_units = int(round(extra / d["claimed_rate"]))
        set_units(d, d["_units"] + extra_units)
        decide(b, C.DED_GT_ACCRUAL, subject=d, subject_type="deduction", action="adjust",
               amount=money(extra_units * d["claimed_rate"]),
               reason=f"Claims for {period} exceeded accrued liability by "
                      f"${money(extra_units * d['claimed_rate']):,}; accrual topped up.",
               decided_by="tpa.human", decided_on=d["available_at"] + timedelta(days=2), customer_id="WMT")

    # Small variances accepted, two large ones escalated: the tolerance is learned, not configured.
    chosen = pick(b, 24, all_of(hist, wmt_signed_rate), "h_variance")
    for i, d in enumerate(chosen):
        v = Decimal(str(round(b.rng.uniform(0.0005, 0.0045), 5))) if i < 22 else (Decimal("0.016"), Decimal("0.029"))[i - 22]
        base = d["amount"]
        d["amount"] = money(base * (1 + v * b.rng.choice((1, -1))))
        accepted = i < 22
        decide(b, C.CLAIM_VS_BACKUP, subject=d, subject_type="deduction",
               action="accept_variance" if accepted else "escalate", amount=d["amount"] - base,
               variance_pct=(v * 100).quantize(Decimal("0.001")),
               reason=(f"Claim differs from scan backup by {v * 100:.2f}%; accepted."
                       if accepted else
                       f"Claim differs from scan backup by {v * 100:.1f}%; escalated and re-billed."),
               decided_by="deductions.human" if accepted else "tpa.human",
               decided_on=d["available_at"] + timedelta(days=1), customer_id="WMT")


# ── live: the answer key ────────────────────────────────────────────────────
def live(b: Builder) -> None:
    lv = in_live(b)
    wmt = all_of(lv, wmt_signed_rate)
    lands_by = lambda days: (lambda d: d["available_at"] + timedelta(days=days) <= b.end)

    # Claims at the amended rate belong to the moment and nothing else.
    for d in b.rows("deductions"):
        if d.get("_kind") == "wmt_scan" and d["claimed_rate"] == F.AMENDMENT.new_rate:
            d["_planted"] = "amendment"

    # Genuinely ambiguous terms: escalate as a source conflict.
    in_window = lambda pid: (lambda d: d["_program"].id == pid)
    (d,) = pick(b, 1, all_of(lv, kind("kr_display"), in_window("TP-0232")), "ambiguous_terms")
    d["_backup"]["notes"] = "End-cap display only; product was not featured in the circular."
    planted(b, "ambiguous_terms", period=surfaced(d), customer_id="KR", amount=d["amount"], control=None,
            escalation="source_conflict", owner_role="customer_team_analyst", outcome="escalate",
            evidence=["TP-0232", d], note="Clause 3.1 'and/or': does end-cap alone earn the fee?")
    (d,) = pick(b, 1, all_of(lv, kind("kr_display"), in_window("TP-0233")), "ambiguous_terms")
    d.update(amount=d["amount"] * 2, claim_end=d["claim_start"] + timedelta(days=9))
    d["_backup"]["notes"] = "Event ran ten days; claimed as two events under clause 3.4."
    planted(b, "ambiguous_terms", period=surfaced(d), customer_id="KR", amount=d["amount"] / 2, control=None,
            escalation="source_conflict", owner_role="customer_team_analyst", outcome="escalate",
            evidence=["TP-0233", d], note="Clause 3.4 'may be counted': at whose option?")
    (d,) = pick(b, 1, all_of(lv, kind("cost_mdf"), in_window("TP-0222")), "ambiguous_terms")
    d["_backup"] = b.add("claim_backup", deduction_id=d, scan_units=None, scan_rate=None, proof_of_performance=False,
                         notes="Volume commitment measured on gross shipments, before returns.",
                         received_date=d["available_at"], available_at=d["available_at"])
    planted(b, "ambiguous_terms", period=surfaced(d), customer_id="COST", amount=d["amount"], control=None,
            escalation="source_conflict", owner_role="customer_team_analyst", outcome="escalate",
            evidence=["TP-0222", d], note="Clause 2.3: is the 1.7M-case commitment gross or net of returns?")

    # Claims straddling a quarter end: low confidence.
    for qe, stream in ((date(2025, 9, 30), "SB-SUPERCENTER"), (date(2025, 9, 30), "SB-NEIGHBORHOOD"),
                       (date(2025, 12, 31), "SB-SUPERCENTER"), (date(2025, 12, 31), "SB-NEIGHBORHOOD")):
        d = merge_across(b, qe, stream, "straddle")
        planted(b, "straddles_quarter_end", period=surfaced(d), customer_id="WMT", amount=d["amount"],
                control=C.PERIOD_STRADDLE, escalation="low_confidence", owner_role="controller", outcome="escalate",
                evidence=[d], note=f"Covers {d['claim_start']} to {d['claim_end']}.")
    qe_months = {period_of(q) for q in QUARTER_ENDS}
    (d,) = pick(b, 1, all_of(lv, kind("kr_display"), lambda d: d["claimed_period"] in qe_months), "straddle")
    qe = period_end(d["claimed_period"])
    d.update(claim_start=qe - timedelta(days=5), claim_end=qe + timedelta(days=8))
    planted(b, "straddles_quarter_end", period=surfaced(d), customer_id="KR", amount=d["amount"],
            control=C.PERIOD_STRADDLE, escalation="low_confidence", owner_role="controller", outcome="escalate",
            evidence=[d], note=f"Event runs {d['claim_start']} to {d['claim_end']}.")

    # Deductions citing a program whose window has closed: block, controller.
    for d in pick(b, 2, all_of(lv, kind("kr_display"), lambda d: d["claimed_period"] >= "2026-04"), "outside_window"):
        prior = F.program_for("KR", "display", d["_program"].window_start - timedelta(days=1))
        d["program_id"] = prior.id
        planted(b, "deduction_outside_window", period=surfaced(d), customer_id="KR", amount=d["amount"],
                control=C.OUTSIDE_WINDOW, escalation="authority", owner_role="controller", outcome="block",
                evidence=[d, prior.id], note=f"Claims {d['claimed_period']} against {prior.id}.")
    (d,) = pick(b, 1, all_of(lv, kind("cost_mdf"), lambda d: d["claimed_period"] >= "2026-02"), "outside_window")
    d["program_id"] = "TP-0122"
    planted(b, "deduction_outside_window", period=surfaced(d), customer_id="COST", amount=d["amount"],
            control=C.OUTSIDE_WINDOW, escalation="authority", owner_role="controller", outcome="block",
            evidence=[d, "TP-0122"], note=f"2026 instalment cites the 2025 MDF program.")

    # Behavioural, not an error: Kroger claims without proof about a third of the time.
    # Sampled after the Kroger plants that need specific quarters.
    for d in pick(b, 4, all_of(lv, kind("kr_display")), "no_proof"):
        d["_backup"].update(proof_of_performance=False, notes="Proof of performance to follow.")
        b.behavioural.append({"type": "no_proof", "period": surfaced(d), "customer_id": "KR", "amount": d["amount"],
                              "expected_control_id": C.NO_PROOF, "expected_outcome": "dispute", "evidence": [d]})

    # Duplicates: auto-resolve from the mined control.
    for d in (pick(b, 3, all_of(wmt, lands_by(24)), "duplicate_source")
              + pick(b, 2, all_of(lv, kind("cost_mdf"), lands_by(24)), "duplicate_source")
              + pick(b, 1, all_of(lv, kind("kr_display"), lands_by(24)), "duplicate_source")):
        dup = clone_duplicate(b, d, b.rng.randint(12, 24))
        planted(b, "duplicate_deduction", period=surfaced(dup), customer_id=d["customer_id"], amount=dup["amount"],
                control=C.DUPLICATE_DEDUCTION, escalation=None, outcome="auto_resolve", evidence=[dup, d])

    # Deductions that land but cannot be matched: the accrual ages and the gate blocks the period.
    for d in pick(b, 4, all_of(lv, kind("cost_mdf"), lambda d: month_for_period(d["claimed_period"]) + 3 <= b.months),
                  "accrual_never_cleared"):
        accrual = f"accrual:{d['_program'].id}:{d['claimed_period']}"
        d.update(program_id=None, invoice_id=None, reason_code="MISC",
                 amount=d["amount"] - money(b.rng.uniform(1200, 2500)))
        planted(b, "accrual_never_cleared", period=add_months(d["claimed_period"], 3), customer_id="COST",
                amount=money(d["_program"].rate / 12), control=C.STALE_ACCRUAL, escalation=None,
                owner_role="close_reviewer", outcome="gate_fail", evidence=[d, accrual],
                note="Instalment deducted net of an unexplained amount with no program or invoice reference.")

    # Scan-backs with no backup: block, deduction analyst.
    for d in pick(b, 8, wmt, "no_backup"):
        drop_backup(d)
        planted(b, "scan_back_no_backup", period=surfaced(d), customer_id="WMT", amount=d["amount"],
                control=C.SCAN_NO_BACKUP, escalation="authority", owner_role="deduction_analyst", outcome="block",
                evidence=[d])

    # Transposed digits: flag above the learned tolerance, pass below it.
    can = lambda above: (lambda d: bool(transpositions(d["amount"], above)))
    for i, d in enumerate(pick(b, 3, all_of(wmt, can(True)), "transposed")
                          + pick(b, 2, all_of(wmt, can(False)), "transposed")):
        above = i < 3
        base = d["amount"]
        options = transpositions(base, above)
        d["amount"] = options[-1] if above else b.rng.choice(options)   # rightmost material swap stays plausible
        planted(b, "transposed_digits", period=surfaced(d), customer_id="WMT", amount=abs(d["amount"] - base),
                control=C.CLAIM_VS_BACKUP if above else None, escalation=None,
                owner_role="trade_promotion_accountant" if above else None, outcome="flag" if above else "pass",
                evidence=[d], note=f"Backup supports ${base:,}; claimed ${d['amount']:,}.")

    # True negatives: small variances inside the learned 0.5% tolerance. Must pass silently.
    for d in pick(b, 6, wmt, "within_tolerance"):
        v = Decimal(str(round(b.rng.uniform(0.0005, 0.004), 5)))
        base = d["amount"]
        d["amount"] = money(base * (1 + v * b.rng.choice((1, -1))))
        planted(b, "within_tolerance", period=surfaced(d), customer_id="WMT", amount=abs(d["amount"] - base),
                control=None, escalation=None, outcome="pass", evidence=[d],
                note=f"{v * 100:.2f}% variance against backup.")

    # A sales lead approving a claim on their own program.
    target = min((r["evidence"][0] for r in b.behavioural if r["type"] == "no_proof"),
                 key=lambda d: d["available_at"])
    ev = b.add("scripted_events", sim_date=target["available_at"], actor_id=F.SALES_LEAD["KR"], action="approve",
               target_type="deduction", target_id=target, note="Approve the display claim; proof is on its way.")
    planted(b, "sales_lead_self_approval", period=surfaced(target), customer_id="KR", amount=target["amount"],
            control=None, escalation="sod", owner_role="controller", outcome="throw", evidence=[ev, target])


def moment(b: Builder) -> None:
    a = F.AMENDMENT
    if month_of(a.available_at) > b.months:
        raise SeedError("the amendment lands after the simulation ends")
    claims = [d for d in b.rows("deductions") if d.get("_planted") == "amendment"]
    planted(b, "amendment_not_applied", period=period_of(a.available_at), customer_id="WMT",
            amount=b.moment["total_catch_up"], control=C.DED_GT_ACCRUAL, escalation="authority",
            owner_role="controller", outcome="restate", evidence=[a.id, a.program_id, *claims],
            note="Restate Feb–Jul, post the catch-up, draft flux. See answer_key.moment.")
    ev = b.add("scripted_events", sim_date=a.available_at + timedelta(days=1), actor_id=F.SALES_LEAD["WMT"],
               action="approve", target_type="restatement", target_id=a.id,
               note="Approve the TP-0214 catch-up adjustment.")
    planted(b, "sales_lead_self_approval", period=period_of(ev["sim_date"]), customer_id="WMT",
            amount=b.moment["total_catch_up"], control=None, escalation="sod", owner_role="controller",
            outcome="throw", evidence=[ev, a.id])

    counts = Counter(r["type"] for r in b.planted)
    if counts != Counter(PLANTED_ERROR_COUNTS):
        raise SeedError(f"planted counts {dict(counts)} do not match {PLANTED_ERROR_COUNTS}")
