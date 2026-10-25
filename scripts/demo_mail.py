"""Live demo of the Gmail integration: mail reaches the deductions inbox, JADE reads it, and the month runs on it.

    uv run python scripts/demo_mail.py list
    uv run python scripts/demo_mail.py run side-letter          # send, read, run the month, print the cards
    uv run python scripts/demo_mail.py send side-letter         # send only: show it in Gmail, then sync from the UI
    uv run python scripts/demo_mail.py sync [--step]            # read new mail into the open month (and run it)

The scenarios, each written against the books as they stand (the month the clock is on):

    side-letter   The Walmart sales lead forwards a note: TP-0214 is "$4.50 a case now, paperwork to follow."
                  Walmart's deduction notice then claims last month at $4.50. Without the email the rate
                  conflict goes to the customer team, or a precedent settles it; with it, the controller gets
                  the card, the email quoted, and a hold recommended: an email is not an amendment.
    late-backup   Walmart deducts a scan-back claim with backup "to follow"; it is held. Two days later the
                  scan data arrives by email; JADE re-checks the claim, withdraws its own dispute and clears it.
    amendment     The customer team forwards the signed amendment: TP-0214 at $4.50 from last month. JADE reads
                  it into terms and sends the controller a restatement of the closed month it reaches. Run it
                  after side-letter (same month, `run side-letter --no-step` first) for the whole arc.

Mailbox: JADE_MAIL_BACKEND=local (default; .eml files in data/inbox) or gmail (via `gws`, after
`gws auth login -s gmail`, sending to and reading from JADE_MAIL_ADDRESS, e.g. you+jade-deductions@gmail.com).
Every sender is a reserved .example address carried in the forwarded header: nothing is sent as a real company.
"""

import argparse
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from email.utils import format_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tpa import judgment, mail  # noqa: E402
from tpa.asof import sim_clock, terms_as_of  # noqa: E402
from tpa.constants import add_months, period_end, period_start  # noqa: E402
from tpa.cycle import step  # noqa: E402
from tpa.db import connect  # noqa: E402
from tpa.rows import all_rows, one_row  # noqa: E402

OUR_INBOX = "deductions@generalmills.example"
WMT_CLAIMS = ("Walmart Supplier Claims", "supplier.claims@walmart.example")
WMT_LEAD = ("Walmart Sales Lead", "walmart.sales@generalmills.example")
WMT_TEAM = ("Walmart Customer Team", "walmart.team@generalmills.example")


def forward(sender: tuple[str, str], subject: str, body: str, note: str) -> tuple[str, str]:
    """How mail reaches a shared deductions inbox: forwarded, with the original header kept."""
    sent = format_datetime(datetime.now().astimezone() - timedelta(minutes=7))
    return (f"Fwd: {subject}",
            f"{note}\n\n---------- Forwarded message ---------\nFrom: {sender[0]} <{sender[1]}>\nDate: {sent}\n"
            f"Subject: {subject}\nTo: {OUR_INBOX}\n\n{body}")


def month_name(period: str) -> str:
    return period_start(period).strftime("%B %Y")


def books(cur) -> dict:
    period, _ = sim_clock(cur)
    claimed = add_months(period, -1) if period > "2026-01" else period
    on = period_end(claimed)
    term = terms_as_of(cur, "TP-0214", on, datetime.combine(period_start(period), datetime.min.time()))
    return {"period": period, "claimed": claimed, "rate": term["rate"] if term else Decimal("3.80")}


def deduction_notice(b: dict, units: int | None, rate: Decimal, amount: Decimal | None = None) -> tuple[str, str]:
    amount = amount if amount is not None else (units * rate).quantize(Decimal("0.01"))
    backup = (f"Units scanned: {units:,}\nClaimed rate: ${rate} per case\nScan data: attached (Retail Link POS extract)"
              if units else "Backup: to follow under separate cover")
    body = (f"Walmart Supplier Deduction Notice\n\nSupplier: General Mills Sales, Inc.  Vendor number: 0123456\n"
            f"Deduction amount: ${amount:,}\nProgram: TP-0214 (Cheerios scan-based allowance)\n"
            f"Claim period: {month_name(b['claimed'])}\nReason code: SB-SUPERCENTER\n{backup}\n\n"
            f"This amount has been deducted from the remittance below. Questions within 30 days to Supplier Claims.\n\n"
            f"Walmart Supplier Claims")
    return forward(WMT_CLAIMS, f"Deduction notice: TP-0214 scan-based allowance, {month_name(b['claimed'])}", body,
                   "Forwarding Walmart's deduction notice for this week's remittance.")


