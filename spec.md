# Trade Promotion Autonomy — Build Spec

Oct 23, 2026 · @Kusum

An autonomous system that fills two seats in trade promotion accounting at General Mills: the trade promotion accountant and the deduction analyst. Built for the Hyphenate track at Cal Hacks 13.0, submission due Oct 25, 2026 at 9:00 AM PT.

## The system

We automate **trade promotion accounting** at General Mills: the whole function, from promotion terms to signed-off close, not a single task inside it.

**The seats line, for submission:** *This system fills the trade promotion accountant and the deduction analyst at a $19.5B public CPG company. It reports to the controller, asks the customer team to settle source-of-truth conflicts, and is structurally barred from approving claims on programs the sales lead negotiated.*

Trade spend is the second-largest line on a CPG income statement after cost of goods. General Mills ships product to Walmart, Costco and Kroger, promises promotional support, and accrues the liability at an estimated rate the moment the shipment leaves. The retailer collects months later by deducting from what it owes — often at a different rate, citing a program from two quarters ago, with backup that does not tie. Somebody has to decide what is authorised, what is disputed, and what the accrual should have been all along.

The function, end to end:

1. Read the trade program terms and mine the controls that govern them
2. Accrue promotional liability on shipment at the projected rate
3. Match incoming deductions to programs, shipments and claim backup
4. Escalate to the customer team when the program and the deduction disagree
5. Clear authorised deductions against the accrual; dispute the rest
6. Restate closed periods when a program amendment or a resolved dispute changes the past
7. Draft flux commentary for every account over materiality
8. Package the period for the close reviewer to sign

The one thing we do that an existing autonomous-finance product does not: **a control that fires on the system's own prior conclusions.** When the past changes, the system reopens its own closed work, restates it, and explains both why it was right then and why it is wrong now.

## The company — General Mills

A real, public, $19.5B company. Everything about the business comes from filings; only the transaction-level data is generated.

| From the FY2025 10-K |  |
| --- | --- |
| Net sales | $19,486.6M |
| Cost of sales | $12,754M |
| Risk factor, verbatim idea | Consolidating retailers use buying power to push for lower pricing and increased promotional programs |
| Revenue recognition | Trade promotions are variable consideration, netted against gross sales |
| Customer concentration | Largest customer disclosed as a percentage of consolidated net sales — pull the current figure |

We model **one brand family in one division**, not the whole company. Hyphenate was explicit about staying inside one corner of one function.

### Why the supplier side

A retailer never discloses the vendor allowances it collects, so that side of this transaction has no public data behind it. The supplier side does: trade promotion is disclosed as variable consideration under revenue recognition, promotional accruals are a named estimate, and the counterparties are public companies with disclosed concentration. Same workload, same architecture, real numbers.

### The money that flows backwards

| Program type | What is promised | How it is collected |
| --- | --- | --- |
| Off-invoice allowance | A per-case rate during a promo window | Taken at invoice, immediately |
| Scan-back / bill-back | A rate on units the retailer actually sold through | Claimed weeks later with scan data as backup |
| Display and feature funds | Paid placement in a circular or end-cap | Claimed against proof of performance |
| Market development funds | Annual lump sum tied to volume commitments | Deducted in instalments through the year |

Scan-backs are where the hard problem lives. You accrue on shipment at a projected redemption rate; the retailer deducts months later at actual sell-through; the two rarely agree, and nothing settles until the backup arrives.

### The three customers

Real companies, generated transactions. Each exists to teach the system a different behaviour.

| Customer | Program mix | Behaviour the system must learn |
| --- | --- | --- |
| Walmart | Scan-back heavy, high volume | A mid-quarter rate amendment nobody applies to the accrual. **This is the moment.** |
| Costco | Off-invoice and MDF | Deducts in clean instalments; almost never disputes; low-risk prior |
| Kroger | Display and feature funds | Claims without proof of performance roughly a third of the time |

### The humans it answers to

All three are played by a model, with distinct authority. Each exists because a real decision belongs to them — not to make agents talk to agents.

| Role | Decides | Cannot do |
| --- | --- | --- |
| Customer sales lead | Negotiates programs, knows customer intent | **Cannot approve a claim on a program he negotiated.** The capability layer throws. |
| Customer team analyst | Settles source-of-truth conflicts with the retailer | Cannot post entries or sign the close |
| Controller | Approves write-offs over threshold, signs the close | — |

### Where the sources disagree

Four records of the same money, disagreeing structurally rather than by accident:

