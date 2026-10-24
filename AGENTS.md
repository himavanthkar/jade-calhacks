# AGENTS.md

Source of truth for every coding agent working in this repo (Claude Code, Codex, Cursor, etc.). `CLAUDE.md` only imports this file — edit here, not there.

## Project

Trade promotion autonomy — Cal Hacks 13.0, Hyphenate track. An autonomous system that fills the trade promotion accountant and deduction analyst seats: accrue on shipment, match deductions, clear or dispute, restate closed periods, and package the close for sign-off. `spec.md` is the build spec; `README.md` has setup and layout.

## Commands

```sh
make db-up      # Postgres 16 on localhost:5433
uv sync
make db-reset   # drop and apply db/schema.sql
make seed       # 24 months of deterministic data + data/answer_key.json
make test       # uv run pytest -q
uv run python scripts/evaluate.py --as-of month-1 --as-of month-9
```

Tests reset the schema. Point `DATABASE_URL` at a scratch database, never a shared one.

## Domain rules (mandatory)

The accounting rules live in `.claude/rules/` and bind every change that touches accruals, deductions, clearing, disputes, reconciliation, or the close:

- `.claude/rules/01-gaap-foundation.md` — ASC 606 / ASC 326 basis, journal entry examples, contra-revenue vs. expense.
- `.claude/rules/02-deduction-system-rules.md` — the 12 core system rules and the clear / hold / dispute / escalate decision logic.
- `.claude/rules/03-reconciliation-and-controls.md` — the reconciliation identity, flags, success measures, and the one-deduction-one-resolution rule.

Claude Code loads these automatically. Other agents must read them before working on ledger, gate, matching, or close logic.

**The rules are read-only for agents.** A hook blocks edits to `.claude/rules/`. If a rule looks wrong or conflicts with the code, stop and raise it with a human; do not work around it.

Non-negotiables, in short:

1. Trade promotion accruals are **contra-revenue**, not operating expense. Here that is `Account.TRADE_PROMO_EXPENSE` (`4100`, in the revenue range) against `Account.ACCRUED_TRADE_PROMO` (`2300`).
2. One deduction → one documented resolution, with AR and accrual effects reconciled. Never clear AR while leaving the related liability outstanding; never reduce revenue twice for the same promotion.
3. Unsupported, duplicated, or excess amounts are held or disputed, not auto-approved. If it can't be verified from the agreement, escalate.
4. Credit-loss exposure (ASC 326) is evaluated separately from promotional liabilities.
5. Every automated decision is traceable: source records, calculations, journal IDs, overrides, approvals.
6. Thresholds and tolerances come from company policy, never presented as GAAP requirements.

## Code conventions

- `tpa/ledger.py` `post_journal` is the only write path into the ledger. Its module docstring is the posting contract (accrual, reversal, clearing, restatement) — follow it exactly.
- The ledger is insert-only; corrections are reversals or restatements via `post_catch_up`, never updates or deletes.
- Import accounts, ID prefixes, enums, and calendar helpers from `tpa/constants.py` instead of writing string literals.
- Reads that depend on time go through `tpa/asof.py` (`balances_as_of`, `entries_as_of`, `terms_as_of`, `landed`).
- Verifiability gates (`tpa/gates.py`) block a period; they don't warn. Don't weaken a gate to make a test pass.
- `tpa/seed/fiction.py` is frozen fiction — names, rates, and volumes don't change.
- Commit on green only: run `make test` before committing.
