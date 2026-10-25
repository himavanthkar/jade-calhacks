# Presenting the data

Two pages carry the "is this real?" part of the demo. Both work in mock mode (captured fixtures) and live.

## Integrations

A hub-and-spoke map in the style of hyphenate.ai: the JADE engine in the middle, real logos on white tiles,
moving dashes on live connections.

| Tile | State | What to say |
|---|---|---|
| Gmail | live | "The deductions inbox. Notices, backup and signed amendments land as source rows; everything else is quoted on the card it's about." |
| SEC EDGAR | live | "General Mills' own 10-K is what the close checks the liability against." |
| Claude | live, optional | "Claude writes the card's sentences. A rewrite that changes a number is thrown away." |
| Escalation inbox, Postgres ledger, Excel close package | live | "One write path into an insert-only ledger; a person signs the package." |
| Retail Link · EDI 820 | planned (dashed, no logo) | "Retailer portals and remittance files take the same path; not built yet." |

Below the map, each email shows what JADE read (each field with its sentence) and what came of it.
For the live run, see [Integrations](integrations.md).

## Backtest

Four charts, each with a "What it means" note and a table view.

| Chart | Data | The point |
|---|---|---|
| How far the liability moves on its own | 16 year ends, balance-sheet line, 10-Ks | Audited books swung up to 22.1% in a year. A ±50% review can't fail; ±22% is calibrated on real history. |
| The estimate at each close, against the 10-K | Critical estimate, FY2021–26, walked forward | Last year's balance beats scaling by sales (9.4% vs 12.3% error): the balance follows programs and claim timing, which is why JADE accrues per program. |
| When the estimate trues up, the quarter moves | Three Q4 earnings releases, quoted | Trade timing moved sales growth by up to 3 points and profit growth by up to 13. JADE's catch-up, scaled to the company, is about one point. |
| Asked once, then settled by precedent | The simulation's played year | 37 of 40 repeats settled by an earlier answer. The asking rate isn't a straight line down: September spikes when a new control is learned. |

Say which charts are real and which is the simulation; the page labels each one. Deduction-level accuracy
is never claimed on real data, because that data isn't public.

Brand marks: `frontend/public/brand/` (sources in its CREDITS.md). Fixtures: `scripts/backtest_fixture.py`,
`scripts/mail_fixture.py`.
