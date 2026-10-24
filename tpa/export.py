"""The sign-off package as CSVs anyone can check in Excel.

Every file ends with formula rows Excel recomputes itself: TOTAL sums the amount columns, CHECK
must come out 0 (debits equal credits; the reconciliation identity holds). The computed values sit
beside the formulas so the file also reads correctly in tools that don't evaluate them. Text that
Excel would treat as a formula is quoted with a leading apostrophe.

    ledger.csv           the period's lines as of the moment
    trial_balance.csv    per customer and account
    reconciliation.csv   ending = opening + accruals + estimate adjustments − settled, per program
    gates.csv            each verifiability gate, per customer, with its violations
"""

import csv
import io
import json
from datetime import date, datetime, time
from decimal import Decimal

import psycopg

from tpa.constants import period_end
from tpa.evaluate import resolve_period
from tpa.package import package

FILES = ("ledger.csv", "trial_balance.csv", "reconciliation.csv", "gates.csv")


def parse_as_of(spec: str | None) -> datetime:
    """'month-8' or '2026-08' → the end of that month; an ISO date-time passes through; None → now."""
    if spec is None:
        return datetime.max
    if spec.startswith("month-") or len(spec) == 7:
        return datetime.combine(period_end(resolve_period(spec)), time.max)
    return datetime.fromisoformat(spec)


class Formula(str):
    """A cell we wrote as a formula on purpose; everything else starting with '=' is escaped."""


def _cell(v):
    if isinstance(v, Formula):
        return str(v)
    if v is None:
        return ""
    if isinstance(v, (Decimal, int)):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


def _col(i: int) -> str:
    return chr(ord("A") + i)


def _table(header: list[str], rows: list[list], sums: list[str], check: str | None, check_value) -> str:
    """Rows, then TOTAL (=SUM per amount column) and CHECK (a formula that must be 0)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_cell(v) for v in r])
    first, last = 2, len(rows) + 1
    total = ["TOTAL"] + [""] * (len(header) - 1)
    for name in sums:
        i = header.index(name)
        total[i] = f"=SUM({_col(i)}{first}:{_col(i)}{last})"
    w.writerow(total)
    if check:
        w.writerow(["CHECK", check.format(total=last + 1), "must be 0", _cell(check_value)])
    # TOTAL and CHECK are formulas by construction; data rows went through _cell.
    return buf.getvalue()


def files(cur: psycopg.Cursor, period: str, as_of: datetime) -> dict[str, str]:
    pkg = package(cur, period, as_of)
    out = {}

    lines = [e for c in pkg["customers"] for e in c["postings"]]
    header = ["id", "journal_id", "customer_id", "entry_type", "account", "debit", "credit", "program_id",
              "valid_time", "decision_time", "approved_by", "memo"]
    dr, cr = header.index("debit"), header.index("credit")
    out["ledger.csv"] = _table(header, [[e[h] for h in header] for e in lines], ["debit", "credit"],
                               f"={_col(dr)}{{total}}-{_col(cr)}{{total}}",
                               sum((e["debit"] - e["credit"] for e in lines), Decimal("0")))

    tb = [[c["customer_id"], acct, bal if bal > 0 else Decimal("0"), -bal if bal < 0 else Decimal("0")]
          for c in pkg["customers"] for acct, bal in c["balances"].items()]
    out["trial_balance.csv"] = _table(["customer_id", "account", "debit", "credit"], tb, ["debit", "credit"],
                                      "=C{total}-D{total}", sum((r[2] - r[3] for r in tb), Decimal("0")))

    header = ["customer_id", "program_id", "origin", "opening", "accruals", "estimate_adjustments", "settled",
              "ending", "outstanding", "check"]
    rows = []
    for c in pkg["customers"]:
        for i, r in enumerate(c["reconciliation"], start=len(rows) + 2):
            rows.append([c["customer_id"], r["program_id"], r["origin"], r["opening"], r["accruals"],
                         r["estimate_adjustments"], r["settled"], r["ending"], r["outstanding"],
                         Formula(f"=D{i}+E{i}+F{i}-G{i}-I{i}")])
    out["reconciliation.csv"] = _table(header, rows, ["opening", "accruals", "estimate_adjustments", "settled",
                                                      "ending", "outstanding"],
                                       "=H{total}-I{total}", sum((r[7] - r[8] for r in rows), Decimal("0")))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["customer_id", "gate", "passed", "description", "violations"])
    for c in pkg["customers"]:
        for g in c["gates"].values():
            w.writerow([c["customer_id"], g["name"], g["passed"], _cell(g["description"]), _cell(g["violations"])])
    out["gates.csv"] = buf.getvalue()
    return out
