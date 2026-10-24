# jade-calhacks
ip

Trade promotion autonomy — Cal Hacks 13.0, Hyphenate track. See `spec.md`.

## Setup

```sh
make db-up      # Postgres 16 on localhost:5433 (docker compose)
uv sync
make db-reset   # drop and apply db/schema.sql
make seed       # reset, generate 24 months, load, write data/answer_key.json
make test
uv run python scripts/evaluate.py --as-of month-1 --as-of month-9
```

`DATABASE_URL` overrides the default `postgresql://tpa:tpa@localhost:5433/tpa`. Tests reset the schema, so point them at a scratch database.

## Layout

- `db/schema.sql` — the full DDL. Ledger guarantees (insert-only, balanced journals, signed-period lock) are enforced by triggers.
- `tpa/constants.py` — calendar, chart of accounts, ID prefixes, enums. Import these instead of writing string literals.
- `tpa/db.py` — connection and schema reset.
- `tpa/ledger.py` — `post_journal`, the only write path into the ledger, plus `reverse_lines` and `post_catch_up` (restatement). The module docstring is the posting contract.
- `tpa/asof.py` — `balances_as_of` (the spec's one query), `entries_as_of`, `entry_history` (the interrogation chain), `terms_as_of`, `landed` (source rows visible by sim date).
- `tpa/gates.py` — the five verifiability gates and `sign_period`, which refuses to sign a period that fails one.
- `tpa/evaluate.py` — precision, recall, escalation rate and autonomy against the answer key; `scripts/evaluate.py` prints them.
- `tpa/seed/` — the deterministic generator. `fiction.py` holds every frozen name, rate and volume; `plant.py` plants the prior-year human decisions and the 50 live errors.
- `data/answer_key.json` (generated) — `planted` (the 50), `behavioural` (expected findings that are not errors), `moment` (the TP-0214 catch-up by period), `controls_truth` (what the miner should find, with precedent ids).
- `data/program_terms_truth.json` (generated) — ground-truth term extraction. `--load-terms` loads it so nothing waits on the extractor.
