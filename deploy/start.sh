#!/bin/sh
# Start JADE on a host that gives it an empty Postgres (DATABASE_URL) and a port (PORT).
#
# The answer key under data/ is rewritten on every start: the container's disk is wiped on restart, and
# the seed is deterministic, so it always matches the database. The database is seeded only when it is
# empty, then run through JADE_THROUGH (default month-7) with the played humans answering, so a visitor
# arrives at August and steps into the moment themselves.
set -e

python scripts/seed.py --seed 1337 --months 24 --no-db > /dev/null

seeded=$(python - <<'PY'
from tpa.db import connect
try:
    with connect() as c, c.cursor() as cur:
        cur.execute("SELECT to_regclass('sim_clock') IS NOT NULL")
        ok = cur.fetchone()[0]
        if ok:
            cur.execute("SELECT COUNT(*) FROM sim_clock")
            ok = cur.fetchone()[0] > 0
    print("yes" if ok else "no")
except Exception:
    print("no")
PY
)

if [ "$seeded" != "yes" ]; then
  echo "Seeding 24 months of books (seed 1337)"
  python scripts/seed.py --seed 1337 --months 24
  if [ -n "${JADE_THROUGH:-month-7}" ]; then
    echo "Running through ${JADE_THROUGH:-month-7} with the played humans"
    python scripts/step.py --players --through "${JADE_THROUGH:-month-7}"
  fi
else
  echo "Books already seeded; keeping them"
fi

exec uvicorn deploy.serve:app --host 0.0.0.0 --port "${PORT:-8000}"
