"""The deductions inbox: mail that reaches General Mills' deduction team, read into the books.

    sync(cur, inbox())        pull new messages, parse each, and land it in the month the clock is on

Retailers send deduction notices and claim backup by email, and colleagues forward signed amendments
and their own notes about deals. A message is a source document, never an instruction. The parser is
deterministic (labelled lines and patterns, like `tpa.extract`), and every field it reads keeps the
line it came from. What a message becomes:

    deduction_notice   a retailer's deduction, with its backup if the notice carries it  → scenario 'deduction'
    claim_backup       backup for a deduction already taken                             → scenario 'backup'
    amendment          a signed amendment, forwarded                                    → scenario 'amendment'
    unsigned_terms     one of our people saying a rate was agreed, with nothing signed  → context only
    unrecognised       kept, quoted, never acted on

Source rows go through `scenario.inject`, so the engine meets them on the next step exactly as it
meets seeded data. Context is quoted on the card it concerns (`correspondence`), and an unsigned
claim of terms sends a rate question to the controller instead of letting a precedent settle it:
an email is not an agreement (rule 1), and a claim the agreement doesn't support is held (rule 8).

Two mailboxes: 'local' reads .eml files from a folder (offline, for rehearsals), 'gmail' reads a
Gmail mailbox through the Google Workspace CLI (`gws`). JADE_MAIL_BACKEND picks one.
"""

import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import format_datetime, parseaddr, parsedate_to_datetime
from pathlib import Path

import psycopg

from tpa import scenario
from tpa.asof import sim_clock
from tpa.constants import period_end
from tpa.rows import all_rows, one_row

ROOT = Path(__file__).resolve().parent.parent
FORWARD = re.compile(r"-{5,} ?Forwarded message ?-{5,}\s*\n(?P<head>(?:[A-Za-z-]+: .*\n)+)", re.I)

# Who a sender is. Retailers' addresses name the customer; our own people's name the actor, so a
# sales lead's note is known to come from the person who negotiated the deal. Reserved .example
# domains: the demo never writes as a real company.
DIRECTORY = {
    "supplier.claims@walmart.example": ("WMT", None, "Walmart supplier claims"),
    "deductions@kroger.example": ("KR", None, "Kroger deductions"),
    "vendor.ap@costco.example": ("COST", None, "Costco vendor AP"),
    "walmart.sales@generalmills.example": ("WMT", "sales.walmart", "Walmart sales lead"),
    "costco.sales@generalmills.example": ("COST", "sales.costco", "Costco sales lead"),
    "kroger.sales@generalmills.example": ("KR", "sales.kroger", "Kroger sales lead"),
    "walmart.team@generalmills.example": ("WMT", "team.walmart", "Walmart customer team analyst"),
}
CUSTOMER_WORDS = {"WMT": r"\bwalmart\b", "KR": r"\bkroger\b", "COST": r"\bcostco\b"}


@dataclass(frozen=True)
class Message:
    message_id: str
    source: str
    sender: str            # the envelope sender
    to: str
    subject: str
    body: str
    received_at: datetime


# ── mailboxes ───────────────────────────────────────────────────────────────
def _from_mime(raw: bytes, message_id: str, source: str) -> Message:
    m = message_from_bytes(raw, policy=policy.default)
    part = m.get_body(preferencelist=("plain", "html"))
    body = part.get_content() if part else ""
    if part is not None and part.get_content_type() == "text/html":
        body = re.sub(r"<br\s*/?>|</p>|</div>", "\n", body)
        body = re.sub(r"<[^>]+>", "", body)
    try:
        received = parsedate_to_datetime(m["Date"])
    except (TypeError, ValueError):
        received = datetime.now(timezone.utc)
    return Message(message_id, source, parseaddr(str(m["From"] or ""))[1].lower(), str(m["To"] or ""),
                   str(m["Subject"] or ""), body.replace("\r\n", "\n"), received)


