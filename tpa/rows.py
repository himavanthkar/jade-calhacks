"""Dict-row query helpers shared by the engine modules."""

import psycopg
from psycopg.rows import dict_row


def all_rows(cur: psycopg.Cursor, sql: str, params=()) -> list[dict]:
    with cur.connection.cursor(row_factory=dict_row) as c:
        c.execute(sql, params)
        return c.fetchall()


def one_row(cur: psycopg.Cursor, sql: str, params=()) -> dict | None:
    with cur.connection.cursor(row_factory=dict_row) as c:
        c.execute(sql, params)
        return c.fetchone()