def side_letter(b: dict) -> tuple[str, str]:
    body = (f"Hi team,\n\nI agreed with the Walmart cereal buyer on Tuesday that TP-0214 goes to $4.50/case from "
            f"{month_name(b['claimed'])}. The paperwork is to follow. Their {month_name(b['claimed'])} scan claim "
            f"will come through at $4.50; please clear it at that rate so we don't sour things ahead of the Q4 reset.\n\n"
            f"Thanks,\nWalmart sales lead, General Mills")
    return forward(WMT_LEAD, "TP-0214 rate going forward", body, "FYI from the Walmart sales lead.")


def backup_email(deduction_id: str, units: int, rate: Decimal) -> tuple[str, str]:
    body = (f"Supplier Claims backup\n\nRe: deduction {deduction_id}, program TP-0214\nUnits scanned: {units:,}\n"
            f"Scan rate: ${rate} per case\nSource: Retail Link POS, Supercenter and Neighborhood Market stores\n\n"
            f"Walmart Supplier Claims")
    return forward(WMT_CLAIMS, f"Backup for deduction {deduction_id}", body, "Walmart sent the scan data.")


def amendment(b: dict) -> tuple[str, str]:
    effective = period_start(b["claimed"])
    signed = period_start(b["period"]) + timedelta(days=1)
    body = (f"AMENDMENT TO TRADE PROMOTION AGREEMENT TP-0214\nSigned {signed.isoformat()}.\n\n"
            f"Clause 4.2 is replaced in full, effective {effective.isoformat()}:\n"
            f"4.2 The allowance is $4.50 per case-equivalent unit scanned.\nAll other terms are unchanged.\n\n"
            f"Signed for Walmart Inc. and for General Mills Sales, Inc.")
    return forward(WMT_TEAM, "Signed: TP-0214 amendment", body,
                   "The signed amendment for the rate the sales lead mentioned. Countersigned by the buyer this week.")


def run_scenario(name: str, conn, box, to: str, *, step_month: bool) -> None:
    with conn.cursor() as cur:
        b = books(cur)
    print(f"Clock on {b['period']}; TP-0214 is ${b['rate']}/case for {b['claimed']}. Mailbox: {box.source} ({box.account})\n")
    if name == "side-letter":
        send(box, to, *side_letter(b))
        units = 13_334
        send(box, to, *deduction_notice(b, units, Decimal("4.50")))
    elif name == "late-backup":
        units = 12_632
        send(box, to, *deduction_notice(b, None, b["rate"], amount=(units * b["rate"]).quantize(Decimal("0.01"))))
        landed = sync(conn, box, expect=1)
        ded = next((i for r in landed for i in r["created_ids"] if i.startswith("DD-")), None)
        if ded is None:
            sys.exit("the deduction notice didn't land; see the inbox row")
        send(box, to, *backup_email(ded, units, b["rate"]))
    elif name == "amendment":
        send(box, to, *amendment(b))
    else:
        sys.exit(f"no scenario {name}: {', '.join(SCENARIOS)}")
    sync(conn, box)
    if step_month:
        run_month(conn)


def send(box, to: str, subject: str, body: str) -> None:
    mid = box.send(to, subject, body)
    print(f"  sent  {subject}  [{mid}]")


