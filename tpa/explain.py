"""The interrogation box: ask any number and trace it to the entry behind it.

`chain(cur, entry_id)` is deterministic: the rule that posted the line, the terms it used and the
clause they come from, the inputs, what was known at the time (and what wasn't yet), who approved
it, and what later reversed or restated it. Every step names the record ids it rests on.

`ask(cur, question)` resolves the records a question is about (ids it mentions, else the month
and program it names) and answers from their chains. The model may phrase the answer; a reply
that introduces any number or id not in the evidence is dropped for the plain chain.
"""

import json
import re
from datetime import datetime
from decimal import Decimal

import psycopg

from tpa import model
from tpa.accrual import rate
from tpa.asof import entry_history, liability_outstanding, terms_as_of
from tpa.constants import Account, period_end, period_of
from tpa.execute import _jsonable
from tpa.rows import all_rows, one_row

RULES = {
    "opening": "Opening balance carried in from the prior year's books",
    "revenue": "Recognise revenue at shipment; off-invoice allowances net against it",
    "accrual": "Accrue promo liability at projected redemption when the product ships",
    "reversal": "Reverse the prior accrual so it can be re-made on what is known now",
    "clearing": "Clear an authorised deduction against the accrued liability",
    "dispute": "Hold the unsupported part of a deduction as a disputed receivable",
    "restatement": "Restate a closed period when its terms change after the close",
    "adjustment": "Adjust the accrual: a true-up, a release, or recording a deduction",
}
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}
ID = re.compile(r"\b(?:JE-\d+(?:-\d+)?|DD-\d+|FN-\d+|ESC-\d+|AM-\d+|TP-\d+)\b")


def money(x) -> str:
    return f"${Decimal(x):,.2f}"


def _step(label: str, text: str, ids: list[str] | None = None) -> dict:
    return {"label": label, "text": text, "ids": [i for i in (ids or []) if i]}


def chain(cur: psycopg.Cursor, entry_id: str) -> dict | None:
    h = entry_history(cur, entry_id)
    if h is None:
        return None
    line, known = h["line"], h["line"]["decision_time"]
    amount = line["credit"] or line["debit"]
    customer = one_row(cur, "SELECT name FROM customers WHERE id = %s", (line["customer_id"],))
    program = line["program_id"] and one_row(cur, "SELECT * FROM trade_programs WHERE id = %s", (line["program_id"],))
    origin = period_of(line["valid_time"])
    head = (f"{line['journal_id']} · {origin} {line['entry_type']} · {customer['name'] if customer else line['customer_id']}"
            f"{' ' + program['program_type'].replace('_', '-') if program else ''} · {money(amount)}")
    steps = []

    finding = h["finding"]
    rule = RULES.get(line["entry_type"], line["entry_type"])
    if finding:
        control = one_row(cur, "SELECT name FROM controls WHERE id = %s", (finding["control_id"],))
        rule += f"; raised by {finding['id']} ({control['name'] if control else finding['control_id']})"
    steps.append(_step("rule", rule, [finding and finding["id"]]))

    if program:
        term = terms_as_of(cur, program["id"], line["valid_time"], known)
        if term:
            unit = "/case" if term["rate_unit"] == "per_case" else ""
            text = (f"{program['id']} clause {term['source_clause_id'] or '—'}, rate ${rate(term['rate'])}{unit}"
                    + (f", projected redemption {rate(term['projected_redemption'])}" if term["projected_redemption"] else ""))
            steps.append(_step("terms", text, [program["id"], term["id"]]))

    if line["entry_type"] in ("accrual", "restatement") and program and program["program_type"] == "scan_back":
        ships = all_rows(cur, """SELECT id, cases FROM shipments WHERE program_id = %s AND period = %s
                                   AND available_at <= %s ORDER BY id""", (program["id"], origin, known.date()))
        if ships:
            steps.append(_step("inputs", f"{ships[0]['id']}..{ships[-1]['id']}, {sum(s['cases'] for s in ships):,} cases "
                                         f"shipped in {origin}", [ships[0]["id"], ships[-1]["id"]]))
    if h["deduction"]:
        d = h["deduction"]
        backup = one_row(cur, "SELECT id FROM claim_backup WHERE deduction_id = %s AND available_at <= %s",
                         (d["id"], known.date()))
        steps.append(_step("inputs", f"{d['id']} for {money(d['amount'])} claiming {d['claimed_period']}"
                                     f"{', backup ' + backup['id'] if backup else ', no backup on file'}",
                           [d["id"], backup and backup["id"]]))

    late = program and all_rows(cur, """SELECT id, effective_date, available_at FROM program_amendments
                                         WHERE program_id = %s AND effective_date <= %s AND available_at > %s""",
                                (program["id"], line["valid_time"], known.date()))
    knew = f"{known:%Y-%m-%d %H:%M}"
    if late:
        knew += " — " + "; ".join(f"{a['id']} (effective {a['effective_date']}) not yet in system, arrived "
                                  f"{a['available_at']}" for a in late)
    steps.append(_step("knew-at", knew, [a["id"] for a in late or []]))

    if h["approved_by"]:
        steps.append(_step("approved", f"{h['approved_by']['name']} ({h['approved_by']['id']}), {known:%Y-%m-%d %H:%M}"))
    else:
        steps.append(_step("approved", "the agent, within a mined control: no human authority was needed"
                           if line["entry_type"] not in ("opening", "revenue", "accrual", "reversal") else
                           "posted by the engine under the posting contract"))
    signoff = one_row(cur, """SELECT signed_by, signed_at FROM period_signoffs WHERE period = %s AND customer_id = %s
                              ORDER BY signed_at LIMIT 1""", (line["period"], line["customer_id"]))
    if signoff:
        steps.append(_step("signed", f"{line['period']} signed by {signoff['signed_by']}, {signoff['signed_at']:%Y-%m-%d %H:%M}"))

    for r in h["restated_by"]:
        delta = (r["credit"] or 0) - (r["debit"] or 0) if line["credit"] else (r["debit"] or 0) - (r["credit"] or 0)
        steps.append(_step("restated", f"{r['journal_id']} on {r['decision_time']:%Y-%m-%d} "
                                       f"({'+' if delta >= 0 else '−'}{money(abs(delta))})", [r["journal_id"]]))
    for r in h["reversed_by"]:
        steps.append(_step("reversed", f"{r['journal_id']} on {r['decision_time']:%Y-%m-%d}", [r["journal_id"]]))
    if finding and (finding["evidence"] or {}).get("precedent_id"):
        p = one_row(cur, "SELECT * FROM precedents WHERE id = %s", (finding["evidence"]["precedent_id"],))
        if p:
            overruled = f", overruling the agent's recommendation to {p['overrode']}" if p["overrode"] else ""
            steps.append(_step("precedent", f"{p['id']}: {p['decision']} by {p['decided_by']}{overruled} — {p['reasoning']}",
                               [p["id"]]))
    return {"entry_id": entry_id, "head": head, "steps": steps, "memo": line["memo"]}


