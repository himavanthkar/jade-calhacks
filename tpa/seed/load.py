"""Write a generated Dataset into Postgres and its answer key to disk."""

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg

from tpa.ledger import Line, post_journal
from tpa.seed.generate import Dataset

# Insert order respects foreign keys.
TABLE_ORDER = [
    "customers", "actors", "trade_programs", "program_amendments", "shipments", "returns",
    "invoices", "deductions", "claim_backup", "disputes", "historical_decisions", "scripted_events",
]


def _insert(cur: psycopg.Cursor, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    cur.executemany(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        [tuple(r[c] for c in cols) for r in rows],
    )


def load(conn: psycopg.Connection, ds: Dataset, *, load_terms: bool = False) -> None:
    """Load into an empty schema (call tpa.db.reset_schema first). Commits once at the end."""
    with conn.cursor() as cur:
        for table in TABLE_ORDER:
            _insert(cur, table, ds.tables.get(table, []))
        # Opening balances go in before the history periods are closed.
        for j in ds.opening_journals:
            post_journal(
                cur, entry_type="opening", period=j["period"], customer_id=j["customer_id"],
                program_id=j["program_id"], decision_time=j["decision_time"], approved_by="controller",
                lines=[Line(account=a, debit=dr, credit=cr, memo=memo, valid_time=vt) for a, dr, cr, memo, vt in j["lines"]],
            )
        _insert(cur, "periods", ds.periods)
        _insert(cur, "sim_clock", [ds.sim_clock])
        if load_terms:
            _insert(cur, "program_terms", ds.program_terms)
    conn.commit()


def _jsonable(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    raise TypeError(f"cannot serialise {type(v).__name__}")


def fingerprint(ds: Dataset) -> str:
    """A short hash of every generated row and the answer key. Two machines with the same
    fingerprint hold exactly the same data; tests/test_seed.py pins the seed-1337 value."""
    blob = json.dumps({"tables": ds.tables, "answer_key": ds.answer_key}, default=_jsonable, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def write_files(ds: Dataset, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "answer_key.json": ds.answer_key,
        "program_terms_truth.json": ds.program_terms,
    }
    paths = []
    for name, payload in files.items():
        path = out_dir / name
        path.write_text(json.dumps(payload, indent=2, default=_jsonable) + "\n")
        paths.append(path)
    return paths
