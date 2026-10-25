"""The problem, in cited numbers: what the Overview, the Ask box and the pitch all say, from one place.

Every figure names its source. Filing figures are also cited in `tpa/seed/calibration.py` and
`tpa/filings.py`; the industry ones in `docs/benchmark-sources.md`.
"""

FACTS = (
    {"value": "$18.4B", "label": "General Mills net sales, FY2026", "source": "10-K",
     "url": "https://www.sec.gov/Archives/edgar/data/40704/000162828026046466/gis-20260531.htm"},
    {"value": "22%", "label": "of it to Walmart", "source": "10-K",
     "url": "https://www.sec.gov/Archives/edgar/data/40704/000162828026046466/gis-20260531.htm"},
    {"value": "$493M", "label": "accrued trade and coupon promotions, a named critical accounting estimate",
     "source": "10-K", "url": "https://www.sec.gov/Archives/edgar/data/40704/000162828026046466/gis-20260531.htm"},
    {"value": "~20%", "label": "of CPG gross sales goes to trade", "source": "Strategy& / PwC",
     "url": "https://www.strategyand.pwc.com/gx/en/insights/2017/zero-based-trade-for-cpg-leaders/"
            "zero-based-trade-for-cpg-leaders.pdf"},
    {"value": "−13 / +7 pts", "label": "Q4 operating profit growth moved by trade timing, FY2025 / FY2026",
     "source": "earnings releases", "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000040704&type=8-K"},
    {"value": "~$97", "label": "to process one deduction by hand", "source": "CRF benchmark",
     "url": "https://clarkstonconsulting.com/insights/deduction-management/"},
)

STORY = ("The failure that matters is not a bad claim; it is a good document nobody entered. In the simulation, "
         "Walmart and General Mills sign an amendment in February (TP-0214, $3.80 → $4.20 a case). It is filed and "
         "forgotten; six months close short. When it surfaces, someone must re-price closed months, explain the "
         "catch-up, and stop the sales lead who negotiated it from approving it. Real books show the same mechanism "
         "in public: General Mills told investors that trade expense timing cost 3 points of Q4 sales growth in "
         "FY2024 and added 7 points of Q4 profit growth in FY2026.")


def answer() -> str:
    """The Ask box's answer to "what problem does JADE solve?": the facts, then the story."""
    lines = [f"{f['value']}: {f['label']} ({f['source']})." for f in FACTS]
    return "\n".join([STORY.split(". In the simulation")[0] + ".", *lines, STORY])
