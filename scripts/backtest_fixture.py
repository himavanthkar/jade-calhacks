"""Capture what the frontend's Backtest page replays. Re-seeds DATABASE_URL.

    uv run python scripts/backtest_fixture.py

backtest.json   GET /api/backtest (real 10-K figures, no database) and GET /api/metrics/series after the
                played year (the simulation: does it ask less as answers accumulate?)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from tpa import players  # noqa: E402
from tpa.api import app  # noqa: E402
from tpa.cycle import run_through  # noqa: E402
from tpa.db import connect  # noqa: E402

OUT = ROOT / "frontend" / "src" / "api" / "fixtures" / "backtest.json"

subprocess.run([sys.executable, str(ROOT / "scripts" / "seed.py"), "--seed", "1337", "--months", "24"], check=True,
               cwd=ROOT, stdout=subprocess.DEVNULL)
os.environ["TPA_HUMANS"] = "players"
with connect() as conn:
    run_through(conn, "2026-12", players.hooks())
c = TestClient(app)
backtest, series = c.get("/api/backtest").json(), c.get("/api/metrics/series").json()
for m in series:                     # the page needs the scores, not the lists of ids behind them
    m.pop("missed", None), m.pop("false_positives", None)
OUT.write_text(json.dumps({"backtest": backtest, "series": series}, separators=(",", ":")))
print(f"wrote {OUT.relative_to(ROOT)}: {len(backtest['closes'])} closes, {len(series)} months")
