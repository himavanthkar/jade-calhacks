#!/usr/bin/env bash
# End to end: Postgres, the books, the API (on :8000, or the next free port) and the UI on :5173, wired together.
#
#   scripts/demo.sh                    first run seeds; later runs keep the books where they were
#   scripts/demo.sh --fresh            re-seed (wipes the demo database, not the scratch one)
#   scripts/demo.sh --fresh --through month-7
#                                      re-seed, then run months 1-7 with stand-in people answering the cards
#                                      (last year's handling); you take over in the UI from August
#   scripts/demo.sh --test             run the backend and frontend tests before starting
#   scripts/demo.sh --mock             UI only, on captured fixtures; no Docker, no API
#
# Ctrl-C stops the API and the UI. The database container keeps running (`make db-down` stops it).
set -euo pipefail
cd "$(dirname "$0")/.."

FRESH=0 THROUGH="" TEST=0 MOCK=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fresh) FRESH=1 ;;
    --through) THROUGH="${2:?--through needs a month, e.g. month-6}"; shift ;;
    --test) TEST=1 ;;
    --mock) MOCK=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null || { echo "missing $1: $2" >&2; exit 1; }; }

need bun "https://bun.sh"
if [[ $MOCK == 1 ]]; then
  say "Frontend on captured fixtures (mock)"
  (cd frontend && bun install --silent)
  cd frontend && exec env VITE_API_MODE=mock VITE_MOCK_SCENARIO=inbox bun run --bun dev
fi

need uv "https://docs.astral.sh/uv/"
need docker "Docker Desktop"
docker info >/dev/null 2>&1 || { echo "Docker isn't running: open Docker Desktop and try again." >&2; exit 1; }

if [[ ! -f .env ]]; then
  say "No .env: copying .env.example"
  cp .env.example .env
fi
set -a; source .env; set +a

say "Postgres on localhost:5433"
make -s db-up >/dev/null
pg_ready() { docker compose exec -T db pg_isready -U tpa >/dev/null 2>&1 || docker exec jade-tpa-db pg_isready -U tpa >/dev/null 2>&1; }
for _ in $(seq 60); do pg_ready && break; sleep 1; done
pg_ready || { echo "Postgres didn't come up in 60s (docker compose logs db)" >&2; exit 1; }
make -s db-scratch

say "Python and frontend dependencies"
uv sync -q
(cd frontend && bun install --silent)

seeded() { uv run python -c "
from tpa.db import connect
with connect() as c, c.cursor() as cur:
    cur.execute(\"SELECT to_regclass('sim_clock') IS NOT NULL\")
    ok = cur.fetchone()[0]
    if ok: cur.execute('SELECT COUNT(*) FROM sim_clock'); ok = cur.fetchone()[0] > 0
raise SystemExit(0 if ok else 1)" 2>/dev/null; }
if [[ $FRESH == 1 ]] || ! seeded; then
  say "Seeding 24 months of books (seed 1337)"
  make -s seed
else
  say "Books already seeded; keeping them (--fresh to re-seed)"
fi

if [[ -n $THROUGH ]]; then
  say "Running through $THROUGH, stand-in people answering the cards"
  uv run python scripts/step.py --players --through "$THROUGH" --metrics | grep -E 'precision|answers that stuck|waiting on people' || true
fi

if [[ $TEST == 1 ]]; then
  say "Tests"
  make -s test
  (cd frontend && bun test)
fi

API_PID=""
cleanup() { [[ -n $API_PID ]] && kill "$API_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Our API answers /api/clock with JSON; anything else on the port is another project's server.
ours() { curl -sf -m 2 "http://127.0.0.1:$1/api/clock" 2>/dev/null | grep -q current_period; }
taken() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
PORT="${API_PORT:-8000}"
if ours "$PORT"; then
  say "Our API is already answering on :$PORT; using it"
else
  while taken "$PORT"; do echo "port $PORT is in use by something else; trying $((PORT + 1))"; PORT=$((PORT + 1)); done
  say "API on :$PORT (log: .demo-api.log)"
  uv run uvicorn tpa.api:app --port "$PORT" >.demo-api.log 2>&1 &
  API_PID=$!
  for _ in $(seq 30); do ours "$PORT" && break; sleep 1; done
  ours "$PORT" || { echo "API didn't start:" >&2; tail -20 .demo-api.log >&2; exit 1; }
fi
echo "clock: $(curl -s "http://127.0.0.1:$PORT/api/clock")"

say "UI on http://localhost:5173 (live API). Ctrl-C to stop."
cd frontend
API_PROXY_TARGET="http://127.0.0.1:$PORT" VITE_API_MODE=http VITE_API_BASE_URL=/api bun run --bun dev
