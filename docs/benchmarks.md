# Benchmarks: is the simulation the right shape?

`make players && make benchmarks` puts the played year's statistics beside sourced industry and peer
figures (`tpa/benchmarks.py`). A benchmark describes the industry; it never tunes the fiction, which is
frozen. Where the simulation sits outside a range, the reason is below, so a judge hears it from us.

| Measure | Simulation (seed 1337, 2026) | Benchmark | Where | Why |
|---|---|---|---|---|
| Trade spend, % of gross sales | 7.3% | 15–25% (Strategy&/PwC 2017: "about 20 percent of their gross sales") | below | One brand family's scan-back, display, MDF and one off-invoice program; no everyday price allowances, coupons or slotting |
| Trade liability, % of net sales | 3.3% | 1.96–2.80% (General Mills 10-Ks FY2020–26); 1.0–1.95% (trade-only peer lines) | above | Walmart claims arrive 5 months after the activity, so five months of scan-back sit unclaimed |
| Trade liability, days of net sales | 12.1 | 7.2–10.2 (General Mills FY2020–26) | above | The same 5-month lag |
| Deductions, % of gross sales | 6.5% | 2–3% (Credit Research Foundation 2012; 3% for food and grocery) | above | Almost all of the simulated trade spend is settled by deduction; real off-invoice allowances never become deductions |
| Invalid share of deduction dollars | 13.3% | 3–5% (CRF 2012) | above | 50 planted errors: a test set dense enough to exercise every control |
| Days to resolve a deduction (median) | 0 | 15–18 (Hackett 2020, via SSON) | below | The engine decides the day a claim lands, and the played humans answer the same day |
| Findings settled without a person | 71% | 48–89% (HighRadius customer cases: vendor figures) | inside | |
| True-ups, % of trade spend | 3.7% | ≤3% (Hershey 10-K FY2025: "have not deviated ... by more than 3%") | above | The forgotten amendment (AM-02, $1.39M) is the demo's moment: one large year |

Peer liabilities, from each company's latest 10-K, as a share of net sales:

| Company | Year | Liability | Share | Note |
|---|---|---|---|---|
| General Mills | FY2026 | $493M | 2.68% | trade and coupon (critical estimate) |
| Hershey | FY2025 | $227.7M | 1.95% | trade and consumer incentives |
| Smucker | FY2026 | $175.9M | 1.94% | |
| Campbell's | FY2026 | $159M | 1.63% | trade and consumer promotion |
| Conagra | FY2026 | $116.0M | 1.03% | trade promotion and advertising |
| Post | FY2025 | about 1% | | variable consideration resolved next period |
| Kraft Heinz, Kellanova, Mondelez | | 3.2–7.2% | | lines include advertising; not comparable |

Context for the business case:
- Deduction cost: about **$97 per deduction** (CRF 2012, cited by Clarkston Consulting).
- Staffing: about 17 people per $10B of revenue with manual processes, 10 for top performers (Hackett 2020).
- One retailer's volume: Hershey took over 42,000 deductions a year at Kroger alone (HighRadius event, vendor-sourced).
- Dispute windows: Walmart allows disputes on deductions less than two years old; Kroger allows 180 days from the invoice (SPS Commerce).
- Post-audit claims reach back up to two years.

**Not found, so not claimed:**
- the share of deductions arriving without backup
- a days benchmark for claim lag
- Costco's dispute window
- the share of deductions from post-audit firms
- a cereal-specific trade rate

The full sourcing, with quotes and confidence, is in [benchmark-sources.md](benchmark-sources.md). Vendor figures
are marked as such and trusted least.