def as_text(c: dict) -> str:
    width = max(len(s["label"]) for s in c["steps"])
    return "\n".join([c["head"], *(f"  {s['label']:<{width}}  {s['text']}" for s in c["steps"])])


# ── resolving a question to entries ─────────────────────────────────────────
def _line_for_journal(cur, journal_id: str) -> str | None:
    row = one_row(cur, """SELECT id FROM ledger_entries WHERE journal_id = %s
                          ORDER BY (account = %s) DESC, id LIMIT 1""", (journal_id, Account.ACCRUED_TRADE_PROMO))
    return row and row["id"]


def resolve(cur: psycopg.Cursor, question: str) -> list[str]:
    """The ledger lines a question is about: by the ids it names, else by month and program."""
    lines: list[str] = []
    for ref in dict.fromkeys(ID.findall(question)):
        if re.fullmatch(r"JE-\d+-\d+", ref):
            lines.append(ref)
        elif ref.startswith("JE-"):
            lines.append(_line_for_journal(cur, ref))
        elif ref.startswith("DD-"):
            lines += [r["id"] for r in all_rows(cur, """SELECT id FROM ledger_entries WHERE deduction_id = %s
                                                       AND account = %s ORDER BY id""", (ref, Account.ACCRUED_TRADE_PROMO))]
        elif ref.startswith("FN-"):
            lines += [r["id"] for r in all_rows(cur, """SELECT id FROM ledger_entries WHERE source_finding_id = %s
                                                       AND account = %s ORDER BY id""", (ref, Account.ACCRUED_TRADE_PROMO))]
        elif ref.startswith("AM-"):
            lines += [r["id"] for r in all_rows(cur, """SELECT e.id FROM ledger_entries e JOIN program_amendments a
                                                       ON a.program_id = e.program_id WHERE a.id = %s
                                                       AND e.entry_type = 'restatement' AND e.account = %s ORDER BY e.id""",
                                                (ref, Account.ACCRUED_TRADE_PROMO))]
    if lines:
        return [x for x in dict.fromkeys(lines) if x][:8]
    months = [MONTHS[w] for w in re.findall(r"[a-z]+", question.lower()) if w in MONTHS]
    programs = re.findall(r"\bTP-\d+\b", question) or ["TP-0214"]
    for m in months[:2]:
        period = f"2026-{m:02d}"
        row = one_row(cur, """SELECT id FROM ledger_entries WHERE entry_type = 'accrual' AND program_id = ANY(%s)
                                AND valid_time = %s AND account = %s ORDER BY decision_time LIMIT 1""",
                      (programs, period_end(period), Account.ACCRUED_TRADE_PROMO))
        if row:
            lines.append(row["id"])
    return lines


