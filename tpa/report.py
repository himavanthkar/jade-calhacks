"""The close report: the sign-off package as one printable page (Print → Save as PDF, or
`scripts/close_report.py` for a PDF). It prints what the package holds and computes nothing new:
the flux commentary with its journal lines, the analytical review against the 10-K, each decision and
who made it, the reconciliation identity per program, the verifiability gates and the sign-offs.
"""

from decimal import Decimal
from html import escape

from tpa.constants import CUSTOMERS

NAMES = {"WMT": "Walmart", "COST": "Costco", "KR": "Kroger"}
CSS = """
body{font:12px/1.5 -apple-system,Helvetica,Arial,sans-serif;color:#292623;margin:0;background:#fff}
main{max-width:920px;margin:0 auto;padding:36px 32px 60px}
header{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #5b241d;padding-bottom:12px}
.mark{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:7px;background:#E86F31;color:#fff;font:700 18px Georgia,serif;margin-right:10px;vertical-align:middle}
h1{font:700 24px Georgia,serif;color:#5b241d;margin:0;display:inline;vertical-align:middle}
h2{font:700 15px Georgia,serif;color:#5b241d;margin:26px 0 8px;border-bottom:1px solid #ecdfd0;padding-bottom:4px}
.meta{font-size:11px;color:#6f6c64;text-align:right}
table{width:100%;border-collapse:collapse;font-size:11px;margin:6px 0}
th{text-align:left;color:#6f6c64;font-weight:600;border-bottom:1px solid #dcd5ca;padding:4px 8px 4px 0}
td{border-bottom:1px solid #f0ebe3;padding:5px 8px 5px 0;vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ids{font:10px ui-monospace,Menlo,monospace;color:#6f6c64}
.box{border:1px solid #ecdfd0;border-left:3px solid #E86F31;border-radius:6px;padding:10px 12px;background:#fdfbf8}
.ok{color:#21654a;font-weight:600}.bad{color:#9b3b22;font-weight:600}
footer{margin-top:30px;border-top:1px solid #ecdfd0;padding-top:8px;font-size:10px;color:#6f6c64}
@media print{main{padding:0}a{color:inherit}}
"""


def _m(v) -> str:
    return "—" if v is None else f"${Decimal(str(v)):,.2f}"


def _pct(v) -> str:
    return "—" if v is None else f"{Decimal(str(v)) * 100:.2f}%"


