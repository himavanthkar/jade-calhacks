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
make step       # run the next live month
make year       # re-seed, run all twelve with stand-in humans, print the metrics
make api        # the HTTP API on :8000 for the UI (frontend's Vite proxy points here)
make players    # same, through the judgment engine with the model-played humans (TPA_USE_MODEL=1 for Claude)
```

Copy `.env.example` to `.env`; the Makefile loads it. `ANTHROPIC_API_KEY` with `TPA_USE_MODEL=1` turns on Claude for the played humans and card drafting; nothing needs it. `DATABASE_URL` overrides the default `postgresql://tpa:tpa@localhost:5433/tpa`. Tests reset the schema, so point them at a scratch database.

## Layout

- `db/schema.sql` — the full DDL. Ledger guarantees (insert-only, balanced journals, signed-period lock) are enforced by triggers.
- `tpa/constants.py` — calendar, chart of accounts, ID prefixes, enums. Import these instead of writing string literals.
- `tpa/db.py` — connection and schema reset.
- `tpa/ledger.py` — `post_journal`, the only write path into the ledger, plus `reverse_lines` and `post_catch_up` (restatement). The module docstring is the posting contract.
- `tpa/asof.py` — `balances_as_of` (the spec's one query), `entries_as_of`, `entry_history` (the interrogation chain), `terms_as_of`, `landed` (source rows visible by sim date).
- `tpa/gates.py` — the five verifiability gates and `sign_period`, which refuses to sign a period that fails one.
- `tpa/evaluate.py` — precision, recall, escalation rate and autonomy against the answer key; `scripts/evaluate.py` prints them.
- `tpa/accrual.py` — the accrual math, pure functions: scan-back segments by rate, fixed funds, the restatement delta, how thresholds get rounded.
- `tpa/controls.py` — the controls library: one check per control, shared by the onboarding replay and the live cycle. Checks return `Hit`s; only those over the mined threshold become findings.
- `tpa/onboarding.py` — replays the history year, classifies every prior human decision by the check that fires on it, and mines thresholds, owners and precedent ids into `controls`. Also derives priors (claim lag, dispute and backup rates, materiality).
- `tpa/cycle.py` — the monthly engine. `step(conn, hooks)` runs one month: day by day (late returns, amendments, deductions, scripted human actions), then the close (revenue, accruals, gates, sign-off, flux). The period state machine lives here.
- `tpa/restate.py` — restatement: when an amendment's valid time reaches into accrued periods, propose a catch-up per period, raise it for the controller, post through `post_catch_up` once approved, and withdraw any dispute the old terms led us to raise.
- `tpa/execute.py` — every posting a decision can lead to (clear, dispute, top-up, re-estimate, release). `execute(cur, finding_id, decision, decided_by, at)` is how an answered escalation turns into journals.
- `tpa/flux.py` — flux commentary for accounts over materiality, every number a sum of named journal lines.
- `tpa/autopilot.py` — stand-in humans that answer as last year's did, for running the year end to end before the model-played roles land. `scripts/step.py --autopilot`.
- `tpa/judgment.py` — the judgment engine (`judgment.hooks()`): mechanical controls go to the agent; otherwise match a precedent on (control, conflict key, customer) and apply it silently, or classify the escalation (source conflict → customer team, low confidence → controller, authority → the control's owner) and write the card. `answer(cur, escalation_id, option_id, answered_by, at, reasoning=)` is the one path a person takes: it checks who may answer, executes, writes the precedent and settles the open cards that precedent now governs. Authority decisions apply silently only up to the largest exposure decided on that key.
- `tpa/sod.py` — segregation of duties. `can_approve(cur, actor_id, target_type, target_id)` throws `SegregationOfDutiesError` when the actor negotiated the program, or is the agent. A blocked attempt is a finding with `escalation_type='sod'`.
- `tpa/players.py` — the model-played humans (`players.hooks()`, `scripts/step.py --players`). Each role answers its cards through `judgment.answer`; with the model on, Claude plays the role and must pick one of the card's options, otherwise it answers as last year's people did.
- `tpa/api.py` — the HTTP surface: clock, period (with `?as_of=` for "what did it know"), step, sign, controls, precedents, escalations and answers, explain, ask, metrics. Decimals go out as strings. `TPA_HUMANS` picks who answers a step's cards.
- `tpa/explain.py` — the interrogation box. `chain(entry_id)` walks rule → terms (clause) → inputs → knew-at (and what wasn't known yet) → approved → signed → restated, every step citing ids. `ask(question)` resolves the records a question names and answers from their chains.
- `tpa/model.py` — the only doorway to Claude, off unless `TPA_USE_MODEL=1` and `ANTHROPIC_API_KEY` are set (`TPA_MODEL` overrides `claude-opus-5-5`). A drafted card that changes any number or record id is thrown away.

## Plugging into the engine (workstreams C and D)

`tpa.cycle.Hooks` is where judgment plugs in. The defaults let the engine run alone, deciding only what a mined control allows the agent and never approving or signing:

| Hook | Called | Default |
| --- | --- | --- |
| `judge(cur, finding, at)` | as each finding is raised, and again at close for any still `open` | mechanical precedents (duplicates, no proof, late returns) auto-resolve; the rest stay `open` |
| `on_event(cur, scripted_event, at)` | on the event's sim date — the sales lead's self-approvals | ignored (the SoD throw is C's) |
| `approve(cur, restatement_finding, at)` | when a restatement is proposed; return the approver or `None` to leave it escalated (`tpa.restate.apply` posts it later) | none: waits for a human |
| `sign(cur, period, customer_id, at)` | for each customer-period with nothing unresolved and every gate passing | none: the period stops at REVIEWED until a named reviewer signs |

After a human answers, call `tpa.execute.execute(cur, finding_id, decision, decided_by, at)`; decisions are listed in its docstring. A source-of-truth answer decides *what* is authorised and never approves a posting itself. Clears go through the agent's mined tolerance, and anything over it raises its own DED-GT-ACCRUAL finding.

Finding `evidence` always carries `summary` (the card's lede and question), `control` (id, name, threshold, owner, precedent ids, learned), `measure`, and the ids involved (`deduction_ids`, `program_id`, `origin`, `accrual_key`, `amendment_id`, `journal_ids`, …) plus check-specific facts. API mapping: `POST /api/period/{p}/step` → `cycle.step`; `GET /api/controls` → `controls` joined to finding counts; `GET /api/explain/{entry_id}` → `asof.entry_history`.
- `tpa/seed/` — the deterministic generator. `fiction.py` holds every frozen name, rate and volume; `plant.py` plants the prior-year human decisions and the 50 live errors.
- `data/answer_key.json` (generated) — `planted` (the 50), `behavioural` (expected findings that are not errors), `moment` (the TP-0214 catch-up by period), `controls_truth` (what the miner should find, with precedent ids).
- `data/program_terms_truth.json` (generated) — ground-truth term extraction. `--load-terms` loads it so nothing waits on the extractor.