class LocalInbox:
    """A folder of .eml files: what a mail export looks like, and a mailbox that never goes offline."""
    source = "local"

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or os.environ.get("JADE_MAIL_DIR") or ROOT / "data" / "inbox")

    @property
    def account(self) -> str:
        return str(self.path)

    def fetch(self) -> list[Message]:
        if not self.path.exists():
            return []
        return [_from_mime(p.read_bytes(), f"local:{p.name}", self.source) for p in sorted(self.path.glob("*.eml"))]

    def send(self, to: str, subject: str, body: str, sender: str = "deductions.demo@generalmills.example") -> str:
        self.path.mkdir(parents=True, exist_ok=True)
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = sender, to, subject
        m["Date"] = format_datetime(datetime.now(timezone.utc))
        m.set_content(body)
        name = f"{datetime.now():%Y%m%d-%H%M%S-%f}.eml"
        (self.path / name).write_bytes(bytes(m))
        return f"local:{name}"


class GmailInbox:
    """A Gmail mailbox through the Google Workspace CLI (`gws`, authorised once with
    `gws auth login -s gmail`). Reads only messages sent to the deductions address."""
    source = "gmail"

    def __init__(self, address: str | None = None, gws: str = "gws"):
        self.address = address or os.environ.get("JADE_MAIL_ADDRESS")
        if not self.address:
            raise RuntimeError("set JADE_MAIL_ADDRESS to the deductions mailbox (e.g. you+jade-deductions@gmail.com)")
        self.gws = gws

    @property
    def account(self) -> str:
        return self.address

    def _call(self, *args: str) -> dict:
        r = subprocess.run([self.gws, *args], capture_output=True, text=True, timeout=60)
        out = r.stdout.strip()
        data = json.loads(out[out.find("{"):]) if "{" in out else {}
        if r.returncode or "error" in data:
            raise RuntimeError(f"gws {' '.join(args[:3])}: {(data.get('error') or {}).get('message') or r.stderr.strip()}")
        return data

    def fetch(self) -> list[Message]:
        listed = self._call("gmail", "users", "messages", "list", "--params",
                            json.dumps({"userId": "me", "q": f"to:{self.address}", "maxResults": 50}))
        out = []
        for ref in reversed(listed.get("messages", [])):           # oldest first: arrival order
            got = self._call("gmail", "users", "messages", "get", "--params",
                             json.dumps({"userId": "me", "id": ref["id"], "format": "raw"}))
            raw = base64.urlsafe_b64decode(got["raw"] + "=" * (-len(got["raw"]) % 4))
            out.append(_from_mime(raw, f"gmail:{ref['id']}", self.source))
        return out

    def send(self, to: str, subject: str, body: str, sender: str | None = None) -> str:
        data = self._call("gmail", "+send", "--to", to, "--subject", subject, "--body", body)
        return f"gmail:{data.get('id', '')}"


def inbox() -> LocalInbox | GmailInbox:
    return GmailInbox() if os.environ.get("JADE_MAIL_BACKEND", "local") == "gmail" else LocalInbox()


# ── reading a message ───────────────────────────────────────────────────────
def unwrap(msg: Message) -> tuple[str, str | None, str]:
    """(original sender, who forwarded it, the original text). Most mail reaches the deductions
    inbox forwarded, so the sender that matters is the forwarded message's."""
    m = FORWARD.search(msg.body)
    if not m:
        return msg.sender, None, msg.body
    head = dict(re.findall(r"^([A-Za-z-]+): (.*)$", m["head"], re.M))
    original = parseaddr(head.get("From", ""))[1].lower() or msg.sender
    return original, msg.sender, msg.body[m.end():]


def _field(text: str, *labels: str) -> tuple[str, str] | None:
    """(value, the line it was read from) for the first labelled line, `Label: value`."""
    for label in labels:
        m = re.search(rf"^[ \t>*]*{label}[ \t]*[:\-][ \t]*(?P<v>.+?)[ \t]*$", text, re.I | re.M)
        if m:
            return m["v"], m[0].strip(" >*\t")
    return None


def _amount(v: str) -> Decimal:
    return Decimal(re.sub(r"[^\d.]", "", v.split("per")[0].split("/")[0]))


MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"), 1)}


def _period(v: str) -> str | None:
    if m := re.search(r"\b(\d{4})-(0[1-9]|1[0-2])\b", v):
        return f"{m[1]}-{m[2]}"
    if m := re.search(r"\b([A-Za-z]+)\s+(\d{4})\b", v):
        if (n := MONTHS.get(m[1].lower())) is not None:
            return f"{m[2]}-{n:02d}"
    return None