- **The trade program** says what rate was promised, with amendments nobody applied
- **Shipment data** says what actually moved, net of returns
- **The deduction** says what the retailer actually took, with a reason code and a date months earlier
- **The claim backup** says what the retailer says it sold, when it arrives at all

Every control in the library is a consistency rule across two of these.

## Architecture

Six layers. One agent owning one function — not a swarm of micro-agents, which Hyphenate explicitly warned against.

| Layer | What it holds | Model involved? |
| --- | --- | --- |
| 0 · Data plane | NetSuite-shaped tables: POs, receipts, returns, invoices, deductions, disputes, circular proof | No. Plain pipelines with data tests. |
| 1 · Context graph | Agreements parsed into structured deal terms, each clause linked to every transaction it touches | Extraction only |
| 2 · Controls library | Mined consistency rules: condition, threshold, owner, precedent | Mining and proposal only |
| 3 · Judgment engine | Finding to precedent match, else escalation to a named human | Question and explanation drafting |
| 4 · Execution | The period state machine, the ledger, restatement | No. Deterministic. |
| 5 · Surface | Month stepper, controls table, escalation inbox, interrogation box | No |

### The line we say to judges

> Every number is computed by deterministic code. The model reads contracts, proposes rules, drafts questions and writes explanations. It never does arithmetic and it never approves anything.

This matters because Hyphenate's own reason for choosing finance is that it is formally verifiable — debits equal credits, bank out equals bank balance. A system that lets a language model compute the number throws that away.

### Where the agent lives

Hyphenate was explicit: data consolidation is plain data engineering, and the agent lives in controls and monitoring. So layer 0 is deliberately boring and layer 2 is where the intelligence sits. We do not demo the pipeline.

### Stack

- **Postgres** — everything, including the bitemporal ledger
- **Python / FastAPI** — engine and API
- **Claude** — clause extraction, rule mining, escalation drafting, flux narrative, interrogation answers
- **React / Vite** — surface
- **pytest** — the verifiability gates run as assertions, not warnings

## Onboarding and the monthly cycle

### Onboarding — self-learning from history

Runs once, over 12 months of prior books. This is the step Hyphenate named first, and every mined rule must cite the precedent that taught it.

1. **Parse trade programs** into `program_terms`: rate, rate unit, base definition, projected redemption, promo window, proof requirement, effective dates
2. **Replay history deterministically** — for each past period, compute what the system *would* have accrued and cleared
3. **Diff against what the humans actually did** — every divergence is a signal: a tolerance they accepted, a rule they applied, an exception they made
4. **Mine controls** from those divergences, each with `condition`, `threshold`, `owner_role`, `precedent_ids`
5. **Derive priors** — per-customer dispute rate, backup arrival rate, days-to-claim, per-account materiality

Output: roughly twelve controls, each clickable back to the historical entries that taught it. Examples the miner should find:

| Control | Threshold | Owner | Mined from |
| --- | --- | --- | --- |
| Deduction exceeds accrued program liability | $2,500 | Trade promotion accountant | 7 prior adjustments |
| Scan-back claim with no backup on file | $0 — any | Deduction analyst | 3 reversed claims |
| Deduction taken outside the program window | $0 — any | Controller | 1 prior recovery |
| Accrual aged beyond 2 periods without a deduction | 2 periods | Close reviewer | 4 stale accruals |
| Claimed scan units differ from shipped cases | 0.5% tolerance | Trade promotion accountant | 22 accepted small variances |

That last one is the important one to demo: the system learned a **tolerance**, not a rule. Humans accepted 22 small variances and escalated the two large ones, so the threshold is derived from behaviour rather than configured.

### The monthly cycle — autonomous execution

A period state machine, not an agent loop:

```
OPEN → ACCRUED → CONTROLLED → ESCALATED → REVIEWED → SIGNED → CLOSED
                                    ↑                            │
                                    └────── RESTATED ────────────┘
```

Per period, per customer:

| # | Step | Posts? |
| --- | --- | --- |
| 1 | Gather shipments, returns, invoices for the period | No |
| 2 | Project redemption rate per open program | No |
| 3 | Compute accrued liability at the projected rate | No |
| 4 | Reverse the prior period accrual | Yes |
| 5 | Post the current accrual with a reversal flag | Yes |
| 6 | Match arriving deductions to programs, shipments and claim backup | No |
| 7 | Clear authorised deductions against the accrual | Yes |
| 8 | Raise a dispute for the unauthorised remainder | Pending approval |
| 9 | Run the controls library over the period | No |
| 10 | Route findings to the judgment engine | No |
| 11 | Draft flux commentary for accounts over materiality | No |
| 12 | Package the period for close reviewer sign-off | No |

