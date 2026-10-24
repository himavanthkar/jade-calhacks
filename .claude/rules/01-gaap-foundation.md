# GAAP Foundation: Accounts Receivable + Trade Promotion Accruals

Objective: Build one accounting system that manages trade promotion deductions, validates customer claims, clears Accounts Receivable (AR), and reconciles promotional accruals under U.S. GAAP.

The system must answer four questions for every deduction:

1. **Is it authorized?** Does the customer have a valid contractual or promotional entitlement?
2. **What should be cleared?** Which invoices and accrued liabilities should be settled?
3. **What should be disputed?** Is the amount unsupported, duplicated, excessive, or otherwise invalid?
4. **When does a human intervene?** Is there insufficient evidence, significant judgment, or a material accounting exception?

## Standards

| Standard | Basic rule | System implication |
| --- | --- | --- |
| ASC 606 — Revenue Recognition | Customer rebates, discounts, and most trade promotions reduce revenue rather than create operating expenses. | Accrue qualifying promotional obligations as reductions of revenue. |
| ASC 606 — Variable Consideration | Estimate expected customer incentives using supportable information, subject to the constraint on variable consideration. | Calculate accruals using approved rates, eligible sales, historical claims, and current expectations. |
| ASC 606 — Distinct Goods or Services | Payments to customers for qualifying distinct services may be recorded as purchases or expenses rather than revenue reductions. | Classify promotion types before deciding which account to debit. |
| ASC 326 — Credit Losses | Receivables must be evaluated for expected credit losses. | Distinguish legitimate price concessions from unpaid receivables that create credit risk. |
| Accrual accounting | Recognize liabilities and related accounting effects in the appropriate period, not merely when an invoice or payment arrives. | Estimate obligations before settlement, then reconcile and adjust as actual information becomes available. |

ASC 606-10-32-25 through 32-27 (consideration payable to a customer) and ASC 606-10-32-5 through 32-13 (variable consideration) are particularly important.

**Important distinction:** a trade promotion accrual is not automatically an expense accrual. In the typical customer-rebate case it reduces revenue and creates a liability. A vendor's unbilled work, by comparison, may produce an expense and an accrued payable.

## Journal entry example — trade promotion

A company ships $1,000 of merchandise, recognizes revenue at shipment because control transfers then, and expects a valid 10% promotional deduction.

**At shipment**

| Account | Debit | Credit |
| --- | --- | --- |
| Accounts Receivable | $1,000 | |
| Sales Revenue | | $1,000 |
| Sales Discounts / Contra-Revenue | $100 | |
| Accrued Trade Promotions | | $100 |

Net revenue = $900. Trade promotion liability = $100.

**When the customer pays $900 and deducts an authorized $100**

| Account | Debit | Credit |
| --- | --- | --- |
| Cash | $900 | |
| Accrued Trade Promotions | $100 | |
| Accounts Receivable | | $1,000 |

Result: AR is fully cleared, the promotional accrual is fully used, and no additional revenue reduction is recorded.

If the customer instead deducted $120 but only $100 was valid, clear the $100 against the accrual and retain the disputed $20 as an open receivable, subject to reassessment of collectibility and potential price concessions.

## Accruals: the second seat (expense accruals)

For ordinary work completed but not yet billed, the accounting is different. A service provider completes $500 of work in September but invoices $520 in October:

| Stage | Journal entry |
| --- | --- |
| September accrual | Dr Expense $500; Cr Accrued Payable $500 |
| October invoice | Dr Accrued Payable $500; Dr Expense $20; Cr Accounts Payable $520 |

The $20 difference is a true-up, assuming it represents additional expense rather than an error requiring correction.

A trade promotion follows a similar estimate-to-settlement lifecycle but typically affects **contra-revenue, not expense**. The system must preserve that distinction.
