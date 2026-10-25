"""Pull General Mills' 10-Ks from SEC EDGAR and extract the figures the simulation is calibrated to.

    uv run python scripts/pull_10k.py [--years 7]

`--years` 10-Ks, newest first (default 7: fiscal 2020-2026, the backtest's history), plus every
quarter's net sales from XBRL as first filed. Needs SEC_USER_AGENT (your name and email: SEC policy for automated access) in the environment
or .env. Writes the filings and data/edgar/extracted.json — every figure with the sentence it was
read from — into data/ (git-ignored). Free, no key; stays well under SEC's 10 requests a second.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "edgar"
CIK = "0000040704"                 # General Mills, Inc.


def user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT")
    env = ROOT / ".env"
    if not ua and env.exists():
        m = re.search(r'^SEC_USER_AGENT=["\']?([^"\'\n]+)', env.read_text(), re.M)
        ua = m and m.group(1)
    if not ua:
        sys.exit("Set SEC_USER_AGENT to your name and email (SEC requires a contact for automated access).")
    return ua


def get(url: str, ua: str) -> bytes:
    time.sleep(0.2)
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua})) as r:
        return r.read()


def text_of(html: bytes) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html.decode("utf-8", "ignore"))))


def quote(t: str, m: re.Match, before: int = 0, after: int = 0) -> str:
    return t[max(0, m.start() - before): m.end() + after].strip()


def extract(t: str) -> dict:
    """Each figure with the sentence it comes from. A pattern that stops matching fails loudly."""
    found = {}

    m = re.search(r"During fiscal (\d{4}) ?, Walmart Inc\. and its affiliates \(Walmart\) accounted for (\d+) percent of "
                  r"our consolidated net sales and (\d+) percent of net sales of our North America Retail segment\.", t)
    found["walmart_share_of_net_sales_pct"] = {"value": int(m.group(2)), "quote": quote(t, m)}
    found["walmart_share_of_na_retail_pct"] = {"value": int(m.group(3)), "quote": quote(t, m)}

    m = re.search(r"Our accrued trade and coupon promotion liabilities were \$(\d+) million as of ([A-Z][a-z]+ \d+, \d{4}) ?, "
                  r"and \$(\d+) million as of ([A-Z][a-z]+ \d+, \d{4}) ?\.", t)
    found["accrued_trade_and_coupon_liabilities_musd"] = {"value": int(m.group(1)), "as_of": m.group(2),
                                                         "prior": int(m.group(3)), "prior_as_of": m.group(4),
                                                         "quote": quote(t, m)}

    m = re.search(r"Trade promotions are recorded using significant judgment of estimated participation and performance "
                  r"levels for offered programs at the time of sale\. Differences between the estimated and actual "
                  r"reduction to the transaction price (?:are|is) recognized as a change in estimate in a subsequent period\.", t)
    found["trade_promotion_policy"] = {"quote": quote(t, m)}

    m = re.search(r"Net Sales North America Retail \$ ([\d,]+\.\d) (\d+) % \$ ([\d,]+\.\d) (\d+) % .*? Total \$ ([\d,]+\.\d) "
                  r"100 % \$ ([\d,]+\.\d) 100 %", t)
    found["na_retail_net_sales_musd"] = {"value": float(m.group(1).replace(",", "")),
                                         "prior": float(m.group(3).replace(",", "")), "quote": quote(t, m)}
    found["segment_net_sales_total_musd"] = {"value": float(m.group(5).replace(",", "")),
                                             "prior": float(m.group(6).replace(",", "")), "quote": quote(t, m)}
    return found


def quarters(revenue: list[dict]) -> list[dict]:
    """Each fiscal quarter's net sales as first filed: the value and the day it became public.
    A quarter is a duration of 80-100 days (General Mills' fourth quarter runs 13 or 14 weeks)."""
    first = {}
    for r in revenue:
        if "start" not in r or not 80 <= (date.fromisoformat(r["end"]) - date.fromisoformat(r["start"])).days <= 100:
            continue
        key = (r["start"], r["end"])
        if key not in first or r["filed"] < first[key]["filed"]:
            first[key] = r
    return [{"start": r["start"], "end": r["end"], "net_sales_usd": r["val"], "form": r["form"],
             "accession": r["accn"], "filed": r["filed"]} for _, r in sorted(first.items())]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=7, help="how many 10-Ks to read, newest first")
    args = ap.parse_args()
    ua = user_agent()
    OUT.mkdir(parents=True, exist_ok=True)
    subs = json.loads(get(f"https://data.sec.gov/submissions/CIK{CIK}.json", ua))
    recent = subs["filings"]["recent"]
    tenks = [(a, d, doc) for f, a, d, doc in zip(recent["form"], recent["accessionNumber"], recent["filingDate"],
                                                  recent["primaryDocument"]) if f == "10-K"][:args.years]
    facts = json.loads(get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json", ua))
    revenue = facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]["units"]["USD"]

    out = {"cik": CIK, "company": subs["name"], "fiscal_year_end": subs["fiscalYearEnd"], "filings": [],
           "quarters": quarters(revenue)}
    for accession, filed, doc in tenks:
        url = f"https://www.sec.gov/Archives/edgar/data/{int(CIK)}/{accession.replace('-', '')}/{doc}"
        cached = OUT / doc
        html = cached.read_bytes() if cached.exists() else get(url, ua)
        cached.write_bytes(html)
        annual = [r for r in revenue if r["accn"] == accession and r.get("fp") == "FY" and r["form"] == "10-K"]
        fy = max(annual, key=lambda r: r["end"])
        out["filings"].append({"accession": accession, "filed": filed, "url": url, "fiscal_year_end": fy["end"],
                               "net_sales_usd": fy["val"], "net_sales_source": "XBRL us-gaap:"
                               "RevenueFromContractWithCustomerExcludingAssessedTax", **extract(text_of(html))})
        print(f"{doc}: fiscal year to {fy['end']}, net sales ${fy['val'] / 1e9:.2f}B")
    (OUT / "extracted.json").write_text(json.dumps(out, indent=1))
    print(OUT / "extracted.json")


if __name__ == "__main__":
    main()
