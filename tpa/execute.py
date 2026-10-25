"""Layer 4 execution: every posting a decision can lead to, deterministic and through `post_journal`.

The judgment engine (workstream C) decides; this module does. After a human answers an
escalation, C calls `execute(cur, finding_id, decision, decided_by, at)`. The engine's own
auto-resolutions go through the same function, so a precedent-driven answer and a human
one post identically.

Accounts, following the posting contract in tpa.ledger:
  deduction taken   Dr 1250 pending          Cr 1200 receivable   (adjustment)
  cleared           Dr 2300 liability        Cr 1250 pending      (clearing, valid_time = origin)
  disputed          Dr 1260 disputed recv.   Cr 1250 pending      (dispute)
  top-up            Dr 4100 expense          Cr 2300 liability    (adjustment, valid_time = origin)
  re-estimate       reversal of the live accrual line + a new accrual at the new estimate
"""

import json
from datetime import date, datetime
from decimal import Decimal

import psycopg

from tpa.accrual import ZERO, money, rate, scan_back_segments, split_by_activity
from tpa.asof import terms_as_of
from tpa.constants import Account, Control as C, add_months, period_end, period_of, period_start
from tpa.controls import Hit, claim_dates, program_on, severity
from tpa.ledger import Line, post_journal, reverse_lines
from tpa.rows import all_rows, one_row

DECISIONS = ("clear", "top_up_and_clear", "dispute", "dispute_difference", "allocate", "reestimate", "hold",
             "release_accrual", "apply_candidates", "acknowledge")


class ExecutionError(RuntimeError):
    pass


def accrual_key(program_id: str, origin: str) -> str:
    return f"accrual:{program_id}:{origin}"


# ── reads ───────────────────────────────────────────────────────────────────
def liability(cur: psycopg.Cursor, program_id: str, origin: str, as_of: datetime) -> Decimal:
    cur.execute(
        """SELECT COALESCE(SUM(credit) - SUM(debit), 0) FROM ledger_entries
           WHERE account = %s AND program_id = %s AND valid_time = %s AND decision_time <= %s""",
        (Account.ACCRUED_TRADE_PROMO, program_id, period_end(origin), as_of),
    )
    return cur.fetchone()[0]


def accrual_posted(cur: psycopg.Cursor, program_id: str, origin: str) -> bool:
    cur.execute(
        """SELECT 1 FROM ledger_entries WHERE account = %s AND program_id = %s AND valid_time = %s
             AND entry_type IN ('accrual', 'opening') AND credit > 0 LIMIT 1""",
        (Account.ACCRUED_TRADE_PROMO, program_id, period_end(origin)),
    )
    return cur.fetchone() is not None


def original_accrual(cur: psycopg.Cursor, program_id: str, origin: str) -> dict | None:
    """The accrual journal posted at the origin period's own close: the one a restatement restates."""
    lines = all_rows(
        cur,
        """SELECT * FROM ledger_entries WHERE entry_type = 'accrual' AND program_id = %s
             AND period = %s AND valid_time = %s ORDER BY decision_time, id""",
        (program_id, origin, period_end(origin)),
    )
    if not lines:
        return None
    journal = lines[0]["journal_id"]
    mine = [l for l in lines if l["journal_id"] == journal]
    return {"journal_id": journal, "decision_time": mine[0]["decision_time"],
            "expense": next(l for l in mine if l["account"] == Account.TRADE_PROMO_EXPENSE),
            "liability": next(l for l in mine if l["account"] == Account.ACCRUED_TRADE_PROMO)}


def deduction_status(cur: psycopg.Cursor, deduction_id: str) -> str:
    """recorded | cleared | disputed | partly_disputed — read from the ledger, never stored."""
    cur.execute(
        """SELECT entry_type, account, SUM(debit) FROM ledger_entries
           WHERE deduction_id = %s AND entry_type IN ('clearing', 'dispute') AND debit > 0
           GROUP BY entry_type, account""",
        (deduction_id,),
    )
    kinds = {r[0] for r in cur.fetchall()}
    if not kinds:
        return "recorded"
    if kinds == {"clearing"}:
        return "cleared"
    if kinds == {"dispute"}:
        return "disputed"
    return "partly_disputed"