### Verifiability gates

These are assertions. A failure **blocks the period**, it does not warn.

- Prior accrual reversal nets to zero against cleared deductions
- Deduction cleared is less than or equal to the accrued liability for that program
- Debits equal credits on every posted entry
- No accrual aged beyond two periods without a deduction
- The deduction's claimed period falls inside the program window

Anything that cannot be verified from the agreement escalates instead of posting. Say this out loud in the demo — it is Hyphenate's own stated philosophy, enacted: *if something is not verifiable, escalate.*

## Judgment, escalation and restatement

### The judgment engine

Every finding passes through the same gate:

```
finding
  └─ match precedent(control_id, conflict_type, customer_id)?
       ├─ HIT  → apply stored decision, log it, continue silently
       └─ MISS → classify escalation type
                   ├─ authority        → controller
                   ├─ source conflict  → customer team analyst
                   ├─ low confidence   → controller, ambiguity quoted
                   └─ SoD violation    → throws, hard block
                 → human answers
                 → write precedent row
                 → next run passes silently
```

The source-conflict escalation asks the question in Hyphenate's own words: **"Which is the source of truth?"** The human picks, the answer is stored, and the same situation never escalates again. Show this loop closing on screen — mine the finding, escalate, answer, then step the month and watch it pass without a word.

### Segregation of duties

`can_approve(actor, claim)` raises an exception when the actor negotiated the agreement the claim arises from. Not a prompt instruction — a capability check in code that throws.

```python
def can_approve(actor: Role, claim: Claim) -> None:
    if claim.program.negotiated_by == actor.id:
        raise SegregationOfDutiesError(
            f"{actor.name} negotiated {claim.program_id} for "
            f"{claim.customer}; approval routed to controller."
        )
```

Demo it live: the sales lead tries to approve the adjustment on the program he negotiated, and the request fails with a readable reason. Thirty seconds, and it answers *would you hire it* better than any feature.

### Rejections carry reasoning

When the controller says no, the reason becomes a precedent — not just a blocked action. Hyphenate called this out specifically. The precedent row stores `decision`, `reasoning`, `decided_by`, `decided_at`, and the next matching finding applies it without asking.

### Restatement — the novelty

Event-driven, not scheduled. Triggers:

- A program amendment lands with a `valid_from` inside a closed period
- Actual redemption diverges from the projected rate beyond tolerance
- A dispute resolves against us

The path:

1. Re-derive `deal_terms` as of the amendment's **valid time**
2. Re-evaluate closed periods *as of new knowledge*, reading the bitemporal ledger at the new `decision_time`
3. Diff against what was posted — produce a catch-up or clawback entry
4. Draft flux commentary explaining the variance to the controller
5. Preserve **both** reasonings side by side

That last step is the whole point. The interrogation box answers two different questions about the same entry:

| Question | Answer source |
| --- | --- |
| Why did you post $180k in February? | The ledger as of `decision_time` = February. Correct on what was known. |
| Why is February now $214k? | The ledger as of `decision_time` = August. The amendment changed the base. |

A control firing on the system's own earlier conclusions is the thing an existing autonomous-finance product does not have. Lead with it.

## Flux commentary and close sign-off

Flux is period-over-period change with a written explanation of why. It is a control activity, not reporting, and it is what the close reviewer signs.

**Why it belongs here:** a large swing in accrued trade promotion liability is almost always an accrual artifact — booked this month and reversed next, or double-counted because the deduction landed and the accrual was never cleared. A system that posts accruals should already know what flux it will create.

### How it runs

1. Materiality picks the accounts needing commentary — the threshold is mined per account, not configured
2. Drill to transaction-level drivers: tier crossing, amendment, dispute resolution, accrual reversal, returns netting
3. Draft the narrative **citing the exact journal lines**, never prose from memory
4. Close reviewer approves or sends back
5. Commentary and approval are retained against the period for audit

### What good output looks like

> **Accrued trade promotion liability, August: $214,350 vs $180,100 July (+19.0%)**
>
> Driven by Walmart program amendment TP-0214 dated 2026-02-14, applied 2026-08-19, which changed the scan-back rate and therefore the accrual base. $34,250 of the movement is a catch-up for periods Feb–Jul (entries JE-1181 through JE-1186). The remaining $4,100 is ordinary August shipment volume. The original Feb–Jul accruals were correct on the terms known at the time; the amendment was not in the system until August.

