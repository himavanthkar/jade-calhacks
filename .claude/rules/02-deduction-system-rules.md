# Core System Rules: Deductions, Clearing, and Escalation

These are automation and internal-control rules built on the GAAP principles in `01-gaap-foundation.md`.

| # | Rule | System action |
| --- | --- | --- |
| 1 | Every promotion must have identifiable terms, eligibility criteria, dates, and an approved owner. | Register the agreement and assign a unique promotion ID. |
| 2 | Estimate qualifying promotional obligations when the related revenue is recognized, if the incentive has been promised or is reasonably expected under ASC 606. | Debit contra-revenue; credit trade promotion liability. |
| 3 | Every customer short payment must be recorded and tracked. | Create a deduction record linked to the customer and remittance. |
| 4 | Every deduction must be matched against valid promotional activity. | Match by customer, promotion, invoice, SKU, eligible quantity, and applicable dates. |
| 5 | One remittance can contain multiple deductions. | Split bundled claims into separate identifiable items before settlement. |
| 6 | Valid deductions settle the corresponding liability and AR balance. | Clear the approved amount without recognizing the promotion twice. |
| 7 | A deduction exceeding its accrual must be investigated. | Reassess the estimate; adjust revenue for valid differences or dispute unsupported amounts. |
| 8 | A deduction without adequate supporting evidence cannot be automatically approved. | Hold for investigation, request documentation, or escalate. |
| 9 | Repeated claims or overlapping promotional allowances cannot be paid twice. | Detect duplicates and prevent duplicate settlement. |
| 10 | Residual accruals must be reconciled at each accounting close. | Identify unused balances, outstanding claims, and necessary estimate adjustments. |
| 11 | Uncollectible receivables must be distinguished from promotional liabilities. | Evaluate genuine credit exposure separately under ASC 326. |
| 12 | Every automated accounting decision must be traceable. | Retain source records, calculations, journal entry IDs, overrides, and approval history. |

This structure is consistent with real-world trade allowance workflows, including Microsoft's documented process for linking promotional claims, deductions, and AR settlements.

## Automated decision logic

```
Customer short-pays an invoice
        │
        ▼
Identify the customer, invoices, deductions, and promotion terms
        │
        ▼
Is the claim valid and supported?
(check eligibility, dates, amount, duplication, and supporting evidence)
        │
   ┌────┴─────────────────────┐
  Yes                    No / uncertain
   │                          │
 CLEAR                   HOLD / DISPUTE
 Apply to AR and         Keep unresolved amount
 accrual. Adjust         open and seek evidence.
 valid differences.
   └────────────┬─────────────┘
                ▼
     Reconcile AR + accruals
                │
                ▼
Escalate unresolved variances, aging, and material exceptions
```

**Human review is triggered by:** material differences, missing contract terms, conflicting evidence, unusual deductions, and accounting classification questions.

Specific dollar limits, tolerance percentages, and review deadlines must be established by company policy. GAAP does not prescribe universal automation thresholds — never hard-code a threshold as if it were a GAAP requirement.
