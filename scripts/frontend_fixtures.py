"""Capture real API responses as the frontend's mock fixtures. Re-seeds DATABASE_URL twice.

    uv run python scripts/frontend_fixtures.py

inbox.json   January and February stepped with every card left for a person
moment.json  the year through August with the played humans: the restatement, February's two answers
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from tpa.api import app  # noqa: E402

OUT = ROOT / "frontend" / "src" / "api" / "fixtures"


def seed():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "seed.py"), "--seed", "1337", "--months", "24",
                    "--load-terms"], check=True, cwd=ROOT, stdout=subprocess.DEVNULL)


c = TestClient(app)


def get(p):
    r = c.get(p)
    r.raise_for_status()
    return r.json()



os.environ["TPA_HUMANS"] = "inbox"; seed()
inbox = {"clock": get("/api/clock"), "controls": get("/api/controls"), "months": {}}
for p in ("2026-01", "2026-02"):
    step = c.post(f"/api/period/{p}/step").json()
    period = get(f"/api/period/{p}")
    lines = [x["id"] for x in period["postings"] if x["account"].startswith("2300") or x["entry_type"] in ("clearing", "dispute")]
    inbox["months"][p] = {"step": step, "period": period, "escalations": get("/api/escalations"),
                          "controls": get("/api/controls"), "metrics": get(f"/api/metrics?as_of={p}"),
                          "explain": {i: get(f"/api/explain/{i}") for i in lines[:25]}}
(OUT / "inbox.json").write_text(json.dumps(inbox, separators=(",", ":")))

os.environ["TPA_HUMANS"] = "players"; seed()
for m in range(1, 9):
    c.post(f"/api/period/2026-{m:02d}/step").raise_for_status()
feb = get("/api/period/2026-02")
accrual = next(x for x in feb["postings"] if x["entry_type"] == "accrual" and x["program_id"] == "TP-0214" and x["credit"] != "0.00" and x["valid_time"] == "2026-02-28")
aug = get("/api/period/2026-08")
moment = {"clock": get("/api/clock"), "period": aug,
          "restatement_finding": next(f for f in aug["findings"] if f["conflict_type"] == "amendment_not_applied"),
          "controls": get("/api/controls"), "escalations_answered": get("/api/escalations?open=false"),
          "feb_accrual": get(f"/api/explain/{accrual['id']}"),
          "feb_package_then": get("/api/period/2026-02/package?as_of=month-2"),
          "feb_package_now": get("/api/period/2026-02/package?as_of=month-8"),
          "metrics": {f"month-{m}": get(f"/api/metrics?as_of=month-{m}") for m in (1, 8)},
          "asks": [c.post("/api/ask", json={"question": q}).json() for q in
                   (f"Why did you post {accrual['journal_id']}?", "What did it know in March?")]}
(OUT / "moment.json").write_text(json.dumps(moment, separators=(",", ":")))
print({f.name: f.stat().st_size for f in OUT.iterdir()})
