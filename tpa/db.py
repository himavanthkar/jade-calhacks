"""Connection and schema helpers."""

import os
from pathlib import Path

import psycopg

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
DEFAULT_URL = "postgresql://tpa:tpa@localhost:5433/tpa"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or database_url())


def reset_schema(conn: psycopg.Connection) -> None:
    """Drop everything and apply db/schema.sql. The only sanctioned way to clear the ledger."""
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
        cur.execute("CREATE SCHEMA public")
        cur.execute(SCHEMA_PATH.read_text())
    conn.commit()