def parse(msg: Message) -> dict:
    """What the message says, as fields with their source lines. Decides nothing."""
    sender, forwarded_by, text = unwrap(msg)
    customer, actor, who = DIRECTORY.get(sender, (None, None, None))
    if customer is None:
        named = [c for c, w in CUSTOMER_WORDS.items() if re.search(w, msg.subject + "\n" + text, re.I)]
        customer = named[0] if len(named) == 1 else None
    out = {"sender": sender, "sender_name": who, "forwarded_by": forwarded_by, "customer_id": customer,
           "sender_actor": actor, "fields": {}, "kind": "unrecognised"}
    fields = out["fields"]

    def read(name: str, *labels: str, conv=lambda v: v) -> None:
        if got := _field(text, *labels):
            try:
                fields[name] = {"value": conv(got[0]), "line": got[1]}
            except (ArithmeticError, ValueError):
                fields[name] = {"value": None, "line": got[1], "unreadable": True}

    program = re.search(r"\bTP-\d{4}\b", msg.subject + "\n" + text)
    if program:
        fields["program_id"] = {"value": program[0], "line": _line(text, program[0]) or msg.subject}

    if am := re.search(r"AMENDMENT (?:AM-\d+ )?TO TRADE PROMOTION AGREEMENT (TP-\d{4})", text, re.I):
        out["kind"] = "amendment"
        fields["program_id"] = {"value": am[1], "line": am[0]}
        if m := re.search(r"Signed (\d{4}-\d{2}-\d{2})", text):
            fields["signed_date"] = {"value": m[1], "line": m[0]}
        if m := re.search(r"effective (\d{4}-\d{2}-\d{2})", text, re.I):
            fields["effective_date"] = {"value": m[1], "line": _line(text, m[0])}
        if m := re.search(r"allowance is \$([\d.]+) per case", text, re.I):
            fields["new_rate"] = {"value": Decimal(m[1]), "line": _line(text, m[0])}
        return out

    if ded := re.search(r"\bDD-\d{4}\b", msg.subject + "\n" + text):
        if _field(text, "Units scanned", "Scan units", "Proof of performance"):
            out["kind"] = "claim_backup"
            fields["deduction_id"] = {"value": ded[0], "line": _line(text, ded[0]) or msg.subject}
    if out["kind"] == "unrecognised" and _field(text, "Deduction amount", "Amount deducted"):
        out["kind"] = "deduction_notice"
        read("amount", "Deduction amount", "Amount deducted", conv=_amount)
        read("claimed_period", "Claim period", "Promotion period", conv=_period)
        read("reason_code", "Reason code")
        read("invoice_id", "Invoice")
    read("claimed_rate", "Claimed rate", "Rate claimed", "Scan rate", conv=_amount)
    read("scan_units", "Units scanned", "Scan units", conv=lambda v: int(re.sub(r"[^\d]", "", v)))
    read("proof_of_performance", "Proof of performance", conv=lambda v: bool(re.match(r"\s*(yes|attached|y)\b", v, re.I)))

    if out["kind"] == "unrecognised" and actor and program:
        # One of our people says a rate was agreed. Read the rate and what they say about paper.
        if m := re.search(r"\$(\d+\.\d{2})\s*(?:/|a|per)\s*case", text, re.I):
            out["kind"] = "unsigned_terms"
            fields["asserted_rate"] = {"value": Decimal(m[1]), "line": _line(text, m[0])}
            if m := re.search(r"(?:from|starting|effective|since)\s+([A-Za-z]+\s+\d{4}|\d{4}-\d{2})", text, re.I):
                fields["from_period"] = {"value": _period(m[1]), "line": _line(text, m[0])}
            signed = re.search(r"\bsigned\b(?! amendment to follow)", text, re.I) and not re.search(
                r"\b(paperwork|amendment|contract) (?:is |will )?(?:to follow|coming|pending)\b|\bverbal(?:ly)?\b|"
                r"\bnot (?:yet )?signed\b", text, re.I)
            fields["signed"] = {"value": bool(signed), "line": _line(text, "paperwork") or _line(text, "verbal") or ""}
    return out


