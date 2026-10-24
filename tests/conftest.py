import pytest

from tpa.db import connect, reset_schema


@pytest.fixture
def conn():
    """A fresh schema per test. Tests run against DATABASE_URL — never point it at the demo DB."""
    c = connect()
    reset_schema(c)
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def base(conn):
    """Minimal reference rows: one customer, one sales lead, one program, two periods."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO customers VALUES ('WMT', 'Walmart', 'mass')")
        cur.execute("INSERT INTO actors VALUES ('sales.walmart', 'Walmart sales lead', 'sales_lead', 'WMT')")
        cur.execute("INSERT INTO actors VALUES ('controller', 'Controller', 'controller', NULL)")
        cur.execute(
            "INSERT INTO trade_programs VALUES "
            "('TP-0214', 'WMT', 'scan-back terms', 'scan_back', '2026-01-10', 'sales.walmart', '2026-01-10')"
        )
        cur.execute("INSERT INTO periods (period, customer_id, state) VALUES ('2026-02', 'WMT', 'OPEN')")
        cur.execute("INSERT INTO periods (period, customer_id, state) VALUES ('2026-03', 'WMT', 'OPEN')")
    conn.commit()
    return conn
