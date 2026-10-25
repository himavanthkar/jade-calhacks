# Proof: what is real, and how we know it works

## What is real and what is simulated

| | Source |
|---|---|
| **Real** | General Mills (CIK 0000040704) and its customers Walmart, Costco and Kroger. From the FY2026 10-K (filed 2026-07-01): net sales $18.42B, North America Retail $10.57B, Walmart 22% of net sales and 31% of North America Retail, accrued trade and coupon promotion liabilities $493M, and the trade promotion accounting policy. FY2025: $19.49B and $470M. Each figure is quoted with its source in `tpa/seed/calibration.py`. The accounting rules (ASC 606, ASC 326) in `.claude/rules/`. |
| **Simulated (seeded)** | Every transaction: 24 months of shipments, invoices, returns, deductions, claim backup and disputes; the agreements and amendments as documents; last year's human decisions; the 50 planted errors. Generated deterministically from seed 1337 (`tpa/seed/`). Transaction-level trade data is never public, on either side of the trade. |
| **Simulated (people)** | The humans who answer cards in an unattended run: the played humans (`tpa/players.py`) take the agent's recommendation, or Claude plays the role and must pick one of the card's options. In the UI a real person answers instead (`TPA_HUMANS=inbox`). |
| **Not simulated** | Everything the system does with that data. The agreements are read from their text (`tpa/extract.py`); the generator's structured terms are only the extractor's answer key, compared in `tests/test_extract.py`. Controls are mined from last year's decisions, not configured. Every posting goes through one write path into an insert-only ledger. |
| **How it fits** | Every close compares the simulated liability with General Mills' real ratio (`tpa/review.py`): 2.16%–3.37% of net sales all year, against 2.41% and 2.68% reported. One brand family at Walmart is $348M a year, about 11% of General Mills' North America Retail sales to Walmart. The $1.39M catch-up is 4.8% of TP-0214's annual accrual and 0.008% of net sales: material to the program, immaterial to the company. |

## Proof it works

50 planted errors with an answer key (`data/answer_key.json`), scored by `tpa/evaluate.py`. Findings on
rows a judge injects live are scored apart.

| | Seed 1337 | Seed 42 (unseen) | Seed 2024 (unseen) |
|---|---|---|---|
| Precision, month 12 | 100% | 100% | 100% |
| Recall, month 12 | 100% | 100% | 100% |

The unseen seeds use the same generator and error types, placed differently: evidence the system isn't
fitted to one answer key, not that it would catch a kind of error never planted. On seed 1337 the played
year also reports escalation rate 40% (month 1) and 50% (month 12), autonomy 67% and 56%, and 37 of 40
repeat situations settled by precedent. The escalation rate stays level because new kinds of situations
keep arriving (a learned control in September, a new ambiguous clause); repeats don't escalate.

## What it got wrong

Found by testing on seeds we didn't develop on and with injected scenarios. Each fix has a test.

| Found by | What it did | Why it was wrong | Fix |
|---|---|---|---|
| Seed 42 | Flagged Kroger's January display claim as over-claimed | It split December's straddling display event by days, eating January's accrual; a per-event fee is accrued whole in one month | Clear on the accrual's basis: an event belongs to the month it starts in (`accrual.claim_share`); the window gate dates events the same way |
| Injected early claim | Raised a 98% redemption-drift alarm | One claim stream had arrived; Walmart sends two | Judge sell-through only once every stream the customer sent last year covers the month |
| Injected late backup | Nothing: the claim stayed disputed | No one re-checked a claim held for missing backup when the backup came | Re-check on arrival; withdraw our own dispute and clear, or raise what the backup shows |
| Injected self-approval | Let a sales lead approve an unmatched claim | No program meant no negotiator to compare with | Unverifiable is blocked |
| Injected handoff | Cleared a claim with no backup | The colleague proposed the wrong program, whose terms don't cover the claim, so every check passed vacuously | A handoff the agreement can't verify goes back |
| Costco instalments | Released an accrual while its claim sat unapplied | Rule 03: never clear one side and leave the other | Apply the unmatched instalment first, release only the residual |
| Final audit | Terms were loaded from the generator's answer key, not read | The agent was handed the contracts' terms | `tpa/extract.py` reads every agreement and amendment; one generated agreement (TP-0232) had lost its rate to a planted ambiguous clause and was corrected to state it |