def _line(text: str, needle: str) -> str | None:
    """The sentence the needle sits in: a line, or one sentence of a paragraph."""
    for line in text.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line):
            if needle.lower() in sentence.lower():
                return sentence.strip(" >*\t")
    return None


def _v(parsed: dict, name: str):
    f = parsed["fields"].get(name)
    return f and f["value"]


def payload_for(parsed: dict) -> tuple[str, dict] | None:
    """The scenario row a message becomes, or None for context."""
    k = parsed["kind"]
    if k == "deduction_notice":
        p = {"customer_id": parsed["customer_id"], "amount": _v(parsed, "amount"), "program_id": _v(parsed, "program_id"),
             "claimed_period": _v(parsed, "claimed_period"), "claimed_rate": _v(parsed, "claimed_rate"),
             "reason_code": _v(parsed, "reason_code"), "invoice_id": None}
        if _v(parsed, "scan_units") or _v(parsed, "proof_of_performance"):
            p["backup"] = {"scan_units": _v(parsed, "scan_units"), "scan_rate": _v(parsed, "claimed_rate"),
                           "proof_of_performance": _v(parsed, "proof_of_performance")}
        return "deduction", {k2: v for k2, v in p.items() if v is not None}
    if k == "claim_backup":
        return "backup", {"deduction_id": _v(parsed, "deduction_id"), "scan_units": _v(parsed, "scan_units"),
                          "scan_rate": _v(parsed, "claimed_rate"),
                          "proof_of_performance": _v(parsed, "proof_of_performance")}
    if k == "amendment":
        return "amendment", {"program_id": _v(parsed, "program_id"), "new_rate": _v(parsed, "new_rate"),
                             "effective_date": _v(parsed, "effective_date"), "signed_date": _v(parsed, "signed_date")}
    return None


# ── landing it in the books ─────────────────────────────────────────────────
def landing(cur: psycopg.Cursor) -> int:
    """The day of the open month the next message lands on: mail arrives in order, a business day
    or so apart, so a backup always lands after the deduction it supports."""
    period, _ = sim_clock(cur)
    n = one_row(cur, "SELECT count(*) AS n FROM inbound_messages WHERE period = %s", (period,))["n"]
    return min(3 + 2 * n, period_end(period).day - 1)