Every number in that paragraph links to an entry. Hyphenate's framing is *ask any number and trace it straight to the entry behind it* — so a flux narrative is driver-linked, not written.

### Sign-off

The close reviewer sees one package: the period's postings, every control that fired, every escalation and its answer, the flux commentary, and the verifiability gate results. Signing locks the period. Restatement is the only way back in, and it writes new rows rather than editing locked ones.

## Data model

Everything bitemporal: `valid_time` is when a fact was true in the world, `decision_time` is when we learned it. Nothing is ever updated in place — a correction is a new row with a later `decision_time`. That single choice buys the audit trail, the "what did you know in March" answer, and restatement.

```sql
-- Layer 0: the source systems
CREATE TABLE customers (
  id TEXT PRIMARY KEY, name TEXT, channel TEXT   -- Walmart, Costco, Kroger
);

CREATE TABLE trade_programs (
  id TEXT PRIMARY KEY, customer_id TEXT, document_text TEXT,
  program_type TEXT,          -- off_invoice | scan_back | display | mdf
  signed_date DATE, negotiated_by TEXT    -- the sales lead. SoD hinges on this.
);

CREATE TABLE shipments (
  id TEXT PRIMARY KEY, customer_id TEXT, period TEXT,
  cases INT, gross_price NUMERIC, ship_date DATE,
  returned_cases INT DEFAULT 0
);

CREATE TABLE invoices (
  id TEXT PRIMARY KEY, customer_id TEXT, period TEXT,
  gross_amount NUMERIC, invoice_date DATE
);

CREATE TABLE deductions (
  id TEXT PRIMARY KEY, invoice_id TEXT, customer_id TEXT,
  program_id TEXT,            -- often null: the matching problem
  amount NUMERIC, reason_code TEXT,
  taken_date DATE,            -- months after the promo period
  claimed_period TEXT,        -- the period the customer says it relates to
  cleared_by TEXT, approved_by TEXT       -- never the same actor
);

CREATE TABLE claim_backup (
  id TEXT PRIMARY KEY, deduction_id TEXT,
  scan_units INT, scan_rate NUMERIC,
  proof_of_performance BOOLEAN, received_date DATE
);

CREATE TABLE disputes (
  id TEXT PRIMARY KEY, deduction_id TEXT, disputed_amount NUMERIC,
  raised_date DATE, resolution TEXT,      -- upheld | recovered | partial
  resolved_date DATE, resolution_amount NUMERIC
);
```

```sql
-- Layer 1: the context graph
CREATE TABLE program_terms (
  id TEXT PRIMARY KEY, program_id TEXT, customer_id TEXT,
  program_type TEXT,            -- off_invoice | scan_back | display | mdf
  rate NUMERIC,
  rate_unit TEXT,               -- 'per_case' | 'pct_of_gross'
  base_definition TEXT,         -- 'shipped_cases' | 'scan_units' | 'gross_sales'
  projected_redemption NUMERIC, -- scan-back: expected sell-through. The estimate.
  window_start DATE, window_end DATE,
  requires_proof BOOLEAN,       -- display/feature funds
  source_clause_id TEXT,
  valid_from DATE, valid_to DATE,
  decision_time TIMESTAMP       -- when WE learned this term existed
);
```

`projected_redemption` is the field the whole project turns on. It is the estimate you accrue at, and the thing actual deductions prove right or wrong months later.

```sql
-- Layer 2: the controls library
CREATE TABLE controls (
  id TEXT PRIMARY KEY,
  name TEXT,
  condition TEXT,           -- an evaluable expression, not prose
  threshold NUMERIC,
  threshold_unit TEXT,      -- 'usd' | 'pct' | 'periods'
  owner_role TEXT,          -- who this escalates to
  precedent_ids TEXT[],     -- the historical entries that taught it
  mined_at TIMESTAMP,
  status TEXT               -- active | retired | tuned
);
```

