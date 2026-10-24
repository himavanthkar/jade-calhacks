"""Shared vocabulary. Every workstream imports from here instead of inventing strings."""

import calendar
from datetime import date

# ── Calendar ────────────────────────────────────────────────────────────────
# Month 1 = 2025-01. Months 1–12 are history (onboarding), 13–24 the live year.
SIM_START = date(2025, 1, 1)
HISTORY_MONTHS = range(1, 13)
LIVE_MONTHS = range(13, 25)


def period_for_month(month: int) -> str:
    """Simulation month number (1-based) → 'YYYY-MM'."""
    year = SIM_START.year + (month - 1) // 12
    return f"{year}-{(month - 1) % 12 + 1:02d}"


def month_for_period(period: str) -> int:
    year, mon = (int(p) for p in period.split("-"))
    return (year - SIM_START.year) * 12 + mon


def live_month(period: str) -> int:
    """'2026-08' → 8, the number the UI stepper shows."""
    return month_for_period(period) - 12


def period_of(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def add_months(period: str, n: int) -> str:
    return period_for_month(month_for_period(period) + n)


def period_start(period: str) -> date:
    year, mon = (int(p) for p in period.split("-"))
    return date(year, mon, 1)


def period_end(period: str) -> date:
    year, mon = (int(p) for p in period.split("-"))
    return date(year, mon, calendar.monthrange(year, mon)[1])


# ── Chart of accounts ───────────────────────────────────────────────────────
class Account:
    GROSS_SALES = "4000 Gross sales"
    TRADE_PROMO_EXPENSE = "4100 Trade promotion expense"   # contra-revenue
    ACCOUNTS_RECEIVABLE = "1200 Accounts receivable"
    DEDUCTIONS_PENDING = "1250 Deductions pending resolution"
    DISPUTE_RECEIVABLE = "1260 Disputed deductions receivable"
    ACCRUED_TRADE_PROMO = "2300 Accrued trade promotion liability"
    WRITE_OFF = "6900 Deduction write-offs"

    ALL = (
        GROSS_SALES, TRADE_PROMO_EXPENSE, ACCOUNTS_RECEIVABLE, DEDUCTIONS_PENDING,
        DISPUTE_RECEIVABLE, ACCRUED_TRADE_PROMO, WRITE_OFF,
    )


# ── ID prefixes ─────────────────────────────────────────────────────────────
class Prefix:
    PROGRAM = "TP"
    AMENDMENT = "AM"
    SHIPMENT = "SH"
    INVOICE = "INV"
    DEDUCTION = "DD"
    BACKUP = "CB"
    DISPUTE = "DS"
    HISTORICAL_DECISION = "HD"
    TERM = "PT"
    CONTROL = "CTL"
    FINDING = "FN"
    ESCALATION = "ESC"
    PRECEDENT = "PR"
    JOURNAL = "JE"
    FLUX = "FX"


def make_id(prefix: str, n: int, width: int = 4) -> str:
    return f"{prefix}-{n:0{width}d}"


# ── Enumerations mirrored from the CHECK constraints in db/schema.sql ───────
CUSTOMERS = {"WMT": "Walmart", "COST": "Costco", "KR": "Kroger"}

PROGRAM_TYPES = ("off_invoice", "scan_back", "display", "mdf")
RATE_UNITS = ("per_case", "pct_of_gross", "lump_sum")
BASE_DEFINITIONS = ("shipped_cases", "scan_units", "gross_sales", "fixed")

ROLES = (
    "sales_lead", "customer_team_analyst", "controller", "close_reviewer",
    "trade_promotion_accountant", "deduction_analyst", "agent",
)

PERIOD_STATES = ("OPEN", "ACCRUED", "CONTROLLED", "ESCALATED", "REVIEWED", "SIGNED", "CLOSED", "RESTATED")
LOCKED_STATES = ("SIGNED", "CLOSED")

ENTRY_TYPES = ("opening", "revenue", "accrual", "reversal", "clearing", "dispute", "restatement", "adjustment")


# ── Control ids ─────────────────────────────────────────────────────────────
# Stable slugs the miner (B) must emit and the answer key refers to. The seeder
# plants history that teaches each one; segregation of duties is code, not a control.
class Control:
    DED_GT_ACCRUAL = "CTL-DED-GT-ACCRUAL"            # deduction > accrued program liability, $2,500
    SCAN_NO_BACKUP = "CTL-SCAN-NO-BACKUP"            # scan-back claim with no backup, any
    OUTSIDE_WINDOW = "CTL-OUTSIDE-WINDOW"            # claimed period outside program window, any
    STALE_ACCRUAL = "CTL-STALE-ACCRUAL"              # accrual aged without a deduction, periods
    CLAIM_VS_BACKUP = "CTL-CLAIM-VS-BACKUP"          # deduction ≠ backup units × rate, 0.5%
    DUPLICATE_DEDUCTION = "CTL-DUPLICATE-DEDUCTION"  # same program, period and amount twice
    RETURNS_NOT_NETTED = "CTL-RETURNS-NOT-NETTED"    # late returns against accrued volume
    NO_PROOF = "CTL-NO-PROOF"                        # display claim without proof of performance
    PERIOD_STRADDLE = "CTL-PERIOD-STRADDLE"          # claim spans a quarter end
    RATE_CONFLICT = "CTL-RATE-CONFLICT"              # claimed rate ≠ program rate
    WRITEOFF_AUTHORITY = "CTL-WRITEOFF-AUTHORITY"    # write-off over $10,000 needs the controller
    REDEMPTION_DRIFT = "CTL-REDEMPTION-DRIFT"        # actual vs projected redemption beyond tolerance

    ALL = (
        DED_GT_ACCRUAL, SCAN_NO_BACKUP, OUTSIDE_WINDOW, STALE_ACCRUAL, CLAIM_VS_BACKUP,
        DUPLICATE_DEDUCTION, RETURNS_NOT_NETTED, NO_PROOF, PERIOD_STRADDLE, RATE_CONFLICT,
        WRITEOFF_AUTHORITY, REDEMPTION_DRIFT,
    )
    # A capability check in code, not a mined rule, so it sits outside ALL.
    SOD = "CTL-SOD"                                  # approver negotiated the program the claim arises from

ESCALATION_TYPES = ("authority", "source_conflict", "low_confidence", "sod")
FINDING_STATES = ("open", "auto_resolved", "escalated", "resolved")

# answer_key.json `type` values, with their planted counts (sum = 50).
PLANTED_ERROR_COUNTS = {
    "amendment_not_applied": 1,
    "duplicate_deduction": 6,
    "scan_back_no_backup": 8,
    "returns_not_netted": 7,
    "deduction_outside_window": 3,
    "transposed_digits": 5,
    "accrual_never_cleared": 4,
    "straddles_quarter_end": 5,
    "sales_lead_self_approval": 2,
    "ambiguous_terms": 3,
    "within_tolerance": 6,   # true negatives: must pass silently
}