def ingest(cur: psycopg.Cursor, msg: Message) -> dict | None:
    """Record one message and land what it carries. A message already ingested is skipped."""
    if one_row(cur, "SELECT id FROM inbound_messages WHERE message_id = %s", (msg.message_id,)):
        return None
    parsed = parse(msg)
    day = landing(cur)
    period, sim_date = scenario.landing_day(cur, day)
    em_id = scenario._id(cur, "inbound_messages", "EM", 4)
    injection, made = None, []
    if (row := payload_for(parsed)) is not None:
        kind, payload = row
        try:
            r = scenario.inject(cur, kind, {**payload, "day": day}, injected_by=f"email:{em_id}")
            injection, made = r["id"], r["created_ids"]
        except scenario.ScenarioError as err:
            parsed["not_landed"] = str(err)       # quoted on the inbox row; nothing is guessed
    _, sender_display, _ = DIRECTORY.get(parsed["sender"], (None, None, None))
    cur.execute(
        """INSERT INTO inbound_messages (id, source, message_id, from_addr, forwarded_by, subject, body, received_at,
                                         sim_date, period, kind, customer_id, sender_actor, parsed, injection_id,
                                         created_ids)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (em_id, msg.source, msg.message_id, parsed["sender"], parsed["forwarded_by"], msg.subject, msg.body,
         msg.received_at.replace(tzinfo=None), sim_date, period, parsed["kind"], parsed["customer_id"],
         parsed["sender_actor"], json.dumps(parsed, default=str), injection, made))
    return {"id": em_id, "kind": parsed["kind"], "lands_on": sim_date, "customer_id": parsed["customer_id"],
            "subject": msg.subject, "injection_id": injection, "created_ids": made,
            "not_landed": parsed.get("not_landed"), "sender": sender_display or parsed["sender"]}


def sync(cur: psycopg.Cursor, box=None) -> list[dict]:
    box = box or inbox()
    return [r for msg in box.fetch() if (r := ingest(cur, msg)) is not None]


# ── context for judgment ────────────────────────────────────────────────────
def _strings(obj) -> set[str]:
    if isinstance(obj, str):
        return {obj}
    if isinstance(obj, dict):
        return set().union(set(), *(_strings(v) for v in obj.values()))
    if isinstance(obj, (list, tuple)):
        return set().union(set(), *(_strings(v) for v in obj))
    return set()


def correspondence(cur: psycopg.Cursor, f: dict, at: datetime) -> list[dict]:
    """Mail that had landed by `at` about this finding: messages whose rows it names, and notes from
    our own people about the program it concerns."""
    ids = _strings(f.get("evidence") or {})
    if not ids:
        return []
    rows = all_rows(cur, """SELECT id, kind, from_addr, sender_actor, subject, sim_date, parsed, created_ids
                            FROM inbound_messages WHERE sim_date <= %s AND customer_id = %s
                              AND (created_ids && %s::text[] OR (kind = 'unsigned_terms'
                                   AND parsed -> 'fields' -> 'program_id' ->> 'value' = ANY(%s::text[])))
                            ORDER BY sim_date, id""", (at.date(), f["customer_id"], list(ids), list(ids)))
    origin = (f.get("evidence") or {}).get("origin") or (f.get("evidence") or {}).get("claimed_period")
    return [card_line(r) for r in rows if r["created_ids"] and set(r["created_ids"]) & ids or bears_on(r, origin)]


def bears_on(r: dict, origin: str | None) -> bool:
    """A note about terms bears on activity from the month it says they start; with no start month,
    on activity after the note was sent. Never on months already claimed under the old terms."""
    if origin is None:
        return False
    start = _v(r["parsed"], "from_period") or f"{r['sim_date']:%Y-%m}"
    return origin >= start


def card_line(r: dict) -> dict:
    p = r["parsed"]
    quotes = [v["line"] for v in p["fields"].values() if v.get("line")]
    return {"id": r["id"], "kind": r["kind"], "from": p.get("sender_name") or r["from_addr"],
            "sender_actor": r["sender_actor"], "subject": r["subject"], "received": r["sim_date"],
            "asserted_rate": _v(p, "asserted_rate"), "signed": _v(p, "signed"),
            "program_id": _v(p, "program_id"), "quotes": list(dict.fromkeys(quotes))[:4]}


def unsigned_terms(mail: list[dict]) -> list[dict]:
    return [m for m in mail if m["kind"] == "unsigned_terms" and not m["signed"]]


def status() -> dict:
    """What the integrations page shows: which mailbox, whether it answers."""
    backend = os.environ.get("JADE_MAIL_BACKEND", "local")
    out = {"id": "gmail", "name": "Gmail", "backend": backend, "address": os.environ.get("JADE_MAIL_ADDRESS")}
    try:
        box = inbox()
        out["account"] = box.account
        if backend == "gmail":
            box._call("gmail", "users", "getProfile", "--params", json.dumps({"userId": "me"}))
        out["status"] = "connected"
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as err:
        out["status"], out["detail"] = "not_connected", str(err)
    return out


def messages(cur: psycopg.Cursor) -> list[dict]:
    """Every message, with what came of it: the rows it made and the findings and cards on them."""
    rows = all_rows(cur, "SELECT * FROM inbound_messages ORDER BY id DESC")
    for r in rows:
        r["outcome"] = all_rows(cur, """SELECT f.id, f.control_id, f.state, f.escalation_type, f.amount,
                                               e.id AS escalation_id, e.to_role, e.answer
                                        FROM findings f LEFT JOIN escalations e ON e.finding_id = f.id
                                        WHERE f.evidence -> 'correspondence' @> %s::jsonb OR EXISTS (
                                          SELECT 1 FROM jsonb_path_query(f.evidence, 'strict $.**') AS x(v)
                                          WHERE jsonb_typeof(x.v) = 'string' AND x.v #>> '{}' = ANY(%s))
                                        ORDER BY f.id""",
                                (json.dumps([{"id": r["id"]}]), r["created_ids"] or ["-"]))
    return rows