```sql
-- Layer 3: judgment
CREATE TABLE findings (
  id TEXT PRIMARY KEY, period TEXT, customer_id TEXT, control_id TEXT,
  severity TEXT, amount NUMERIC,
  exposure NUMERIC,         -- dollars at risk, drives escalation lane
  confidence NUMERIC,       -- below threshold → low_confidence escalation
  state TEXT,               -- open | auto_resolved | escalated | resolved
  escalation_type TEXT,     -- authority | source_conflict | low_confidence | sod
  evidence JSONB,           -- ids of every row that triggered it
  created_at TIMESTAMP
);

CREATE TABLE precedents (
  id TEXT PRIMARY KEY, control_id TEXT, conflict_type TEXT, customer_id TEXT,
  decision TEXT,            -- which source won, or approve | reject
  reasoning TEXT,           -- rejections carry reasoning
  decided_by TEXT, decided_at TIMESTAMP,
  from_escalation_id TEXT
);

CREATE TABLE escalations (
  id TEXT PRIMARY KEY, finding_id TEXT, to_role TEXT,
  question TEXT, options JSONB,
  answer TEXT, answered_at TIMESTAMP,
  became_precedent_id TEXT
);
```

```sql
-- Layer 4: the bitemporal ledger
CREATE TABLE ledger_entries (
  id TEXT PRIMARY KEY, journal_id TEXT,
  period TEXT, account TEXT,
  debit NUMERIC DEFAULT 0, credit NUMERIC DEFAULT 0,
  memo TEXT,
  reversal_of TEXT,         -- the accrual this reverses
  restates TEXT,            -- the entry this restates
  source_finding_id TEXT,
  valid_time DATE,          -- the period it belongs to
  decision_time TIMESTAMP,  -- when we knew it
  approved_by TEXT
);

CREATE TABLE periods (
  period TEXT PRIMARY KEY,
  state TEXT,               -- OPEN|ACCRUED|CONTROLLED|ESCALATED|REVIEWED|SIGNED|CLOSED|RESTATED
  signed_by TEXT, signed_at TIMESTAMP,
  gate_results JSONB
);

CREATE TABLE flux_commentary (
  id TEXT PRIMARY KEY, period TEXT, account TEXT,
  current_balance NUMERIC, prior_balance NUMERIC, pct_change NUMERIC,
  narrative TEXT, driver_entry_ids TEXT[],
  approved_by TEXT
);
```

### The one query that matters

Everything the interrogation box does reduces to this:

```sql
-- the books as they stood at a point in time
SELECT account, SUM(debit) - SUM(credit) AS balance
FROM ledger_entries
WHERE period = :period
  AND decision_time <= :as_of
GROUP BY account;
```

Run it with `as_of` = February and you get what was posted. Run it with `as_of` = August and you get the restated truth. Same table, same period, two correct answers. Put both on screen at once.

## Seed data and the proof harness

### What is real and what is simulated

Say this unprompted in the demo. It answers *is it real enough* without overclaiming, which beats pretending synthetic data is real.

|  | Source |
| --- | --- |
| **Real** | General Mills is a public company. Net sales, cost of sales, segment mix, customer concentration and the revenue-recognition treatment of trade promotions as variable consideration all come from the FY2025 10-K on SEC EDGAR. Walmart, Costco and Kroger are its real customers. |
| **Simulated** | 24 months of shipments, invoices, deductions, claim backup and disputes at transaction level |
| **How we know it works** | 50 planted errors with an answer key; precision and recall reported on screen |

Transaction-level trade data is never public on either side of this trade — not in any filing, anywhere. Do not spend time looking for it. What the filings give you is the shape of the business and the accounting policy, and that is what makes the simulation defensible.

### The generator

One script, fixed seed, deterministic. Use `faker` plus explicit rules, **never a model** — the answer key has to be exact and you need to regenerate reproducibly when something breaks at 4am.

```
scripts/seed.py --seed 1337 --months 24
  months  1–12  → history, for onboarding to learn from
  months 13–24  → the live year the demo steps through
```

Walmart's actual sell-through must drift away from the projected redemption rate month by month, so the accrual estimate genuinely moves. That drift is what makes the restatement real rather than staged.

### The 50 planted errors

Each row of `answer_key.json` carries `error_id`, `type`, `period`, `vendor`, `amount`, `expected_control_id`, `expected_escalation_type`.

| Type | Count | What the system should do |
| --- | --- | --- |
| Program amendment not applied to the accrual | 1 | **The moment.** Restate 6 periods, catch-up entry, flux narrative. |
| Duplicate deduction for one program period | 6 | Auto-resolve from mined control |
| Scan-back claim with no backup | 8 | Block, escalate to deduction analyst |
| Returns not netted from promoted volume | 7 | Auto-resolve, reduce accrued liability |
| Deduction outside the program window | 3 | Block, escalate to controller |
| Transposed digits in deduction amount | 5 | Flag above tolerance, pass below it |
| Accrual never cleared after the deduction landed | 4 | Gate failure, blocks the period |
| Deduction claiming a period that straddles quarter end | 5 | Escalate, low confidence |
| Sales lead self-approval attempt | 2 | **Throws.** Hard block. |
| Program terms genuinely ambiguous | 3 | Escalate as source conflict |
| Small variances within learned tolerance | 6 | Pass silently — these are the **true negatives** |

