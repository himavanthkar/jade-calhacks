"""Company policy. Every automation threshold and tolerance that is not mined from history lives
here, with where it comes from. None of these are GAAP requirements: GAAP sets no automation
thresholds, and a controller can change any of them. Mined thresholds live in `controls`.
"""

from decimal import Decimal

# Company policy, not GAAP. A backup "variance" below this is the retailer rounding a blended
# rate, not a difference. Stated choice: setting it to zero changes no finding on the seed.
VARIANCE_NOISE_FLOOR_PCT = Decimal("0.01")

# Company policy, not GAAP. Redemption drift (actual vs projected sell-through) that teaches the
# library its CTL-REDEMPTION-DRIFT control. History cannot mine it: single history months drifted
# by up to 1.79% and no one acted, so there are no decisions to learn from, and a ceiling over
# that noise (2.5%) would never fire on the live year's sustained climb (0.71% to 2.22%).
# Stated choice: one point of sell-through, until enough live months exist to mine one.
DRIFT_TOLERANCE_PCT = Decimal("1.0")
DRIFT_OWNER = "trade_promotion_accountant"

# Company policy, not GAAP. Flux commentary covers an account whose month-on-month change exceeds
# this share of the history year's mean monthly accrual (rounded up to a nice number), with a
# floor for an account that history never moved.
MATERIALITY_RATE = Decimal("0.001")
MATERIALITY_FLOOR = Decimal("1000")

# Company policy, not GAAP. Severity bands by dollars at risk; the lowest band starts at the
# mined DED-GT-ACCRUAL tolerance ($2,500) so "low" means "within what the agent may true up".
SEVERITY_BANDS = ((Decimal("250000"), "critical"), (Decimal("50000"), "high"), (Decimal("2500"), "medium"))

# Company policy, not GAAP. How sure the agent is that a check's facts settle the question.
# A quarter-straddling claim's period can't be verified on its own; a customer's written reading
# of a clause our terms don't settle is less certain still.
STRADDLE_CONFIDENCE = Decimal("0.5")
TERMS_READING_CONFIDENCE = Decimal("0.4")
# Below this the judgment engine escalates as low confidence: it cannot verify from the agreement.
LOW_CONFIDENCE = Decimal("0.6")

# Company policy, not GAAP. The close's analytical review compares accrued trade promotion
# liability as a share of annualized net sales with General Mills' reported ratio (its latest
# 10-K at the time). A ratio more than this far off, either way, needs the reviewer's
# explanation before signing. Set before looking at the simulation: the analytical-review
# convention that a difference above half the expectation is never explained away as noise.
ANALYTICAL_REVIEW_TOLERANCE = Decimal("0.5")

# Company policy, not GAAP. A card unanswered this many days by the close goes up to the
# controller, who owns the close: approvers are busy, and the close shouldn't wait on silence.
CARD_FOLLOW_UP_DAYS = 10
