# Getting started

## Quick start

```sh
cp .env.example .env    # then set TEST_DATABASE_URL; ANTHROPIC_API_KEY is optional
make db-up              # Postgres 16 on localhost:5433
make db-scratch         # tpa_scratch, the database tests reset
uv sync
make seed               # 24 months of books, fingerprint 731ff15914136d8f
make players            # run the live year with the played humans, print the scores
make api                # the HTTP API on :8000 for the UI
make test               # 129 tests, against TEST_DATABASE_URL only
```

| Command | What it shows |
|---|---|
| `make players` | the year end to end: judgment engine, played humans, scores and "answers that stuck" |
| `make says-no` | the same, with the controller overruling the agent on Walmart's quarter-straddling claims |
| `make year` | last year's answers applied directly, no judgment engine (a baseline) |
| `make step` | one month at a time, cards left for a person (`TPA_HUMANS=inbox`) |
| `uv run python scripts/evaluate.py --as-of month-1 --as-of month-12` | precision, recall, escalation rate, autonomy |
| `uv run python scripts/export.py --period 2026-02 --as-of month-2` | February as Excel-checkable CSVs (try `--as-of month-8` too) |
| `uv run python scripts/pull_10k.py` | re-read General Mills' 10-K figures from SEC EDGAR (needs `SEC_USER_AGENT`) |

Where the data comes from, and how to check you have the same: [`DATA.md`](../DATA.md).

## Frontend

React + Vite in `frontend/` (designed in Figma): period overview, journal entries, verification gates,
restatement comparison, flux review, the escalation inbox and the interrogation box.

```sh
make api                        # the backend on :8000; Vite proxies /api to it
cd frontend && bun install
VITE_API_MODE=http bun run dev  # against the real API
bun run dev                     # or replay captured responses (VITE_MOCK_SCENARIO=inbox | moment)
bun test && bun run build && bun run lint
```

The mock replays responses captured from the real API (`uv run python scripts/frontend_fixtures.py`
regenerates them); it computes nothing. For the live demo, run in `http` mode.