That last row matters as much as the rest. A system that escalates everything has perfect recall and is useless. The six in-tolerance variances are how you prove precision.

### The metric

```
scripts/evaluate.py --as-of month-1 --as-of month-9
```

Report four numbers, on screen, in the demo:

- **Precision** — of the findings raised, how many were real errors
- **Recall** — of the planted errors, how many were caught
- **Escalation rate** — findings sent to a human ÷ total findings. This should *fall* between month 1 and month 9 as precedents accumulate.
- **Autonomy** — periods closed with no human touch

The falling escalation rate is your self-improvement proof, and it is a number rather than a claim. Hyphenate said 50% automation of a hard workflow is still 50% ROI — so do not hide a mid-range number, frame it.

## The UI surface

Four things. Resist adding a fifth.

### 1 · Month stepper

A clock control at the top: **‹ Month 8 · August 2026 ›** with a Step button. Clicking advances the simulated month, transactions land, the agent wakes and runs.

This is not a demo hack — present it as how the product is operated, because it solves the real problem that the system works over months and you have three minutes. It also means you can replay any scenario on demand when Hyphenate hands you one of their own, which the brief warns they may do.

### 2 · Controls table

The centrepiece. Hyphenate's own vocabulary on screen.

| Rule | Threshold | Owner | Precedent | Fired |
| --- | --- | --- | --- | --- |
| Deduction > accrued liability | $2,500 | Trade promo acct | 7 entries | 12× |
| Scan-back without backup | any | Deduction analyst | 3 entries | 8× |
| Scan units ≠ shipped cases | 0.5% | Trade promo acct | 22 entries | 2× |

Every precedent cell is clickable and opens the historical entries that taught the rule. Rows added after onboarding are visually marked as **learned** — that is the self-improvement proof a judge can see without reading a metric.

### 3 · Escalation inbox

Three lanes, one per human role, so it is visibly not agents talking to agents. Each card shows the question, the evidence, and the options.

> **To: Customer team — Walmart** Deduction DD-3391 claims period 2026-03 at $0.42/case. Program TP-0214 as signed says $0.38/case. Claim backup has not arrived. **Which is the source of truth?** ◦ Program as signed ◦ Customer's claimed rate ◦ Hold until backup arrives ◦ Escalate to controller

When answered, the card collapses into a precedent row with a visible link to the control it now governs. Step the month and show the same conflict passing silently.

### 4 · Interrogation box

A text input with placeholder *"Ask it why it did anything."* Invite the judges to use it — this is where you win the "defends a decision when questioned" criterion.

Answers walk the evidence chain:

```
JE-1184 · Feb accrual · Walmart scan-back · $180,100
  rule       Accrue promo liability at projected redemption
  terms      trade_programs#TP-0214 clause 4.2, rate $0.38/case
  inputs     SH-0412..SH-0488, 8,230 cases shipped
  knew-at    2026-02-28 — amendment AM-02 not yet in system
  approved   controller@genmills, 2026-03-02 09:14
  restated   JE-1251 on 2026-08-19 (+$34,250)
```

Build this as a first-class surface, not a log viewer. It is the single highest-leverage UI element for this track.

## Four-person work split

The risk with four people is everyone waiting on the schema. Kill that in the first hour: **one person writes the full DDL and commits it before anyone else writes a line.** Everything below assumes that is done by hour 1.

|  | Owner | Owns | Blocked by |
| --- | --- | --- | --- |
| **A** | Data & ledger | Schema, seeder, answer key, bitemporal ledger, verifiability gates, the as-of query | Nothing. Starts immediately. |
| **B** | Agent core | Onboarding replay, control mining, the period state machine, restatement | A's schema (hour 1), then independent |
| **C** | Judgment & humans | Judgment engine, precedents, SoD capability layer, the three model-played roles, escalation drafting | A's schema (hour 1) |
| **D** | Surface & story | All four UI panels, the API contract, flux rendering, demo video, pitch | Mock JSON until hour 10 |

### The contracts between you

