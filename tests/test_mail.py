"""The deductions inbox (tpa.mail): mail is read by code, lands as source rows or as context, and an
unsigned claim of terms changes who decides and what the agent recommends.

Jan–Mar run as seeded; April's mail is written into a local mailbox the way `scripts/demo_mail.py`
writes it, synced, and April runs with the cards left for people.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from tpa import judgment, mail, players
from tpa.cycle import run_through, step
from tpa.db import connect, reset_schema
from tpa.rows import all_rows, one_row
from tpa.seed.generate import build
from tpa.seed.load import load

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("demo_mail", ROOT / "scripts" / "demo_mail.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture(scope="module")
def april(tmp_path_factory):
    conn = connect()
    reset_schema(conn)
    load(conn, build(1337, 24), load_terms=False)
    conn.commit()
    run_through(conn, "2026-03", players.hooks())
    box = mail.LocalInbox(tmp_path_factory.mktemp("inbox"))
    with conn.cursor() as cur:
        b = demo.books(cur)
    box.send("x", *demo.side_letter(b))                                        # $4.50 from March, unsigned
    box.send("x", *demo.deduction_notice(b, 13_334, Decimal("4.50")))          # the claim the note is about
    box.send("x", *demo.deduction_notice(b, 13_334, Decimal("4.60")))          # a rate nobody wrote about
    box.send("x", *demo.deduction_notice(b, None, b["rate"], amount=Decimal("48001.60")))
    with conn.cursor() as cur:
        first = mail.sync(cur, box)
        held = first[-1]["created_ids"][0]
    box.send("x", *demo.backup_email(held, 12_632, b["rate"]))
    box.send("x", "Lunch Friday?", "Anyone up for tacos? Kroger parking lot food truck is back.")
    with conn.cursor() as cur:
        second = mail.sync(cur, box)
        again = mail.sync(cur, box)
    conn.commit()
    step(conn, judgment.hooks())
    conn.commit()
    conn.autocommit = True
    yield {"conn": conn, "landed": first + second, "again": again, "books": b}
    conn.close()


def cards_for(conn, deduction_id):
    with conn.cursor() as cur:
        return all_rows(cur, """SELECT e.*, f.control_id, f.evidence FROM escalations e JOIN findings f ON f.id = e.finding_id
                                WHERE f.evidence -> 'deduction_ids' ? %s ORDER BY e.id""", (deduction_id,))


def test_each_message_is_read_into_the_right_kind(april):
    kinds = [r["kind"] for r in april["landed"]]
    assert kinds == ["unsigned_terms", "deduction_notice", "deduction_notice", "deduction_notice", "claim_backup",
                     "unrecognised"]
    note = april["landed"][0]
    assert note["created_ids"] == [] and note["customer_id"] == "WMT"
    assert [i[:2] for i in april["landed"][1]["created_ids"]] == ["DD", "CB"]     # the notice carried its backup
    assert april["landed"][-1]["created_ids"] == []                               # small talk lands nothing
    assert april["again"] == []                                                   # a message is read once


def test_every_field_keeps_the_line_it_was_read_from(april):
    with april["conn"].cursor() as cur:
        row = one_row(cur, "SELECT parsed FROM inbound_messages WHERE id = %s", (april["landed"][1]["id"],))
    fields = row["parsed"]["fields"]
    assert fields["amount"]["line"] == "Deduction amount: $60,003.00"
    assert Decimal(fields["claimed_rate"]["value"]) == Decimal("4.50")
    assert row["parsed"]["sender"] == "supplier.claims@walmart.example"          # the forwarded sender, not ours


def test_an_unsigned_rate_sends_the_claim_to_the_controller_with_a_hold(april):
    ded = april["landed"][1]["created_ids"][0]
    [card] = cards_for(april["conn"], ded)
    assert card["control_id"] == "CTL-RATE-CONFLICT"
    assert card["to_role"] == "controller" and card["recommended"] == "hold"
    assert "no signed amendment on file" in card["question"] and "An email is not an agreement" in card["question"]
    quoted = {m["id"]: m for m in card["evidence"]["correspondence"]}
    assert set(quoted) == {april["landed"][0]["id"], april["landed"][1]["id"]}     # the note and the claim's own notice
    assert quoted[april["landed"][0]["id"]]["sender_actor"] == "sales.walmart"


def test_a_rate_nobody_wrote_about_takes_the_usual_road(april):
    ded = april["landed"][2]["created_ids"][0]
    [card] = cards_for(april["conn"], ded)
    assert card["to_role"] == "customer_team_analyst" and card["recommended"] != "hold"


def test_a_note_never_reaches_back_before_the_month_it_names(april):
    with april["conn"].cursor() as cur:
        earlier = all_rows(cur, """SELECT id FROM findings WHERE evidence ? 'correspondence'
                                   AND COALESCE(evidence ->> 'origin', evidence ->> 'claimed_period') < %s""",
                           (april["books"]["claimed"],))
    assert earlier == []


def test_backup_by_email_clears_the_held_claim(april):
    held = april["landed"][3]["created_ids"][0]
    with april["conn"].cursor() as cur:
        f = one_row(cur, "SELECT * FROM findings WHERE evidence -> 'deduction_ids' ? %s ORDER BY id LIMIT 1", (held,))
        cleared = one_row(cur, "SELECT count(*) AS n FROM ledger_entries WHERE deduction_id = %s AND entry_type = 'clearing'",
                          (held,))
    assert f["control_id"] == "CTL-SCAN-NO-BACKUP" and f["state"] == "resolved"
    assert f["evidence"]["resolution"]["decision"] == "superseded"
    assert cleared["n"] > 0


def test_the_inbox_shows_what_came_of_each_message(april):
    with april["conn"].cursor() as cur:
        rows = {r["id"]: r for r in mail.messages(cur)}
    note = rows[april["landed"][0]["id"]]
    assert any(o["to_role"] == "controller" for o in note["outcome"])
