"""Layer 1: read the trade agreements and amendments into `program_terms`, each term citing its clause.

Deterministic: one pattern per clause type, and a document that doesn't yield a required term is
refused (an unreadable agreement is escalated, never guessed). With the model on, Claude reads the
same document as a second reader; a disagreement is reported against the clause, and the
deterministic reading still stands, since the model never sets a number.

Documents are read the day they reach us, and the terms carry that as their decision time:
    agreements   at onboarding for those already here, else on their available_at day
    amendments   on their available_at day, an hour before the engine looks for restatements
The generator's `program_terms_truth.json` is the answer key for this module, never its input.
"""

import json
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import psycopg

from tpa import model
from tpa.asof import terms_as_of
from tpa.rows import all_rows, one_row

READ_AT = time(9)
DATE = r"(\d{4}-\d{2}-\d{2})"
MONEY = r"\$([\d,]+(?:\.\d+)?)"

# (program_type, clause pattern that states the rate, rate unit, base)
RATE_CLAUSES = (
    ("scan_back", rf"^(4\.2) The allowance is {MONEY} per case", "per_case", "scan_units"),
    ("off_invoice", rf"^(2\.1) Supplier grants an off-invoice allowance of {MONEY} per case shipped", "per_case",
     "shipped_cases"),
    ("mdf", rf"^(2\.1) Supplier will fund market development activities of {MONEY} for the term", "lump_sum", "fixed"),
    ("display", rf"^(3\.\d) .*?{MONEY} per (?:feature )?event", "lump_sum", "fixed"),
)
# Wording that leaves a term open to two readings: reported with the extraction, for the record.
AMBIGUOUS = re.compile(r"\band/or\b|\bmay be counted\b|\bcontingent on\b", re.I)


class ExtractionError(ValueError):
    pass


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _money(s: str) -> Decimal:
    return Decimal(s.replace(",", ""))


def read_agreement(text: str) -> dict:
    """The terms an agreement states, with the clause each comes from."""
    head = re.search(r"TRADE PROMOTION AGREEMENT (TP-\d+)", text)
    term = re.search(rf"runs from {DATE} through {DATE}", text)
    customer = re.search(r'and (.+?) \("Customer"\)', text)
    if not (head and term and customer):
        raise ExtractionError("not a trade promotion agreement: no program id, term or customer")
    for program_type, pattern, unit, base in RATE_CLAUSES:
        m = re.search(pattern, text, re.M)
        if m:
            break
    else:
        raise ExtractionError(f"{head.group(1)}: no clause states a rate")
    projected = re.search(r"projected redemption (\d+)%", text)
    if program_type == "scan_back" and not projected:
        raise ExtractionError(f"{head.group(1)}: a scan-back program needs a projected redemption to accrue on")
    return {
        "program_id": head.group(1), "customer_name": customer.group(1), "program_type": program_type,
        "rate": _money(m.group(2)), "rate_unit": unit, "base_definition": base,
        "projected_redemption": (Decimal(projected.group(1)) / 100) if projected else None,
        "window_start": _d(term.group(1)), "window_end": _d(term.group(2)),
        "requires_proof": bool(re.search(r"requires proof of performance", text)),
        "source_clause_id": f"{head.group(1)}#{m.group(1)}",
        "ambiguities": [line.strip() for line in text.splitlines() if AMBIGUOUS.search(line)],
    }


def read_amendment(text: str) -> dict:
    head = re.search(r"AMENDMENT (AM-\d+) TO TRADE PROMOTION AGREEMENT (TP-\d+)", text)
    change = re.search(rf"Clause (\d\.\d) is replaced in full, effective {DATE}", text)
    if not (head and change):
        raise ExtractionError("not an amendment: no id, program or replaced clause")
    rate = re.search(rf"^{re.escape(change.group(1))} .*?{MONEY} per", text, re.M)
    if not rate:
        raise ExtractionError(f"{head.group(1)}: the replacement clause {change.group(1)} states no rate")
    return {"amendment_id": head.group(1), "program_id": head.group(2), "clause": change.group(1),
            "effective_date": _d(change.group(2)), "rate": _money(rate.group(1))}


def second_reader(text: str, reading: dict) -> list[str]:
    """With the model on: Claude reads the document too. Returns the fields where it disagrees."""
    fields = ("program_type", "rate", "window_start", "window_end", "projected_redemption", "requires_proof")
    reply = model.ask_json("You extract structured terms from a trade promotion agreement. Use only the text.",
                           f"Fields: {', '.join(fields)} (dates YYYY-MM-DD, rate as a number, projected_redemption "
                           f"as a fraction or null).\n\n{text}")
    if not reply:
        return []
    out = []
    for f in fields:
        mine, theirs = reading.get(f), reply.get(f)
        if mine is None and theirs is None:
            continue
        try:
            same = Decimal(str(mine)) == Decimal(str(theirs)) if isinstance(mine, Decimal) else str(mine) == str(theirs)
        except Exception:
            same = False
        if not same:
            out.append(f"{f}: read {mine}, second reader {theirs}")
    return out


def _next_term_id(cur) -> str:
    cur.execute(r"SELECT COALESCE(MAX(substring(id FROM '^PT-(\d+)$')::int), 0) + 1 FROM program_terms")
    return f"PT-{cur.fetchone()[0]:04d}"


