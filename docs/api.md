# API and live scenarios

## API

`make api`, or `uv run uvicorn tpa.api:app --reload`. Amounts are decimal strings, never floats.

| Endpoint | |
|---|---|
| `GET /api/clock` | where the simulation is |
| `GET /api/period/{p}?as_of=` | state per customer, postings, findings, gates, flux, analytical review, as the books stood then |
| `POST /api/period/{p}/step` | run the month the clock points at |
| `POST /api/period/{p}/sign` | `{customer_id, signed_by}` a named reviewer signs a clean period |
| `GET /api/period/{p}/package?as_of=` | the sign-off package |
| `GET /api/period/{p}/export/{ledger,trial_balance,reconciliation,gates}.csv` | the package with Excel check rows |
| `GET /api/controls` | the mined controls with their precedents and fired counts |
| `GET /api/precedents/{history,live}/{id}` | a precedent cell's click-through |
| `GET /api/escalations?open=true` | the inbox: question, options, recommendation, evidence |
| `POST /api/escalations/{id}/answer` | `{answer, answered_by?, reasoning?}` writes the precedent |
| `GET /api/explain/{entry_id}` | the evidence chain for a ledger line |
| `POST /api/ask` | `{question}` the interrogation box |
| `GET /api/metrics?as_of=` | precision, recall, escalation rate, autonomy, answers that stuck |
| `GET/POST /api/scenario`, `GET /api/scenario/examples` | live scenarios |

`TPA_HUMANS` chooses who answers a step's cards: `inbox` (a person, default), `players`, or `autopilot`.

## Live scenarios

Hyphenate may ask for a scenario of their own. `POST /api/scenario` adds source rows to the month the clock
is on, and the engine meets them on the next step exactly like seeded data (`step: true` runs it at once).

| Kind | Example | What the engine does |
|---|---|---|
| `deduction` | a scan-back claim with no backup, or at a rate the program doesn't say | dispute by precedent, or a "which is the source of truth?" card |
| `duplicate` | a claim taken twice | caught, citing the original |
| `backup` | scan data arriving for a held claim | re-checks; withdraws its own dispute and clears |
| `return` | cases coming back after the month was accrued | re-makes the accrual net of them |
| `amendment` | a rate change effective months ago, as a document | reads it, re-prices the closed months, asks the controller |
| `approval_attempt` | the sales lead approving his own program's claim | blocked by segregation of duties |
| `handoff` | a colleague's half-finished match | re-checked, then finished or handed back with the reason |

`GET /api/scenario/examples` gives ready-made ones against the books as they stand.