def knowledge(cur: psycopg.Cursor, question: str) -> dict | None:
    """'What did it know in March?': the books and terms as they stood at the end of that month."""
    m = re.search(r"\bknow\w*\b.*\b(" + "|".join(MONTHS) + r")\b", question.lower())
    if not m:
        return None
    period = f"2026-{MONTHS[m.group(1)]:02d}"
    at = datetime.combine(period_end(period), datetime.max.time())
    term = terms_as_of(cur, "TP-0214", period_end(period), at)
    liab = liability_outstanding(cur, at).get(("TP-0214", period_end(period)), Decimal("0"))
    cur.execute("SELECT COUNT(*) FROM findings WHERE created_at <= %s", (at,))
    findings = cur.fetchone()[0]
    cur.execute("SELECT id, effective_date, available_at FROM program_amendments WHERE available_at > %s", (at.date(),))
    unknown = cur.fetchall()
    return {"as_of": at, "period": period, "tp0214_rate": term and term["rate"], "tp0214_outstanding": liab,
            "findings_raised_by_then": findings,
            "not_yet_known": [{"amendment_id": a, "effective": e, "arrived": v} for a, e, v in unknown]}


NO = re.compile(r"\b(said no|says no|say no|overrul\w*|reject\w*|turned down|disagree\w*)\b", re.I)


def overrulings(cur: psycopg.Cursor) -> list[dict]:
    """Every time a person turned down the agent's recommendation, and what followed from it."""
    rows = all_rows(cur, """SELECT p.*, (SELECT COUNT(*) FROM findings f WHERE f.evidence ->> 'precedent_id' = p.id
                                         AND f.id <> e.finding_id) AS followed
                            FROM precedents p JOIN escalations e ON e.id = p.from_escalation_id
                            WHERE p.overrode IS NOT NULL ORDER BY p.decided_at, p.id""")
    return [{"precedent_id": r["id"], "control_id": r["control_id"], "customer_id": r["customer_id"],
             "recommended": r["overrode"], "decided": r["decision"], "decided_by": r["decided_by"],
             "decided_at": r["decided_at"], "reasoning": r["reasoning"], "later_cases_following_it": r["followed"]}
            for r in rows]


def ask(cur: psycopg.Cursor, question: str) -> dict:
    if NO.search(question):
        said_no = overrulings(cur)
        if said_no:
            text = "\n".join(f"{o['decided_by']} overruled the agent on {o['control_id']} ({o['customer_id']}) on "
                             f"{o['decided_at']:%Y-%m-%d}: recommended {o['recommended']}, decided {o['decided']}. "
                             f"\"{o['reasoning']}\" That became {o['precedent_id']}; "
                             f"{o['later_cases_following_it']} later case(s) followed it without asking."
                             for o in said_no)
            return {"question": question, "answer": text, "chains": [], "knowledge": {"overrulings": said_no},
                    "drafted_by": "agent"}
    chains = [c for c in (chain(cur, e) for e in resolve(cur, question)) if c]
    known = knowledge(cur, question)
    if not chains and not known:
        return {"question": question, "answer": "I couldn't tie that to a record. Name an entry (JE-…), a deduction "
                                                "(DD-…), a finding (FN-…) or a month, and I'll trace it.",
                "chains": [], "knowledge": None, "drafted_by": "agent"}
    plain = "\n\n".join(as_text(c) for c in chains)
    if known:
        plain = (f"As of {known['as_of']:%Y-%m-%d}: TP-0214 at ${rate(known['tp0214_rate'])}/case, "
                 f"{money(known['tp0214_outstanding'])} accrued and unclaimed for its {known['period']} shipments, "
                 f"{known['findings_raised_by_then']} findings raised. Not yet known: "
                 + (", ".join(f"{u['amendment_id']} (effective {u['effective']}, arrived {u['arrived']})"
                              for u in known["not_yet_known"]) or "nothing") + ".") + ("\n\n" + plain if plain else "")
    evidence = json.dumps({"chains": chains, "knowledge": known}, default=_jsonable)
    drafted = model.ask(
        "You answer a finance judge's question about an autonomous accounting agent's books. Answer only from "
        "the evidence given, in three sentences or fewer, citing record ids. Never compute a new number; quote "
        "the evidence's numbers exactly.", f"Question: {question}\n\nEvidence:\n{evidence}", max_tokens=400)
    ok = drafted and model.facts(drafted) <= model.facts(plain) | model.facts(evidence)
    return {"question": question, "answer": drafted if ok else plain, "chains": chains, "knowledge": known,
            "drafted_by": "model" if ok else "agent"}
