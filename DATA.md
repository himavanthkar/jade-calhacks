# Data

Where every row comes from, what is done to it on the way, and how a teammate gets the same data.
For what is real and what is simulated, see the table in `README.md`.

## Getting the data

Nothing under `data/` is committed. Everything there is regenerated, identically, from code:

| What | Command | Committed? |
|---|---|---|
| The simulated books (2,523 source rows) and the database | `make seed` | No: regenerated. The code that makes it is committed. |
| `data/answer_key.json`, `data/program_terms_truth.json` | `make seed` | No: regenerated. |
| The 10-K figures and their quotes | already in `tpa/seed/calibration.py` | **Yes.** |
| The 10-K files (11 MB) and `data/edgar/extracted.json` | `uv run python scripts/pull_10k.py` (needs `SEC_USER_AGENT` in `.env`) | No: re-downloaded from EDGAR. |
| UI mock data | `uv run python scripts/frontend_fixtures.py` | **Yes**, in `frontend/src/api/fixtures/`. |
| A year of engine output (postings, findings, cards) | `make players` (or `make year`) | No: recomputed from the seed. |

**Checking you have the same data.** `make seed` ends with `fingerprint 72a7f2811d410a9d`. That is a hash of
every generated row and the answer key, and `tests/test_seed.py` pins it. The same seed gives the same
fingerprint on every machine, every Python hash seed, every run. If the fingerprint changes, the fiction
changed: re-seed, and expect the answer key and the demo numbers to move with it.

**Rows injected live** (`POST /api/scenario`) are the one exception to "everything is the seed": they are
recorded in `scenario_injections` with the ids they made, and the evaluator keeps their findings out of
precision (`counts.scenario_findings`), since the answer key never planted them.

## Cleaning: none, by design

There is no cleaning stage, and there must not be one. The generator writes straight into the source
tables, and the mess in them is deliberate: 50 planted errors (duplicates, transposed digits, claims outside
the window, missing backup, unnetted returns, ambiguous clauses, self-approvals). The system's job is to
find them. Dropping a duplicate or fixing a transposition on load would hide the error from the controls
and score as a miss. Rule 03 says the same for real books: unmatched deductions, duplicates and variances
are flagged, never quietly corrected.

What does happen to data is listed below. Every step is deterministic: same input, same output, no
model involved.

## 1 · Public data: SEC EDGAR → `tpa/seed/calibration.py`

`scripts/pull_10k.py`

1. **Fetch.** The filing index (`data.sec.gov/submissions/CIK0000040704.json`), the XBRL facts
   (`…/api/xbrl/companyfacts/CIK0000040704.json`) and the two latest 10-K documents, with your contact in
   the User-Agent as SEC asks, at most five requests a second.
2. **HTML to text.** Strip tags, unescape entities (`&amp;` → `&`), collapse all whitespace to single spaces.
   Nothing else; the text keeps the filing's own spacing quirks (`fiscal 2026 ,`).
3. **Extract.** One regular expression per figure, each matching the whole sentence or table row the figure
   sits in, and storing that text as its quote. A pattern that stops matching fails the script; it never
   falls back to a guess.
4. **Net sales from XBRL, not text.** `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`, rows
   with `form = 10-K`, `fp = FY` and the filing's own accession, latest period end. XBRL ($18,424.6M) and
   the segment table ($18,398.4M) differ by $26.2M, the corporate and other sales the 10-K reports outside
   segments (it says $26 million). Both are kept, each labelled.
5. **Freeze.** The figures and quotes are copied into `tpa/seed/calibration.py` by hand and committed.
   `tests/test_calibration.py` re-checks them against `data/edgar/extracted.json` whenever that file exists.

## 2 · Generation: `tpa/seed/`

`generate.py` and `plant.py`, from the parameters in `fiction.py` (frozen).

- **One random stream**, `random.Random(seed)`, consumed in a fixed order. No wall-clock time, no
  `faker`. Checked: the fingerprint is identical under different `PYTHONHASHSEED` values, so no set or dict
  ordering leaks into the output.
- **Ids assigned at the end**, after every row exists, in date order.
- **Money.** `Decimal` throughout, never floats; rounded to the cent half-up (`tpa.accrual.money`). Rates
  keep six decimals.
- **Calendar.** Walmart claims are cut into retail weeks (Saturday to Friday) and split at month ends; each
  week gets a seeded weight in [0.9, 1.1] so two weeks are never accidentally identical claims.
- **Availability.** Every source row carries `available_at`, the day it reaches the business (a deduction
  five months after the shipment, an amendment months after it was signed). The engine reads only rows
  that have landed (`tpa.asof.landed`).
- **Planting.** Errors are planted on chosen rows after generation and recorded in the answer key with
  the ids that prove them. Constrained picks go first so every plant has a valid target.

## 3 · Interpretation in the engine

These steps don't change source rows. Each one records what it did, as a finding or in a journal memo, so
the interrogation box can show it.

| Step | Where | What it does | Recorded as |
|---|---|---|---|
| Program matching | `controls.match_program`, `controls.program_on` | Use the program the deduction cites; else infer it from the reason code and claim dates; else leave it unmatched | `evidence.matched` = cited / inferred; unmatched deductions are held in 1250 and named on findings |
| Straddle allocation | `accrual.split_by_activity` | A claim across months is split by activity days, to the cent, remainder on the last share | `PERIOD-STRADDLE` finding; one clearing line per origin |
| Returns netting | `execute.reestimate` | A late return re-makes the origin's accrual on net cases | `RETURNS-NOT-NETTED` finding; reversal + new accrual |
| Duplicates | `controls.check_deduction` | Same customer, period, amount, reason and claim dates as an earlier one: disputed, never deleted | `DUPLICATE-DEDUCTION` finding; dispute journal |
| Backup variance floor | `policy.VARIANCE_NOISE_FLOOR_PCT` | Under 0.01% is treated as the retailer rounding a blended rate | stated policy (changes no finding on the seed) |
| As-of visibility | `tpa.asof` | Every read takes a decision time; nothing learned later leaks into an earlier answer | the bitemporal ledger |
| Rounding | `tpa.accrual.money` | Half-up to the cent, the one rule for every posted amount | — |