Agree these four shapes in the first hour and nobody blocks after that. D builds against mock fixtures of exactly these until the real endpoints land.

```
GET  /api/period/{period}        → { state, postings[], findings[], gates{}, flux[] }
POST /api/period/{period}/step   → advances the clock, runs the cycle
GET  /api/controls               → [{ id, name, threshold, owner, precedent_ids, fired_count, learned }]
GET  /api/escalations?open=true  → [{ id, to_role, question, options[], evidence{} }]
POST /api/escalations/{id}/answer → { answer } ⇒ writes precedent
GET  /api/explain/{entry_id}     → the evidence chain
GET  /api/metrics?as_of={period} → { precision, recall, escalation_rate, autonomy }
```

### Pairing points

Three moments where two people must sit together or it will not integrate:

- **Hour 6** — A and B on the ledger write path. Accrual, reversal and restatement all write through one function or you will have three inconsistent ones.
- **Hour 12** — B and C on the finding-to-escalation handoff. The `evidence` blob shape has to satisfy both the escalation card and the interrogation box.
- **Hour 20** — C and D on the interrogation box. It reads from more tables than anything else and is the most likely thing to be half-built at 6am.

### Who presents

Two people pitch, two run the laptop. The person who built the judgment engine (C) should answer the interrogation questions live, because they will know why any given decision was made without looking it up.

## Hour-by-hour

Submission closes Sunday 9:00 AM PT, hard. The plan ends at 6:00 AM with three hours of slack, because something will break.

### Friday night — 11pm to 3am

| Time | A · Data | B · Agent | C · Judgment | D · Surface |
| --- | --- | --- | --- | --- |
| 11p–12a | **Write the full DDL. Commit it.** | Agree API contract with D | Agree evidence blob shape | Agree API contract, scaffold Vite app |
| 12a–2a | Seeder: 24 months, 3 vendors | Attainment + earned-rebate math, pure functions | Role definitions, `can_approve` with the throw | Month stepper + period view against mocks |
| 2a–3a | Answer key, 50 errors | Accrual / reversal / true-up | Escalation card generation | Controls table against mocks |

**Checkpoint 3am:** seeder runs, `pytest` on the rebate math passes, UI renders mock data. If the seeder is not done, everyone stops and helps A.

### Saturday — 3am to 3pm

| Time | A | B | C | D |
| --- | --- | --- | --- | --- |
| 3a–6a | Bitemporal ledger + as-of query | Period state machine | Judgment gate, precedent store | Escalation inbox |
| 6a–8a | *Sleep in shifts — two down, two up, rotate* |  |  |  |
| 8a–11a | Verifiability gates as assertions | **Onboarding replay + control mining** | Model-played humans answering | Interrogation box |
| 11a–12p | Wire real API, kill the mocks — all four |  |  |  |
| 12p–3p | **Restatement path** (A+B pair) |  | Precedent loop closing | Flux rendering |

**Checkpoint 3pm:** step month 1 → 9 end to end without a crash. Go to the Hyphenate booth and show them. This is the most valuable 20 minutes of the weekend — you get feedback with 18 hours left to act on it.

### Saturday evening — 3pm to 11pm

| Time | What |
| --- | --- |
| 3p–5p | The moment: amendment → restate → catch-up → flux. Make it work perfectly. |
| 5p–7p | `evaluate.py`, precision/recall/escalation rate at month 1 and month 9 |
| 7p–8p | Metrics panel on screen |
| 8p–9p | **Hostile judge rehearsal.** One teammate attacks the interrogation box for a full hour. |
| 9p–11p | Fix everything that rehearsal broke |

### Sunday — 11pm to 6am

| Time | What |
| --- | --- |
| 11p–1a | Record the demo video. Open on the moment. |
| 1a–3a | Devpost write-up, README, architecture diagram, seats line |
| 3a–5a | Buffer. Something is broken; this is where you fix it. |
| 5a–6a | Submit. **Do not wait for 9am.** |
| 6a–9a | Sleep, then rehearse the live pitch twice before judging |

### Three rules for the night

1. **Freeze the fiction at midnight.** Names, vendors, amounts — settled, never revisited.
2. **Commit on green only.** One broken main at 4am costs more than any feature gains.
3. **If a thing is not on screen by Saturday 8pm, it is cut.** No exceptions, including the restatement — although if the restatement is cut, the project is cut, so protect it above everything.

## The demo

### The moment

Month 8. The agent has raised an alert on its own: **under-accrued trade promotion liability, Walmart, $1.4M across six periods.**