def html(pkg: dict) -> str:
    period = pkg["period"]
    customers = {c["customer_id"]: c for c in pkg["customers"]}
    signed = [c for c in pkg["customers"] if c["signed_by"]]
    status = (f"Signed for {len(signed)} of {len(customers)} customers" if signed else "Unsigned: prepared for review")
    rows = []
    rows.append(f"""<header><div><span class="mark">J</span><h1>Trade promotion close · {escape(period)}</h1>
      <div style="margin-top:6px;color:#6f6c64">General Mills (simulation) · US retail · prepared by JADE</div></div>
      <div class="meta">{'Books as they stand' if str(pkg['as_of']).startswith('9999') else 'As of ' + escape(str(pkg['as_of'])[:16])}<br><b>{status}</b></div></header>""")

    rows.append("<h2>Flux: what moved and why</h2>")
    if pkg["flux"]:
        for f in pkg["flux"]:
            rows.append(f"""<div class="box" style="margin-bottom:8px"><b>{escape(f['account'])}</b>:
              {_m(f['prior_balance'])} → {_m(f['current_balance'])} ({'—' if f['pct_change'] is None else f"{Decimal(str(f['pct_change'])):+.1f}%"})<br>{escape(f['narrative'])}
              <div class="ids">Journal lines: {escape(', '.join(f['driver_entry_ids'][:24]))}{' …' if len(f['driver_entry_ids']) > 24 else ''}</div></div>""")
    else:
        rows.append("<p>No account moved past materiality.</p>")

    r = pkg.get("analytical_review")
    if r:
        verdict = ('<span class="ok">Within range</span>' if r["within_range"]
                   else '<span class="bad">Outside range: reviewer explains before signing</span>')
        src = r.get("source") or {}
        rows.append(f"""<h2>Analytical review against the 10-K</h2><div class="box">Accrued trade promotion liability
          {_m(r['liability'])} is {_pct(r['ratio'])} of annualized net sales ({_m(r['net_sales_annualized'])}).
          General Mills reports {_pct(r['expectation'])}{f" (FY{src.get('fiscal_year')} 10-K, filed {src.get('filed')})" if src else ''};
          review range {_pct(r['low'])}–{_pct(r['high'])}. {verdict}.</div>""")

    rows.append("<h2>Decisions</h2><table><tr><th>Customer</th><th>Finding</th><th>Control</th><th class='n'>Amount</th><th>Decided</th><th>By</th><th>Precedent</th></tr>")
    any_decision = False
    for cid in CUSTOMERS:
        for f in customers[cid]["findings"]:
            if not f.get("escalation_id") and f["state"] != "auto_resolved":
                continue
            any_decision = True
            by = f.get("answered_by") or ("JADE (agreement or precedent)" if f["state"] == "auto_resolved" else "open")
            decided = ((f["evidence"].get("resolution", {}) or {}).get("decision") or f.get("answer") or f["state"]).replace("_", " ")
            rows.append(f"<tr><td>{NAMES[cid]}</td><td class='ids'>{escape(f['id'])}</td><td>{escape(f['control_id'].replace('CTL-', '').replace('-', ' ').lower())}</td>"
                        f"<td class='n'>{_m(f['amount'])}</td><td>{escape(str(decided))}</td><td>{escape(by)}</td>"
                        f"<td class='ids'>{escape(f.get('became_precedent_id') or '')}</td></tr>")
    if not any_decision:
        rows.append("<tr><td colspan=7>No decisions this period.</td></tr>")
    rows.append("</table>")

    rows.append("<h2>Reconciliation: ending = opening + accruals + adjustments − settled</h2><table><tr><th>Customer</th><th>Program</th>"
                "<th class='n'>Opening</th><th class='n'>Accruals</th><th class='n'>Adjustments</th><th class='n'>Settled</th><th class='n'>Ending</th></tr>")
    for cid in CUSTOMERS:
        for x in customers[cid]["reconciliation"]:
            rows.append(f"<tr><td>{NAMES[cid]}</td><td class='ids'>{escape(x['program_id'])}</td><td class='n'>{_m(x['opening'])}</td>"
                        f"<td class='n'>{_m(x['accruals'])}</td><td class='n'>{_m(x['estimate_adjustments'])}</td>"
                        f"<td class='n'>{_m(x['settled'])}</td><td class='n'><b>{_m(x['ending'])}</b></td></tr>")
    rows.append("</table>")

    rows.append("<h2>Verifiability gates and sign-off</h2><table><tr><th>Customer</th><th>Gates</th><th>Debits = credits</th><th>Signed</th></tr>")
    for cid in CUSTOMERS:
        c = customers[cid]
        passed = sum(1 for g in c["gates"].values() if g["passed"])
        balanced = Decimal(str(c["totals"]["debit"])) == Decimal(str(c["totals"]["credit"]))
        rows.append(f"<tr><td>{NAMES[cid]}</td><td class='{'ok' if passed == len(c['gates']) else 'bad'}'>{passed} of {len(c['gates'])} passed</td>"
                    f"<td class='{'ok' if balanced else 'bad'}'>{_m(c['totals']['debit'])} = {_m(c['totals']['credit'])}</td>"
                    f"<td>{escape(c['signed_by'] or 'not yet')}{' · ' + escape(str(c['signed_at'])[:10]) if c['signed_at'] else ''}</td></tr>")
    rows.append("</table>")
    rows.append("<footer>Every amount is a sum of named journal lines in an insert-only ledger. Trade promotion is "
                "contra-revenue (ASC 606). Thresholds are company policy, not GAAP. Simulated transactions; real "
                "10-K figures.</footer>")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><title>JADE close {escape(period)}</title>"
            f"<style>{CSS}</style></head><body><main>{''.join(rows)}</main></body></html>")