def sync(conn, box, expect: int = 0, wait: int = 90) -> list[dict]:
    """Read new mail. Gmail delivers in a few seconds; wait until it has."""
    landed, deadline = [], time.time() + (wait if box.source == "gmail" else 0)
    while True:
        with conn.cursor() as cur:
            landed += mail.sync(cur, box)
        conn.commit()
        if box.source != "gmail" or landed or time.time() > deadline:
            break
        time.sleep(3)
    for r in landed:
        made = ", ".join(r["created_ids"]) or ("not landed: " + r["not_landed"] if r["not_landed"] else "context only")
        print(f"  read  {r['id']} {r['kind']:<16} from {r['sender']}, lands {r['lands_on']}  → {made}")
    if expect and len(landed) < expect:
        sys.exit("no new mail arrived; check JADE_MAIL_ADDRESS and `gws auth status`")
    return landed


def run_month(conn) -> None:
    with conn.cursor() as cur:
        period, _ = sim_clock(cur)
    summary = step(conn, judgment.hooks())
    conn.commit()
    print(f"\nRan {period}:")
    for line in summary.get("log", []):
        if "EM-" in line or "CB-" in line or "AM-" in line or "arrived" in line:
            print(f"  {line}")
    with conn.cursor() as cur:
        ids = [i for r in all_rows(cur, "SELECT created_ids FROM inbound_messages WHERE period = %s", (period,))
               for i in r["created_ids"]]
        cards = all_rows(cur, """SELECT e.id, e.to_role, e.question, e.recommended, f.id AS finding_id, f.control_id,
                                        f.state, f.exposure
                                 FROM findings f LEFT JOIN escalations e ON e.finding_id = f.id
                                 WHERE f.period = %s AND (f.evidence ? 'correspondence' OR EXISTS (
                                   SELECT 1 FROM jsonb_path_query(f.evidence, 'strict $.**') AS x(v)
                                   WHERE jsonb_typeof(x.v) = 'string' AND x.v #>> '{}' = ANY(%s)))
                                 ORDER BY f.id""", (period, ids or ["-"]))
    if not cards:
        print("  nothing for a person: every message was settled by the agreement")
    for c in cards:
        where = f"card {c['id']} → {c['to_role']}" if c["id"] else f"{c['state']} by the agent"
        print(f"\n  {c['finding_id']} {c['control_id']} (${c['exposure'] or 0:,}): {where}")
        if c["question"]:
            print(f"    {c['question']}")


SCENARIOS = ("side-letter", "late-backup", "amendment")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("list", "run", "send", "sync"))
    ap.add_argument("scenario", nargs="?")
    ap.add_argument("--to", help="the deductions mailbox (default JADE_MAIL_ADDRESS, or the local folder)")
    ap.add_argument("--no-step", action="store_true", help="with run: read the mail but don't run the month")
    ap.add_argument("--step", action="store_true", help="with sync: also run the month")
    args = ap.parse_args()
    if args.command == "list":
        print("\n".join(SCENARIOS))
        return
    box = mail.inbox()
    to = args.to or getattr(box, "address", None) or OUR_INBOX
    with connect() as conn:
        if args.command == "sync":
            sync(conn, box)
            if args.step:
                run_month(conn)
        elif args.command == "send":
            with conn.cursor() as cur:
                b = books(cur)
            if args.scenario == "side-letter":
                send(box, to, *side_letter(b))
                send(box, to, *deduction_notice(b, 13_334, Decimal("4.50")))
            elif args.scenario == "amendment":
                send(box, to, *amendment(b))
            elif args.scenario == "late-backup":
                with conn.cursor() as cur:
                    held = one_row(cur, """SELECT d.id FROM deductions d JOIN inbound_messages m ON d.id = ANY(m.created_ids)
                                           ORDER BY m.id DESC LIMIT 1""")
                if held:
                    send(box, to, *backup_email(held["id"], 12_632, b["rate"]))
                else:
                    send(box, to, *deduction_notice(b, None, b["rate"], amount=(12_632 * b["rate"]).quantize(Decimal("0.01"))))
                    print("  (sync it, then `send late-backup` again for the backup)")
            else:
                sys.exit(f"scenario: {', '.join(SCENARIOS)}")
        else:
            run_scenario(args.scenario or "", conn, box, to, step_month=not args.no_step)


if __name__ == "__main__":
    main()