TERM_COLUMNS = ("program_id", "customer_id", "program_type", "rate", "rate_unit", "base_definition",
                "projected_redemption", "window_start", "window_end", "requires_proof", "source_clause_id",
                "amendment_id", "valid_from", "valid_to", "decision_time")


def _insert_term(cur, row: dict) -> str:
    tid = _next_term_id(cur)
    cur.execute(f"INSERT INTO program_terms (id, {', '.join(TERM_COLUMNS)}) VALUES (%s, {', '.join(['%s'] * len(TERM_COLUMNS))})",
                (tid, *(row.get(c) for c in TERM_COLUMNS)))
    return tid


def extract_program(cur: psycopg.Cursor, program: dict) -> dict:
    r = read_agreement(program["document_text"])
    if r["program_id"] != program["id"]:
        raise ExtractionError(f"{program['id']}'s document names {r['program_id']}")
    customer = one_row(cur, "SELECT id FROM customers WHERE name = %s", (r["customer_name"],))
    if customer is None or customer["id"] != program["customer_id"]:
        raise ExtractionError(f"{program['id']}'s document names {r['customer_name']}, not its customer")
    known = datetime.combine(program["available_at"], READ_AT)
    tid = _insert_term(cur, {**r, "customer_id": customer["id"], "amendment_id": None, "valid_from": r["window_start"],
                             "valid_to": None, "decision_time": known})
    return {"program_id": program["id"], "term_ids": [tid], "ambiguities": r["ambiguities"],
            "second_reader": second_reader(program["document_text"], r) if model.enabled() else []}


def extract_amendment(cur: psycopg.Cursor, amendment: dict) -> dict:
    """The amended rate from its effective date, and the term it replaces closed the day before:
    two new rows, known from the day the amendment reached us. Nothing earlier is touched."""
    a = read_amendment(amendment["document_text"])
    if (a["amendment_id"], a["program_id"]) != (amendment["id"], amendment["program_id"]):
        raise ExtractionError(f"{amendment['id']}'s document names {a['amendment_id']} on {a['program_id']}")
    known = datetime.combine(amendment["available_at"], READ_AT)
    current = terms_as_of(cur, a["program_id"], a["effective_date"], known)
    if current is None:
        raise ExtractionError(f"{a['amendment_id']}: {a['program_id']} has no terms in force on {a['effective_date']}")
    base = {c: current[c] for c in TERM_COLUMNS if c in current}
    ids = []
    if a["effective_date"] > current["valid_from"]:
        ids.append(_insert_term(cur, {**base, "valid_to": a["effective_date"] - timedelta(days=1), "decision_time": known}))
    ids.append(_insert_term(cur, {**base, "rate": a["rate"], "source_clause_id": f"{a['amendment_id']}#{a['clause']}",
                                  "amendment_id": a["amendment_id"], "valid_from": a["effective_date"],
                                  "valid_to": current["valid_to"], "decision_time": known}))
    return {"amendment_id": a["amendment_id"], "program_id": a["program_id"], "term_ids": ids}


def extract_landed(cur: psycopg.Cursor, through: date) -> list[dict]:
    """Every agreement and amendment that has reached us by `through` and isn't read yet, oldest first."""
    out = []
    for p in all_rows(cur, """SELECT * FROM trade_programs p WHERE available_at <= %s
                                AND NOT EXISTS (SELECT 1 FROM program_terms t WHERE t.program_id = p.id)
                              ORDER BY available_at, id""", (through,)):
        try:
            out.append(extract_program(cur, p))
        except ExtractionError as err:
            out.append({"program_id": p["id"], "error": str(err)})
    for a in all_rows(cur, """SELECT * FROM program_amendments a WHERE available_at <= %s
                                AND NOT EXISTS (SELECT 1 FROM program_terms t WHERE t.amendment_id = a.id)
                              ORDER BY available_at, id""", (through,)):
        try:
            out.append(extract_amendment(cur, a))
        except ExtractionError as err:
            out.append({"amendment_id": a["id"], "program_id": a["program_id"], "error": str(err)})
    return out


def log_line(r: dict) -> str:
    what = r.get("amendment_id") or r["program_id"]
    if r.get("error"):
        return f"could not read {what}: {r['error']}; its claims can't be verified until a person enters the terms"
    extra = (f"; ambiguous: {len(r['ambiguities'])} clause(s)" if r.get("ambiguities") else "") + \
            (f"; second reader disagrees on {', '.join(r['second_reader'])}" if r.get("second_reader") else "")
    return f"read {what} into {', '.join(r['term_ids'])}{extra}"


def compare_with_truth(cur: psycopg.Cursor, truth: list[dict]) -> list[str]:
    """Every difference between what was extracted and the generator's ground truth (ids aside)."""
    fields = [c for c in TERM_COLUMNS if c != "decision_time"]

    def norm(v):
        return format(v.normalize(), "f") if isinstance(v, Decimal) else str(v)

    have = sorted(tuple(norm(r[c]) for c in fields) for r in all_rows(cur, "SELECT * FROM program_terms"))
    want = sorted(tuple(norm(r[c]) for c in fields) for r in truth)
    return [json.dumps(dict(zip(fields, row))) for row in sorted(set(have) ^ set(want))]
