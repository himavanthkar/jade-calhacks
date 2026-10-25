"""Capture the inbox the frontend's mock replays. Re-seeds DATABASE_URL.

    uv run python scripts/mail_fixture.py

mail.json   the year through September with the played humans; in October the Walmart sales lead's
            unsigned note, Walmart's claim at that rate, and the signed amendment land by (local) mail,
            and October runs with the cards left for a person.
"""

import json
import os
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["JADE_MAIL_BACKEND"] = "local"
os.environ["JADE_MAIL_DIR"] = tempfile.mkdtemp(prefix="jade-inbox-")

from fastapi.testclient import TestClient  # noqa: E402

from tpa import mail, players  # noqa: E402
from tpa.api import app  # noqa: E402
from tpa.cycle import run_through  # noqa: E402
from tpa.db import connect  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import demo_mail as demo  # noqa: E402

OUT = ROOT / "frontend" / "src" / "api" / "fixtures" / "mail.json"

subprocess.run([sys.executable, str(ROOT / "scripts" / "seed.py"), "--seed", "1337", "--months", "24"], check=True,
               cwd=ROOT, stdout=subprocess.DEVNULL)
with connect() as conn:
    run_through(conn, "2026-09", players.hooks())
    with conn.cursor() as cur:
        b = demo.books(cur)
box = mail.inbox()
for subject, body in (demo.side_letter(b), demo.deduction_notice(b, 13_334, Decimal("4.50")), demo.amendment(b)):
    box.send(demo.OUR_INBOX, subject, body)

os.environ["TPA_HUMANS"] = "inbox"
c = TestClient(app)
c.post("/api/inbox/sync", json={"step": True}).raise_for_status()
inbox = c.get("/api/inbox").json()
cards = {o["escalation_id"] for m in inbox for o in m["outcome"] if o["escalation_id"]}
OUT.write_text(json.dumps({"integrations": c.get("/api/integrations").json(), "inbox": inbox,
                           "escalations": [e for e in c.get("/api/escalations").json() if e["id"] in cards]},
                          separators=(",", ":")))
print(f"wrote {OUT.relative_to(ROOT)}: {len(inbox)} messages, {len(cards)} cards")