def unresolved_amount(cur: psycopg.Cursor, ded: dict) -> Decimal:
    """What is still sitting in 1250 for this deduction."""
    cur.execute(
        """SELECT COALESCE(SUM(debit) - SUM(credit), 0) FROM ledger_entries
           WHERE deduction_id = %s AND account = %s""",
        (ded["id"], Account.DEDUCTIONS_PENDING),
    )
    return cur.fetchone()[0]


# ── findings ────────────────────────────────────────────────────────────────
def controls(cur: psycopg.Cursor) -> dict[str, dict]:
    return {c["id"]: c for c in all_rows(cur, "SELECT * FROM controls WHERE status <> 'retired'")}


def _jsonable(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    raise TypeError(type(v).__name__)


def next_id(cur: psycopg.Cursor, table: str, prefix: str) -> str:
    cur.execute(f"SELECT COALESCE(MAX(substring(id FROM %s)::int), 0) + 1 FROM {table}", (rf"^{prefix}-(\d+)$",))
    return f"{prefix}-{cur.fetchone()[0]:04d}"


def raise_finding(cur: psycopg.Cursor, hit: Hit, *, period: str, customer_id: str, at: datetime,
                  control: dict) -> str:
    """Insert a finding. Evidence shape (shared with the escalation card and the interrogation box):
    summary, control{...}, measure, the ids of every row involved, and check-specific facts."""
    finding_id = next_id(cur, "findings", "FN")
    evidence = {
        "summary": hit.summary,
        "control": {"id": control["id"], "name": control["name"], "threshold": control["threshold"],
                    "threshold_unit": control["threshold_unit"], "owner_role": control["owner_role"],
                    "precedent_ids": control["precedent_ids"], "learned": control["learned"]},
        "measure": hit.measure,
        **hit.evidence,
    }
    cur.execute(
        """INSERT INTO findings (id, period, customer_id, control_id, severity, amount, exposure, confidence,
                                 state, conflict_type, evidence, created_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'open', %s, %s, %s)""",
        (finding_id, period, customer_id, hit.control_id, severity(hit.exposure), hit.amount, hit.exposure,
         hit.confidence, hit.conflict_type, json.dumps(evidence, default=_jsonable), at),
    )
    return finding_id


def finding(cur: psycopg.Cursor, finding_id: str) -> dict:
    row = one_row(cur, "SELECT * FROM findings WHERE id = %s", (finding_id,))
    if row is None:
        raise ExecutionError(f"no finding {finding_id}")
    return row


def set_finding_state(cur: psycopg.Cursor, finding_id: str, state: str, note: dict | None = None) -> None:
    if note:
        cur.execute("UPDATE findings SET state = %s, evidence = evidence || jsonb_build_object('resolution', %s::jsonb) "
                    "WHERE id = %s", (state, json.dumps(note, default=_jsonable), finding_id))
    else:
        cur.execute("UPDATE findings SET state = %s WHERE id = %s", (state, finding_id))


def open_findings_for(cur: psycopg.Cursor, deduction_id: str) -> list[dict]:
    return all_rows(cur, """SELECT * FROM findings WHERE state IN ('open', 'escalated')
                              AND evidence -> 'deduction_ids' ? %s ORDER BY id""", (deduction_id,))


# ── postings ────────────────────────────────────────────────────────────────
def record_deduction(cur: psycopg.Cursor, ded: dict, program_id: str | None, period: str, at: datetime) -> str:
    """The customer short-paid: move the amount from receivable to pending resolution."""
    return post_journal(
        cur, entry_type="adjustment", period=period, customer_id=ded["customer_id"], program_id=program_id,
        decision_time=at,
        lines=[Line(Account.DEDUCTIONS_PENDING, debit=ded["amount"], deduction_id=ded["id"],
                    memo=f"Deduction {ded['id']} ({ded['reason_code']}) taken {ded['taken_date']}, "
                         f"claims {ded['claimed_period']}"),
               Line(Account.ACCOUNTS_RECEIVABLE, credit=ded["amount"], deduction_id=ded["id"],
                    memo=f"Short-paid {ded['invoice_id'] or 'no invoice cited'}")],
    )


def clear(cur: psycopg.Cursor, ded: dict, program_id: str, origin: str, amount: Decimal, period: str,
          at: datetime, *, approved_by: str | None = None, finding_id: str | None = None, memo: str = "") -> str:
    """Clear an authorised amount against the origin's accrued liability. Never over-clears."""
    available = liability(cur, program_id, origin, at)
    if amount > available:
        raise ExecutionError(f"clearing {amount} against {accrual_key(program_id, origin)} would exceed the "
                             f"{available} accrued; top up first")
    vt = period_end(origin)
    return post_journal(
        cur, entry_type="clearing", period=period, customer_id=ded["customer_id"], program_id=program_id,
        decision_time=at, approved_by=approved_by, source_finding_id=finding_id,
        lines=[Line(Account.ACCRUED_TRADE_PROMO, debit=amount, valid_time=vt, deduction_id=ded["id"],
                    memo=memo or f"Clear {ded['id']} against {accrual_key(program_id, origin)}"),
               Line(Account.DEDUCTIONS_PENDING, credit=amount, valid_time=vt, deduction_id=ded["id"],
                    memo=memo or f"Clear {ded['id']} against {accrual_key(program_id, origin)}")],
    )


def top_up(cur: psycopg.Cursor, customer_id: str, program_id: str, origin: str, amount: Decimal, period: str,
           at: datetime, *, memo: str, approved_by: str | None = None, finding_id: str | None = None) -> str:
    vt = period_end(origin)
    return post_journal(
        cur, entry_type="adjustment", period=period, customer_id=customer_id, program_id=program_id,
        decision_time=at, approved_by=approved_by, source_finding_id=finding_id,
        lines=[Line(Account.TRADE_PROMO_EXPENSE, debit=amount, valid_time=vt, memo=memo),
               Line(Account.ACCRUED_TRADE_PROMO, credit=amount, valid_time=vt, memo=memo)],
    )


def dispute(cur: psycopg.Cursor, ded: dict, program_id: str | None, amount: Decimal, period: str, at: datetime,
            *, memo: str, approved_by: str | None = None, finding_id: str | None = None) -> str:
    vt = period_end(ded["claimed_period"])
    return post_journal(
        cur, entry_type="dispute", period=period, customer_id=ded["customer_id"], program_id=program_id,
        decision_time=at, approved_by=approved_by, source_finding_id=finding_id,
        lines=[Line(Account.DISPUTE_RECEIVABLE, debit=amount, valid_time=vt, deduction_id=ded["id"], memo=memo),
               Line(Account.DEDUCTIONS_PENDING, credit=amount, valid_time=vt, deduction_id=ded["id"], memo=memo)],
    )


def disputed_amount(cur: psycopg.Cursor, deduction_id: str) -> Decimal:
    cur.execute("SELECT COALESCE(SUM(debit) - SUM(credit), 0) FROM ledger_entries WHERE deduction_id = %s AND account = %s",
                (deduction_id, Account.DISPUTE_RECEIVABLE))
    return cur.fetchone()[0]


def withdraw_dispute(cur: psycopg.Cursor, ded: dict, program_id: str | None, period: str, at: datetime, *,
                     memo: str, finding_id: str | None = None) -> str | None:
    """Take back our own dispute: the amount returns to pending, ready to clear."""
    amount = disputed_amount(cur, ded["id"])
    if amount <= 0:
        return None
    vt = period_end(ded["claimed_period"])
    return post_journal(
        cur, entry_type="dispute", period=period, customer_id=ded["customer_id"], program_id=program_id,
        decision_time=at, source_finding_id=finding_id,
        lines=[Line(Account.DEDUCTIONS_PENDING, debit=amount, valid_time=vt, deduction_id=ded["id"], memo=memo),
               Line(Account.DISPUTE_RECEIVABLE, credit=amount, valid_time=vt, deduction_id=ded["id"], memo=memo)],
    )


def scan_back_estimate(cur: psycopg.Cursor, program_id: str, origin: str, terms_known_at: datetime,
                       volume_known_at: datetime) -> tuple[Decimal, list, int]:
    """(amount, segments, net cases) for a scan-back origin: volume as known at one time, terms at another."""
    shipments = all_rows(cur, "SELECT * FROM shipments WHERE program_id = %s AND period = %s AND available_at <= %s",
                         (program_id, origin, volume_known_at.date()))
    cur.execute("SELECT shipment_id, SUM(cases) FROM returns WHERE shipment_id = ANY(%s) AND available_at <= %s "
                "GROUP BY shipment_id", ([s["id"] for s in shipments], volume_known_at.date()))
    returned = dict(cur.fetchall())
    first = terms_as_of(cur, program_id, period_end(origin), terms_known_at)
    segs = scan_back_segments(shipments, returned, first["projected_redemption"],
                              lambda on: terms_as_of(cur, program_id, on, terms_known_at))
    return sum((s.amount for s in segs), ZERO), segs, sum(s.cases for s in segs)


def segments_memo(program_id: str, origin: str, segs, projected: Decimal, known: datetime) -> str:
    parts = "; ".join(f"{s.cases:,} net cases × {rate(projected)} × ${rate(s.rate)}/case = ${s.amount:,}" for s in segs)
    return f"Accrue {program_id} {origin} at projected redemption: {parts} (terms as known {known:%Y-%m-%d})"


def reestimate(cur: psycopg.Cursor, program_id: str, origin: str, period: str, at: datetime, *,
               reason: str, finding_id: str | None = None) -> str | None:
    """Re-make an origin's scan-back estimate on the volume known now (returns netted) and the terms
    the live accrual was made on: reverse the live line, post the new one. A restated origin gets a
    delta adjustment instead, so the catch-up layer is never reversed."""
    live = all_rows(
        cur,
        """SELECT * FROM ledger_entries e WHERE e.entry_type = 'accrual' AND e.program_id = %s AND e.valid_time = %s
             AND NOT EXISTS (SELECT 1 FROM ledger_entries r WHERE r.reversal_of = e.id)
           ORDER BY e.decision_time DESC, e.id""",
        (program_id, period_end(origin)),
    )
    if not live:
        return None
    journal = live[0]["journal_id"]
    lines = [l for l in live if l["journal_id"] == journal]
    posted = sum((l["credit"] for l in lines if l["account"] == Account.ACCRUED_TRADE_PROMO), ZERO)
    basis = lines[0]["decision_time"]
    new, segs, _ = scan_back_estimate(cur, program_id, origin, basis, at)
    if new == posted:
        return None
    customer_id = lines[0]["customer_id"]
    restated = one_row(cur, "SELECT 1 AS x FROM ledger_entries WHERE entry_type = 'restatement' AND program_id = %s "
                            "AND valid_time = %s LIMIT 1", (program_id, period_end(origin)))
    if restated:
        delta = posted - new
        memo = f"Re-estimate {accrual_key(program_id, origin)}: {reason}"
        return post_journal(
            cur, entry_type="adjustment", period=period, customer_id=customer_id, program_id=program_id,
            decision_time=at, source_finding_id=finding_id,
            lines=[Line(Account.ACCRUED_TRADE_PROMO, debit=delta, valid_time=period_end(origin), memo=memo),
                   Line(Account.TRADE_PROMO_EXPENSE, credit=delta, valid_time=period_end(origin), memo=memo)],
        )
    reverse_lines(cur, [l["id"] for l in lines], period=period, decision_time=at,
                  memo=f"Reverse {journal}: {reason}")
    first = terms_as_of(cur, program_id, period_end(origin), basis)
    memo = segments_memo(program_id, origin, segs, first["projected_redemption"], basis) + f". Re-made: {reason}"
    return post_journal(
        cur, entry_type="accrual", period=period, customer_id=customer_id, program_id=program_id,
        decision_time=at, source_finding_id=finding_id,
        lines=[Line(Account.TRADE_PROMO_EXPENSE, debit=new, valid_time=period_end(origin), memo=memo),
               Line(Account.ACCRUED_TRADE_PROMO, credit=new, valid_time=period_end(origin), memo=memo)],
    )


def release_accrual(cur: psycopg.Cursor, customer_id: str, program_id: str, origin: str, period: str, at: datetime,
                    *, approved_by: str, finding_id: str | None = None) -> str | None:
    """Release what is left of a stale accrual back to expense."""
    left = liability(cur, program_id, origin, at)
    if left <= 0:
        return None
    memo = f"Release stale accrual {accrual_key(program_id, origin)}"
    return post_journal(
        cur, entry_type="adjustment", period=period, customer_id=customer_id, program_id=program_id,
        decision_time=at, approved_by=approved_by, source_finding_id=finding_id,
        lines=[Line(Account.ACCRUED_TRADE_PROMO, debit=left, valid_time=period_end(origin), memo=memo),
               Line(Account.TRADE_PROMO_EXPENSE, credit=left, valid_time=period_end(origin), memo=memo)],
    )


# ── clearing with the mined tolerance ───────────────────────────────────────
def mined_tolerance(cur: psycopg.Cursor) -> Decimal:
    """DED-GT-ACCRUAL's mined threshold: the over-claim the agent may true up on its own."""
    cur.execute("SELECT threshold FROM controls WHERE id = %s", (C.DED_GT_ACCRUAL,))
    row = cur.fetchone()
    return row[0] if row else ZERO


def settle(cur: psycopg.Cursor, ded: dict, program_id: str, origin: str, period: str, at: datetime, *,
           tolerance: Decimal, approved_by: str | None = None, finding_id: str | None = None,
           amount: Decimal | None = None) -> Decimal:
    """Clear `amount` (default: what is pending) against the origin. An over-claim within the mined
    tolerance is trued up and cleared; a larger one is left for judgment. Returns the excess
    that was NOT settled (zero when everything cleared)."""
    amount = unresolved_amount(cur, ded) if amount is None else amount
    available = liability(cur, program_id, origin, at)
    excess = amount - available
    if excess > tolerance and approved_by is None:
        return excess
    if excess > 0:
        top_up(cur, ded["customer_id"], program_id, origin, excess, period, at, approved_by=approved_by,
               finding_id=finding_id,
               memo=f"True-up {accrual_key(program_id, origin)}: claims exceed accrued liability by ${excess:,}"
                    + (" — within the mined tolerance" if approved_by is None else f", approved by {approved_by}"))
    clear(cur, ded, program_id, origin, amount, period, at, approved_by=approved_by, finding_id=finding_id)
    return ZERO


def authorise(cur: psycopg.Cursor, ded: dict, program_id: str, period: str, at: datetime, *,
              origin: str | None = None, amount: Decimal | None = None, deferred: list | None = None,
              finding_id: str | None = None) -> str | None:
    """The agent clears an authorised amount (default: all that is pending) on its own authority.
    An origin not yet accrued this period is deferred to the close; an over-claim beyond the
    mined tolerance becomes a DED-GT-ACCRUAL finding, whose id is returned."""
    origin = origin or ded["claimed_period"]
    if not accrual_posted(cur, program_id, origin) and origin >= period and deferred is not None:
        deferred.append((ded, program_id))
        return None
    excess = settle(cur, ded, program_id, origin, period, at, tolerance=mined_tolerance(cur), amount=amount,
                    finding_id=finding_id)
    if excess <= 0:
        return None
    return over_claim_finding(cur, ded, program_id, origin, excess, period, at)


def over_claim_finding(cur: psycopg.Cursor, ded: dict, program_id: str, origin: str, excess: Decimal,
                       period: str, at: datetime) -> str:
    key = accrual_key(program_id, origin)
    existing = one_row(cur, """SELECT id FROM findings WHERE control_id = %s AND conflict_type = 'over_claim'
                                 AND period = %s AND state IN ('open', 'escalated') AND evidence ->> 'accrual_key' = %s""",
                       (C.DED_GT_ACCRUAL, period, key))
    if existing:
        cur.execute("""UPDATE findings SET amount = amount + %s, exposure = exposure + %s,
                         evidence = jsonb_set(evidence, '{deduction_ids}', (evidence -> 'deduction_ids') || to_jsonb(%s::text))
                       WHERE id = %s""", (ded["amount"], excess, ded["id"], existing["id"]))
        return existing["id"]
    cur.execute("""SELECT COALESCE(SUM(credit), 0), COALESCE(SUM(debit), 0) FROM ledger_entries
                   WHERE account = %s AND program_id = %s AND valid_time = %s AND decision_time <= %s""",
                (Account.ACCRUED_TRADE_PROMO, program_id, period_end(origin), at))
    accrued, cleared = cur.fetchone()
    hit = Hit(C.DED_GT_ACCRUAL, "over_claim", excess, ded["amount"], excess,
              f"Claims for {origin} on {program_id} exceed the accrued liability: {ded['id']} for ${ded['amount']:,} "
              f"leaves ${excess:,} uncovered (accrued ${accrued:,}, already cleared ${cleared:,}).",
              {"deduction_ids": [ded["id"]], "program_id": program_id, "origin": origin, "accrual_key": key,
               "accrued": accrued, "cleared": cleared, "excess": excess})
    return raise_finding(cur, hit, period=period, customer_id=ded["customer_id"], at=at,
                         control=controls(cur)[C.DED_GT_ACCRUAL])


# ── decisions ───────────────────────────────────────────────────────────────
def _deductions_of(cur: psycopg.Cursor, f: dict) -> list[dict]:
    ids = (f["evidence"] or {}).get("deduction_ids", [])
    return all_rows(cur, "SELECT * FROM deductions WHERE id = ANY(%s) ORDER BY available_at, id", (ids,)) if ids else []


UNSIGNED = ("OPEN", "ACCRUED", "CONTROLLED", "ESCALATED", "REVIEWED")


def closing_period(cur: psycopg.Cursor, f: dict, at: datetime) -> str:
    """Where a decision on a finding posts. While the finding's period is still being closed (not yet
    signed), it posts there: a release the close reviewer approves during October's close is October's
    adjustment, so October's gates see it. Once that period is signed it posts to the period `at` is in."""
    current = period_of(at.date())
    if f["period"] < current:
        row = one_row(cur, "SELECT state FROM periods WHERE period = %s AND customer_id = %s",
                      (f["period"], f["customer_id"]))
        if row and row["state"] in UNSIGNED:
            return f["period"]
    return current


def execute(cur: psycopg.Cursor, finding_id: str, decision: str, decided_by: str, at: datetime, *,
            period: str | None = None, note: str = "") -> list[str]:
    """Carry out a decision on a finding and resolve it. Returns the journals and follow-up findings.

    decisions
      clear               the deductions are authorised: the agent clears them within its tolerance;
                          anything over becomes a DED-GT-ACCRUAL finding
      top_up_and_clear    DED-GT-ACCRUAL: the decider approves topping the accrual up, then clear
      dispute             dispute every deduction in full (duplicates, no proof, outside window)
      dispute_difference  clear what the program or backup supports, dispute the rest
      allocate            straddles: clear the claim against each origin by activity days
      reestimate          RETURNS-NOT-NETTED: re-make the origin accrual net of returns
      release_accrual     STALE-ACCRUAL: release the accrual to expense
      apply_candidates    STALE-ACCRUAL: clear the unmatched deductions the card names against the
                          accrual, then release only what is left
      hold                leave everything pending; the finding stays escalated
      acknowledge         nothing to post (e.g. redemption drift): noted, resolved
    A source-of-truth answer decides *what* is authorised; it never approves a posting, so
    clears go through the agent's own tolerance. Only top_up_and_clear and release_accrual
    post on the decider's authority. The caller (C) checks segregation of duties first.
    """
    if decision not in DECISIONS:
        raise ExecutionError(f"unknown decision {decision!r}")
    f = finding(cur, finding_id)
    ev = f["evidence"] or {}
    period = period or closing_period(cur, f, at)
    journals: list[str] = []
    approver = None if decided_by == "agent" else decided_by
    tolerance = mined_tolerance(cur)

    def agent_clears(ded, program_id, amount=None, origin=None):
        follow_up = authorise(cur, ded, program_id, period, at, origin=origin, amount=amount, finding_id=finding_id)
        journals.append(f"over_claim:{follow_up}" if follow_up else f"cleared:{ded['id']}")

    if decision == "hold":
        set_finding_state(cur, finding_id, "escalated", {"decision": decision, "by": decided_by, "at": at, "note": note})
        return journals

    if decision == "acknowledge":
        pass
    elif decision == "reestimate":
        j = reestimate(cur, ev["program_id"], ev["origin"], period, at, finding_id=finding_id,
                       reason=ev.get("summary", "") + (f" ({note})" if note else ""))
        journals += [j] if j else []
    elif decision == "apply_candidates":
        if approver is None:
            raise ExecutionError("matching an unmatched deduction to an accrual needs a human approver")
        program_id, origin = ev["program_id"], ev["origin"]
        for ded_id in ev.get("candidate_deduction_ids", []):
            ded = one_row(cur, "SELECT * FROM deductions WHERE id = %s", (ded_id,))
            amount = min(unresolved_amount(cur, ded), liability(cur, program_id, origin, at))
            if amount > 0:
                journals.append(clear(cur, ded, program_id, origin, amount, period, at, approved_by=approver,
                                      finding_id=finding_id,
                                      memo=f"Apply unmatched {ded_id} to {accrual_key(program_id, origin)}: {note}"))
        j = release_accrual(cur, f["customer_id"], program_id, origin, period, at, approved_by=decided_by,
                            finding_id=finding_id)
        journals += [j] if j else []
    elif decision == "release_accrual":
        program_id, origin = ev["program_id"], ev["origin"]
        j = release_accrual(cur, f["customer_id"], program_id, origin, period, at, approved_by=decided_by,
                            finding_id=finding_id)
        journals += [j] if j else []
    else:
        for ded in _deductions_of(cur, f):
            pending = unresolved_amount(cur, ded)
            if pending <= 0:
                continue
            program_id = ev.get("program_id") or ded["program_id"]
            if decision == "dispute":
                journals.append(dispute(cur, ded, program_id, pending, period, at, approved_by=approver,
                                        finding_id=finding_id,
                                        memo=f"Dispute {ded['id']}: {note or ev.get('summary', f['control_id'])}"))
            elif decision == "clear":
                agent_clears(ded, program_id)
            elif decision == "top_up_and_clear":
                if approver is None:
                    raise ExecutionError("topping up beyond tolerance needs a human approver")
                settle(cur, ded, program_id, ev.get("origin") or ded["claimed_period"], period, at,
                       tolerance=tolerance, approved_by=approver, finding_id=finding_id)
                journals.append(f"cleared:{ded['id']}")
            elif decision == "dispute_difference":
                supported = min(_supported_amount(cur, ded, ev, at), pending)
                if supported < pending:
                    journals.append(dispute(cur, ded, program_id, pending - supported, period, at,
                                            approved_by=approver, finding_id=finding_id,
                                            memo=f"Dispute unsupported ${pending - supported:,} of {ded['id']}: "
                                                 f"{note or ev.get('summary', '')}"))
                if supported > 0:
                    agent_clears(ded, program_id, amount=supported)
            elif decision == "allocate":
                start, end = claim_dates(ded)
                origins = _origins_between(start, end)
                basis = terms_as_of(cur, program_id, start, at)
                shares = split_by_activity(pending, start, end, [(period_start(o), period_end(o)) for o in origins],
                                           basis and basis["program_type"])
                for origin, share in zip(origins, shares):
                    if share <= 0:
                        continue
                    o_start = max(start, period_start(origin))
                    term = terms_as_of(cur, program_id, o_start, at)
                    target = program_id if term and term["window_start"] <= o_start <= term["window_end"] else \
                        _program_on(cur, ded["customer_id"], term["program_type"] if term else None, o_start, at)
                    agent_clears(ded, target, amount=share, origin=origin)
    set_finding_state(cur, finding_id, "resolved" if decided_by != "agent" else "auto_resolved",
                      {"decision": decision, "by": decided_by, "at": at, "note": note, "journals": journals})
    return journals


def _supported_amount(cur: psycopg.Cursor, ded: dict, ev: dict, at: datetime) -> Decimal:
    if ev.get("supported"):
        return Decimal(ev["supported"])
    if ev.get("program_rate"):
        backup = one_row(cur, "SELECT * FROM claim_backup WHERE deduction_id = %s", (ded["id"],))
        units = backup["scan_units"] if backup and backup["scan_units"] else None
        if units:
            return money(Decimal(units) * Decimal(ev["program_rate"]))
    return ZERO


def _origins_between(start: date, end: date) -> list[str]:
    out, p = [], period_of(start)
    while p <= period_of(end):
        out.append(p)
        p = add_months(p, 1)
    return out


def _program_on(cur: psycopg.Cursor, customer_id: str, program_type: str | None, on: date, at: datetime) -> str:
    program_id = program_on(cur, customer_id, program_type, on, at)
    if program_id is None:
        raise ExecutionError(f"no {program_type} program for {customer_id} on {on}")
    return program_id