A February amendment changed the scan-back rate on program TP-0214. The accrual base is a function of that rate, so every accrual from February onward was booked low. Nobody applied the amendment. Deductions arriving in Q3 reflect the new rate, and the gap is what exposed it. The system caught it, restated six closed periods, posted the catch-up, drafted the flux commentary — and when the sales lead who negotiated TP-0214 tried to approve the adjustment, it threw.

Open the video on this. Do not open on architecture.

### Run order, three minutes

| Time | On screen | You say |
| --- | --- | --- |
| 0:00 | The month-8 alert | "It found this by itself." Click into the evidence chain. |
| 0:15 | — | The seats line. Then: it accrues when product ships, matches the deduction months later, clears what's authorised, posts every entry with an approver. |
| 0:45 | Rewind to month 1, controls table | "It read the trade programs and 12 months of history and mined these rules. Every one cites the entries that taught it." Click a precedent. |
| 1:15 | Step months 2–6 | It runs. Accruals, deductions, clearing. Nobody is watching. |
| 1:35 | Escalation card | "Which is the source of truth?" Answer it. Step again — silent. |
| 2:00 | The SoD throw | Sales lead tries to approve his own program. It fails, with a reason. |
| 2:15 | Month 8, full restatement | Catch-up entry, flux narrative, both reasonings side by side. |
| 2:35 | Metrics panel | Precision, recall, escalation rate at month 1 vs month 9. |
| 2:50 | Interrogation box | "Ask it why it did anything." Hand them the keyboard. |

### The close

> Deductions are the one finance workload with free ground truth. Every claim comes back accepted or disputed, so thresholds tune against reality instead of being guessed. That is why this function can actually be made autonomous.

That line is your differentiator. Most teams will not have one.

### Interrogation rehearsal

One teammate plays hostile judge for a full hour Saturday evening. The questions that will come:

- *What did it know in March?*
- *What if the amendment had been ambiguous?*
- *What if the controller had said no?*
- *Show me something it got wrong.*
- *Why didn't it escalate this one?*
- *What's real and what's simulated?*
- *Could the agent approve its own claim if it tried?*

The fifth is the one that catches teams out. The answer is: a mined tolerance covered it, here is the control, here are the 22 historical variances that set the threshold.

Have an answer to *show me something it got wrong* ready and rehearsed. Volunteering a failure is the most credible thing you can do in a demo, and the planted-error key means you can point at precisely which ones it missed and why.

## Cut list and submission

### Cut in this order, without debate

1. Apify Actor — a side prize, not part of this story
2. Defective allowance (Mirado) entirely
3. Co-op advertising (Calder) — leaves Northfield alone, which is all the moment needs
4. Flux narrative polish — a structured table beats a bad paragraph
5. The third escalation lane
6. Onboarding replay animation — a static mined table is fine

Hyphenate said *the best solutions are usually very simple* and that a simple thing done perfectly over-indexes in judging. Cutting to one vendor is not a retreat, it is the strategy.

### Never cut

- The bitemporal ledger
- The restatement path
- The precedent store and the closing loop
- The segregation-of-duties throw
- The precision/recall number
- The interrogation box

If four of these six work and nothing else does, you still place. If all the features work and these do not, you do not.

### Submission checklist

- [ ] GitHub repo, public, with README
- [ ] Project image
- [ ] Demo video opening on the moment, under 3 minutes
- [ ] One-line seats statement in the description
- [ ] Proof section: what is real, what is simulated, precision and recall
- [ ] Architecture diagram in the README
- [ ] Submitted by **6:00 AM Sunday**, not 9:00
- [ ] Also submitted to Microsoft "Built for the Real World" — reframe around controller hours eliminated and dollars recovered
- [ ] Also submitted to CRS Best Financial AI Agent
- [ ] Cal Hacks Most Technically Advanced Hack

### Recruiting, which is the real prize

Hyphenate's top five get expedited interviews — wider than the cash. The MIT precedent was a paid week in NYC, and one person converted it to a full-time offer. Najeeb said the filter is **agency and ownership, not polish.**

- Show them something at the 3pm Saturday checkpoint. Say *you told us the agent lives in controls and monitoring, so here is our controls table.*
- Collect names: Ray, Najeeb, Radhika, and whichever engineer you talk to at the booth.
- Microsoft 2nd place and both CRS $0-cash prizes pay in interviews and are the least contested at the event.
- The Devpost page outlives the weekend. Write it for someone reading it in March.
