"""The frozen fiction. Names, programs, rates and volumes are settled here and nowhere else.

General Mills, Walmart, Costco and Kroger are real; every transaction is generated.
The headline parameters (TP-0214, AM-02, Walmart volume) were fixed by the team on 2026-10-24.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal as D

BRAND_FAMILY = "Cheerios family (Big G cereal)"

CUSTOMERS = [
    ("WMT", "Walmart", "mass"),
    ("COST", "Costco", "club"),
    ("KR", "Kroger", "grocery"),
]
CUSTOMER_ORDER = {c[0]: i for i, c in enumerate(CUSTOMERS)}

# (id, name, role, customer_id). Role titles only — the people are fictional.
ACTORS = [
    ("agent", "Trade promotion autonomy", "agent", None),
    ("controller", "Controller", "controller", None),
    ("close_reviewer", "Close reviewer", "close_reviewer", None),
    ("tpa.human", "Trade promotion accountant (prior year)", "trade_promotion_accountant", None),
    ("deductions.human", "Deduction analyst (prior year)", "deduction_analyst", None),
    ("sales.walmart", "Walmart sales lead", "sales_lead", "WMT"),
    ("sales.costco", "Costco sales lead", "sales_lead", "COST"),
    ("sales.kroger", "Kroger sales lead", "sales_lead", "KR"),
    ("team.walmart", "Walmart customer team analyst", "customer_team_analyst", "WMT"),
    ("team.costco", "Costco customer team analyst", "customer_team_analyst", "COST"),
    ("team.kroger", "Kroger customer team analyst", "customer_team_analyst", "KR"),
]
SALES_LEAD = {"WMT": "sales.walmart", "COST": "sales.costco", "KR": "sales.kroger"}
CUSTOMER_TEAM = {"WMT": "team.walmart", "COST": "team.costco", "KR": "team.kroger"}

# ── Volumes and prices, per customer per year ───────────────────────────────
MONTHLY_CASES = {("WMT", 2025): 560_000, ("WMT", 2026): 690_000,
                 ("COST", 2025): 140_000, ("COST", 2026): 145_000,
                 ("KR", 2025): 205_000, ("KR", 2026): 210_000}
CASE_PRICE = {("WMT", 2025): D("41.00"), ("WMT", 2026): D("42.00"),
              ("COST", 2025): D("37.50"), ("COST", 2026): D("38.00"),
              ("KR", 2025): D("41.50"), ("KR", 2026): D("42.50")}
SHIP_WEEKDAYS = {"WMT": (0, 1, 2, 3, 4), "COST": (1, 3), "KR": (0, 3)}   # Mon=0

# ── Customer behaviour ──────────────────────────────────────────────────────
WALMART_CLAIM_LAG_MONTHS = 5          # Feb claims land in July: the gap surfaces in Q3
WALMART_STREAMS = (("SB-SUPERCENTER", D("0.82")), ("SB-NEIGHBORHOOD", D("0.18")))
WALMART_PROGRAM_CITED = 0.6           # otherwise program_id is null: the matching problem
KROGER_CLAIM_LAG_MONTHS = 2
KROGER_NO_PROOF_RATE = 1 / 3
COSTCO_MDF_DAY = 20

# Walmart's actual sell-through as a fraction of shipped cases. 2025 tracks the
# projection; 2026 drifts away from it month by month so the estimate really moves.
REDEMPTION_2025_NOISE = 0.0005
REDEMPTION_2026_DRIFT_PER_MONTH = 0.0035
REDEMPTION_2026_NOISE = 0.002


@dataclass(frozen=True)
class Program:
    id: str
    customer_id: str
    program_type: str
    rate: D
    rate_unit: str
    base_definition: str
    projected_redemption: D | None
    window_start: date
    window_end: date
    requires_proof: bool
    signed_date: date
    ambiguity: str | None = None      # a clause written to be genuinely ambiguous

    @property
    def negotiated_by(self) -> str:
        return SALES_LEAD[self.customer_id]


def _q(year: int, q: int) -> tuple[date, date]:
    start = date(year, 3 * q - 2, 1)
    end = date(year, 3 * q, 31 if q in (1, 4) else 30)
    return start, end


PROGRAMS: list[Program] = [
    Program("TP-0114", "WMT", "scan_back", D("3.60"), "per_case", "scan_units", D("0.91"),
            date(2025, 1, 1), date(2025, 12, 31), False, date(2024, 12, 10)),
    Program("TP-0214", "WMT", "scan_back", D("3.80"), "per_case", "scan_units", D("0.92"),
            date(2026, 1, 1), date(2026, 12, 31), False, date(2025, 12, 9)),
    Program("TP-0121", "COST", "off_invoice", D("1.05"), "per_case", "shipped_cases", None,
            date(2025, 1, 1), date(2025, 12, 31), False, date(2024, 12, 3)),
    Program("TP-0221", "COST", "off_invoice", D("1.10"), "per_case", "shipped_cases", None,
            date(2026, 1, 1), date(2026, 12, 31), False, date(2025, 12, 2)),
    Program("TP-0122", "COST", "mdf", D("2280000.00"), "lump_sum", "fixed", None,
            date(2025, 1, 1), date(2025, 12, 31), False, date(2024, 12, 3)),
    Program("TP-0222", "COST", "mdf", D("2400000.00"), "lump_sum", "fixed", None,
            date(2026, 1, 1), date(2026, 12, 31), False, date(2025, 12, 2),
            ambiguity="2.3 Instalments are contingent on Customer meeting an annual volume "
                      "commitment of 1,700,000 cases."),
    *[Program(f"TP-013{q}", "KR", "display", D("155000.00"), "lump_sum", "fixed", None,
              *_q(2025, q), True, date(2024, 12, 12)) for q in (1, 2, 3, 4)],
    Program("TP-0231", "KR", "display", D("165000.00"), "lump_sum", "fixed", None,
            *_q(2026, 1), True, date(2025, 12, 11)),
    Program("TP-0232", "KR", "display", D("165000.00"), "lump_sum", "fixed", None,
            *_q(2026, 2), True, date(2025, 12, 11),
            ambiguity="3.1 Supplier pays $165,000.00 per event, payable upon feature in the weekly "
                      "circular and/or secondary end-cap display."),
    Program("TP-0233", "KR", "display", D("165000.00"), "lump_sum", "fixed", None,
            *_q(2026, 3), True, date(2025, 12, 11),
            ambiguity="3.4 An event running longer than seven days may be counted as two events."),
    Program("TP-0234", "KR", "display", D("165000.00"), "lump_sum", "fixed", None,
            *_q(2026, 4), True, date(2025, 12, 11)),
]
PROGRAM_BY_ID = {p.id: p for p in PROGRAMS}

# ── The moment ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Amendment:
    id: str
    program_id: str
    new_rate: D
    effective_date: date      # valid time: a Saturday, the start of a Walmart retail week
    signed_date: date
    available_at: date        # entered into the system


AMENDMENT = Amendment("AM-02", "TP-0214", D("4.20"), date(2026, 2, 14), date(2026, 2, 12), date(2026, 8, 19))


def true_rate(program: Program, on: date) -> D:
    """The rate actually in force on a date, as the retailer knows it."""
    if program.id == AMENDMENT.program_id and on >= AMENDMENT.effective_date:
        return AMENDMENT.new_rate
    return program.rate


def program_for(customer_id: str, program_type: str, on: date) -> Program | None:
    for p in PROGRAMS:
        if p.customer_id == customer_id and p.program_type == program_type and p.window_start <= on <= p.window_end:
            return p
    return None


# ── Documents ───────────────────────────────────────────────────────────────
def program_document(p: Program) -> str:
    customer = dict((c[0], c[1]) for c in CUSTOMERS)[p.customer_id]
    head = (f"TRADE PROMOTION AGREEMENT {p.id}\n"
            f"Between General Mills Sales, Inc. (\"Supplier\") and {customer} (\"Customer\").\n"
            f"Products: {BRAND_FAMILY}. Signed {p.signed_date.isoformat()}.\n\n"
            f"1. Term. This program runs from {p.window_start.isoformat()} through {p.window_end.isoformat()}.\n")
    if p.program_type == "scan_back":
        body = (f"4.1 Customer may claim a scan-back allowance on units of the Products scanned at "
                f"register during the term.\n"
                f"4.2 The allowance is ${p.rate} per case-equivalent unit scanned.\n"
                f"4.3 Claims must be supported by point-of-sale scan data and may be taken as a "
                f"deduction against open invoices.\n\n"
                f"Appendix A (Supplier internal planning, not part of the agreement): projected "
                f"redemption {int(p.projected_redemption * 100)}% of shipped cases.\n")
    elif p.program_type == "off_invoice":
        body = f"2.1 Supplier grants an off-invoice allowance of ${p.rate} per case shipped, taken at invoice.\n"
    elif p.program_type == "mdf":
        body = (f"2.1 Supplier will fund market development activities of ${p.rate:,.2f} for the term.\n"
                f"2.2 Customer may deduct the fund in twelve equal monthly instalments.\n")
    else:
        body = (f"3.1 Supplier pays ${p.rate:,.2f} per feature event, one event per month.\n"
                f"3.2 Each claim requires proof of performance: a circular tear sheet or store photograph.\n")
    if p.ambiguity:
        clause_no = p.ambiguity.split(" ", 1)[0]
        body = "\n".join(line for line in body.splitlines() if not line.startswith(clause_no)) + "\n" + p.ambiguity + "\n"
    return head + body


def amendment_document(a: Amendment) -> str:
    p = PROGRAM_BY_ID[a.program_id]
    return (f"AMENDMENT {a.id} TO TRADE PROMOTION AGREEMENT {p.id}\n"
            f"Signed {a.signed_date.isoformat()}.\n\n"
            f"Clause 4.2 is replaced in full, effective {a.effective_date.isoformat()}:\n"
            f"4.2 The allowance is ${a.new_rate} per case-equivalent unit scanned.\n"
            f"All other terms are unchanged.\n")
