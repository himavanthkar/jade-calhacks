# Coupled Reconciliation, Controls, and Success Measures

## Reconciliation identity

The system maintains a common ledger of promotion obligations and settlements. For each promotion:

```
Ending Accrual = Beginning Accrual + New Accruals + Estimate Adjustments − Settled Claims
```

The system must continuously flag:

- **Orphan accruals:** liabilities remaining after promotional activity is completed and all expected claims are resolved.
- **Unmatched deductions:** short payments with no matching eligible promotion or authorization.
- **Estimate variances:** actual valid claims differing from expected promotional costs.
- **Duplicate settlements:** a deduction cleared in AR without correctly relieving the related accrual, or the same obligation settled more than once.

Residual accruals are not automatically errors: valid claims may still arrive later. Conversely, an unsupported claim does not automatically become an expense or a credit loss.

## Key controls and success measures

Track:

- deduction auto-resolution rate
- dispute recovery
- percentage of deductions missing backup
- unmatched AR aging
- accrual settlement rate
- accrual estimate accuracy
- dollar value of manual adjustments

## The most important operating rule

**One deduction produces one documented accounting resolution, with the corresponding AR and accrual effects reconciled.** The system must never quietly clear AR while leaving an associated liability outstanding, and must never reduce revenue twice for the same promotion.

## Sources and current GAAP status

- [Deloitte — ASC 606, Consideration Payable to a Customer](https://dart.deloitte.com/USDART/home/codification/revenue/asc606-10/roadmap-revenue-recognition/chapter-6-step-3-determine-transaction/6-6-consideration-payable-a-customer)
- [Deloitte — ASC 606, Variable Consideration](https://dart.deloitte.com/USDART/home/codification/revenue/asc606-10/roadmap-revenue-recognition/chapter-6-step-3-determine-transaction/6-3-variable-consideration)
- [Deloitte — ASC 326, Trade Receivables](https://dart.deloitte.com/USDART/home/codification/assets/32x/asc326-10/roadmap-credit-losses-cecl/chapter-5-application-cecl-model-off/5-2-trade-receivables-contract-assets)
- [Microsoft — Trade Allowance and Deduction Settlement](https://learn.microsoft.com/en-us/dynamics365/supply-chain/sales-marketing/trade-allowance)

**Regulatory update:** on October 22, 2026, FASB proposed clarifications to ASC 606 concerning payments made on behalf of customers or to customers' customers. These proposals are not yet effective GAAP.

These rules are a foundational system design, not a substitute for a company-specific accounting policy reviewed by its controller or auditor.
