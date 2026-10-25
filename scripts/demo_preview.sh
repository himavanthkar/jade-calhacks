#!/usr/bin/env bash
# One command to the demo state the pitch assumes: January to September played, the sales lead's note,
# Walmart's $4.50 claim and the signed amendment landed by email, October run, three cards open
# (ESC-0018 hold and ESC-0019 restatement for the controller, ESC-0020 for the close reviewer).
#
#   scripts/demo_preview.sh             build the demo state, snapshot it, start the API (:8011) and UI (:5183)
#   scripts/demo_preview.sh --restore   back to the snapshot after a run or a judge's scenario (about 30 seconds)
#   scripts/demo_preview.sh --stop      stop the API and the UI
#   scripts/demo_preview.sh --gmail     land the emails through Gmail instead of the local mailbox
#                                       (needs `gws auth login -s gmail` and JADE_MAIL_ADDRESS)
#
# The target is DEMO_DATABASE_URL, default its own tpa_preview database, so `make test` (which resets
# TEST_DATABASE_URL) can't wipe a live demo. It refuses DATABASE_URL, the database scripts/demo.sh uses,
# unless --yes-reset-demo is passed.
set -euo pipefail
cd "$(dirname "$0")/.."

GMAIL=0 RESTORE=0 STOP=0 YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gmail) GMAIL=1 ;;
    --restore) RESTORE=1 ;;
    --stop) STOP=1 ;;
    --yes-reset-demo) YES=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n\033[1m▸ %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null || { echo "missing $1: $2" >&2; exit 1; }; }
API_PORT=8011 UI_PORT=5183
STATE=.local/demo-preview
mkdir -p "$STATE"

stop() {
  pkill -f "uvicorn tpa.api:app --port $API_PORT" 2>/dev/null || true
  pkill -f "vite.*--port $UI_PORT" 2>/dev/null || true
}
if [[ $STOP == 1 ]]; then stop; echo "stopped"; exit 0; fi

need uv "https://docs.astral.sh/uv/"
need bun "https://bun.sh"
need docker "Docker Desktop"
[[ -f .env ]] && { set -a; source .env; set +a; }
TARGET="${DEMO_DATABASE_URL:-postgresql://tpa:tpa@localhost:5433/tpa_preview}"
if [[ $TARGET == "${DATABASE_URL:-postgresql://tpa:tpa@localhost:5433/tpa}" && $YES != 1 ]]; then
  echo "refusing: $TARGET is the demo database (DATABASE_URL). Pass --yes-reset-demo to rebuild it anyway." >&2
  exit 1
fi
DB="${TARGET##*/}"; DB="${DB%%\?*}"
SNAPSHOT="${DB}_snapshot"
dbexec() { docker compose exec -T db "$@" 2>/dev/null || docker exec jade-tpa-db "$@"; }
MAIL_BACKEND=local
[[ $GMAIL == 1 ]] && MAIL_BACKEND=gmail

start() {
  say "API on :$API_PORT (log: $STATE/api.log)"
  DATABASE_URL="$TARGET" JADE_MAIL_BACKEND="$MAIL_BACKEND" JADE_MAIL_DIR="$PWD/$STATE/inbox" TPA_HUMANS=inbox \
    nohup uv run uvicorn tpa.api:app --port "$API_PORT" >"$STATE/api.log" 2>&1 </dev/null &
  for _ in $(seq 30); do curl -sf -m 2 "http://127.0.0.1:$API_PORT/api/clock" >/dev/null && break; sleep 1; done
  curl -sf -m 2 "http://127.0.0.1:$API_PORT/api/clock" >/dev/null || { echo "API didn't start:" >&2; tail -20 "$STATE/api.log" >&2; exit 1; }
  say "UI on :$UI_PORT (log: $STATE/ui.log)"
  (cd frontend && API_PROXY_TARGET="http://127.0.0.1:$API_PORT" VITE_API_MODE=http VITE_API_BASE_URL=/api \
    nohup bun run --bun dev --port "$UI_PORT" --strictPort >"../$STATE/ui.log" 2>&1 </dev/null &) >/dev/null 2>&1
  for _ in $(seq 30); do curl -sf -m 2 -o /dev/null "http://127.0.0.1:$UI_PORT" && break; sleep 1; done
  echo "clock: $(curl -s "http://127.0.0.1:$API_PORT/api/clock")"
  echo "open cards: $(curl -s "http://127.0.0.1:$API_PORT/api/escalations" | python3 -c 'import sys, json; print(len(json.load(sys.stdin)))')"
  printf '\n  Open http://localhost:%s\n  After a run or a judge'"'"'s scenario: scripts/demo_preview.sh --restore\n  Stop: scripts/demo_preview.sh --stop\n' "$UI_PORT"
}

if [[ $RESTORE == 1 ]]; then
  dbexec psql -U tpa -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$SNAPSHOT'" | grep -q 1 \
    || { echo "no snapshot yet: run scripts/demo_preview.sh first" >&2; exit 1; }
  stop; sleep 1
  say "Restoring $DB from $SNAPSHOT"
  dbexec dropdb -U tpa --if-exists --force "$DB"
  dbexec createdb -U tpa -T "$SNAPSHOT" "$DB"
  start
  exit 0
fi

stop
say "Postgres on localhost:5433"
make -s db-up >/dev/null
for _ in $(seq 60); do dbexec pg_isready -U tpa >/dev/null 2>&1 && break; sleep 1; done
dbexec createdb -U tpa "$DB" 2>/dev/null || true
uv sync -q
(cd frontend && bun install --silent)

export DATABASE_URL="$TARGET" JADE_MAIL_BACKEND="$MAIL_BACKEND" TPA_HUMANS=inbox
rm -rf "$STATE/inbox"; mkdir -p "$STATE/inbox"
export JADE_MAIL_DIR="$PWD/$STATE/inbox"

say "Seeding and playing January to September (seed 1337)"
uv run python scripts/step.py --reset --through month-9 --players | tail -1
say "The sales lead's note and Walmart's claim, read into October"
uv run python scripts/demo_mail.py run side-letter --no-step | grep -E "^\s+(sent|read)" || true
say "The signed amendment; October runs"
uv run python scripts/demo_mail.py run amendment | grep -E "card ESC-" || true

say "Snapshot for --restore"
dbexec dropdb -U tpa --if-exists --force "$SNAPSHOT"
dbexec createdb -U tpa -T "$DB" "$SNAPSHOT"
start
