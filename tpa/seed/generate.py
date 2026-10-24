"""Deterministic generator: explicit rules over one seeded RNG. No model, no faker.

Rows are plain dicts. Fields that point at other generated rows hold the row
itself until `finalize` assigns ids, so ids can be numbered in date order after
planting has added, merged and deleted rows. Keys starting with '_' are
generator bookkeeping and never reach the database.
"""

import itertools
import random
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from tpa.constants import (
    HISTORY_MONTHS, Account, add_months, month_for_period, period_end, period_for_month,
    period_of, period_start,
)
from tpa.seed import fiction as F

CENT = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def dec(x: float, places: int = 6) -> Decimal:
    return Decimal(str(round(x, places)))


def at(d: date, hour: int = 9, minute: int = 0) -> datetime:
    return datetime.combine(d, time(hour, minute))


def days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def retail_segments(period: str) -> list[tuple[date, date]]:
    """Walmart retail weeks (Saturday–Friday), split at the month boundaries."""
    segs, start = [], period_start(period)
    for d in days(start, period_end(period)):
        if d.weekday() == 4 or d == period_end(period):   # Friday closes a retail week
            segs.append((start, d))
            start = d + timedelta(days=1)
    return segs


class SeedError(RuntimeError):
    pass


@dataclass
class Dataset:
    seed: int
    months: int
    tables: dict[str, list[dict]]
    opening_journals: list[dict]
    periods: list[dict]
    sim_clock: dict
    program_terms: list[dict]
    answer_key: dict


# Tables whose ids are assigned at finalize: prefix, width, sort key.
ID_SPEC = {
    "shipments": ("SH", 5, lambda r: (r["ship_date"], F.CUSTOMER_ORDER[r["customer_id"]], r["_seq"])),
    "returns": ("RT", 4, lambda r: (r["available_at"], r["_seq"])),
    "invoices": ("INV", 5, lambda r: (r["invoice_date"], F.CUSTOMER_ORDER[r["customer_id"]], r["_seq"])),
    "deductions": ("DD", 4, lambda r: (r["available_at"], F.CUSTOMER_ORDER[r["customer_id"]],
                                       r["claim_start"] or r["taken_date"], r["_seq"])),
    "claim_backup": ("CB", 4, lambda r: (r["available_at"], r["_seq"])),
    "disputes": ("DS", 4, lambda r: (r["raised_date"], r["_seq"])),
    "historical_decisions": ("HD", 4, lambda r: (r["decided_at"], r["_seq"])),
    "scripted_events": ("EV", 2, lambda r: (r["sim_date"], r["_seq"])),
}


class Builder:
    def __init__(self, seed: int, months: int):
        if months < 13:
            raise SeedError("need at least 13 months: 12 of history and one live")
        self.seed = seed
        self.months = months
        self.rng = random.Random(seed)
        self.end = period_end(period_for_month(months))
        self.tables: dict[str, list[dict]] = defaultdict(list)
        self._seq = itertools.count()
        self._invoices: dict[str, list[dict]] = defaultdict(list)
        self.returns_by_shipment: dict[int, list[dict]] = defaultdict(list)
        self.planted: list[dict] = []
        self.behavioural: list[dict] = []
        self.moment: dict = {}

    # ── helpers ─────────────────────────────────────────────────────────────
    def add(self, table: str, **row) -> dict:
        row["_seq"] = next(self._seq)
        self.tables[table].append(row)
        return row

    def rows(self, table: str) -> list[dict]:
        return [r for r in self.tables[table] if not r.get("_deleted")]

    def in_range(self, d: date) -> bool:
        return d <= self.end

    def is_history(self, d: date) -> bool:
        return month_for_period(period_of(d)) in HISTORY_MONTHS

    def invoice_before(self, customer_id: str, on: date) -> dict | None:
        invs = self._invoices[customer_id]
        i = bisect_right([v["invoice_date"] for v in invs], on)
        return invs[i - 1] if i else None

    def net_cases(self, shipment: dict) -> int:
        return shipment["cases"] - sum(r["cases"] for r in self.returns_by_shipment[shipment["_seq"]])

    def add_return(self, shipment: dict, cases: int, return_date: date, available_at: date) -> dict:
        r = self.add("returns", shipment_id=shipment, customer_id=shipment["customer_id"],
                     cases=cases, return_date=return_date, available_at=available_at)
        self.returns_by_shipment[shipment["_seq"]].append(r)
        return r

    # ── reference data ──────────────────────────────────────────────────────
    def reference(self) -> None:
        for cid, name, channel in F.CUSTOMERS:
            self.add("customers", id=cid, name=name, channel=channel)
        for aid, name, role, cid in F.ACTORS:
            self.add("actors", id=aid, name=name, role=role, customer_id=cid)
        for p in F.PROGRAMS:
            self.add("trade_programs", id=p.id, customer_id=p.customer_id,
                     document_text=F.program_document(p), program_type=p.program_type,
                     signed_date=p.signed_date, negotiated_by=p.negotiated_by, available_at=p.signed_date)
        a = F.AMENDMENT
        self.add("program_amendments", id=a.id, program_id=a.program_id,
                 document_text=F.amendment_document(a), effective_date=a.effective_date,
                 signed_date=a.signed_date, available_at=a.available_at)

    # ── shipments, invoices, ordinary returns ───────────────────────────────
    def shipments(self) -> None:
        for m in range(1, self.months + 1):
            period = period_for_month(m)
            year = period_start(period).year
            for cid, _, _ in F.CUSTOMERS:
                ship_days = [d for d in days(period_start(period), period_end(period))
                             if d.weekday() in F.SHIP_WEEKDAYS[cid]]
                per_day = F.MONTHLY_CASES[(cid, year)] / len(ship_days)
                price = F.CASE_PRICE[(cid, year)]
                for d in ship_days:
                    cases = int(round(per_day * self.rng.uniform(0.92, 1.08)))
                    program = (F.program_for(cid, "scan_back", d) or F.program_for(cid, "off_invoice", d))
                    sh = self.add("shipments", customer_id=cid, program_id=program.id if program else None,
                                  period=period, cases=cases, gross_price=price, ship_date=d, available_at=d)
                    off_invoice = (money(cases * program.rate)
                                   if program and program.program_type == "off_invoice" else money(0))
                    inv = self.add("invoices", customer_id=cid, shipment_id=sh, period=period,
                                   gross_amount=money(cases * price), off_invoice_amount=off_invoice,
                                   invoice_date=d, available_at=d)
                    self._invoices[cid].append(inv)
                    if self.rng.random() < 0.08:   # ordinary returns land inside the same period
                        rd = min(d + timedelta(days=self.rng.randint(2, 9)), period_end(period))
                        self.add_return(sh, max(1, round(cases * self.rng.uniform(0.002, 0.01))), rd, rd)

    # ── Walmart scan-back claims ────────────────────────────────────────────
    def actual_redemption(self, m: int) -> Decimal:
        if m in HISTORY_MONTHS:
            p = F.PROGRAM_BY_ID["TP-0114"]
            return dec(float(p.projected_redemption) + self.rng.gauss(0, F.REDEMPTION_2025_NOISE))
        p = F.PROGRAM_BY_ID["TP-0214"]
        drift = F.REDEMPTION_2026_DRIFT_PER_MONTH * (m - 13)
        return dec(float(p.projected_redemption) + drift + self.rng.gauss(0, F.REDEMPTION_2026_NOISE))

    def walmart_claims(self) -> None:
        for m in range(1, self.months + 1):
            period = period_for_month(m)
            taken_period = add_months(period, F.WALMART_CLAIM_LAG_MONTHS)
            redemption = self.actual_redemption(m)   # drawn every month so the RNG stream is stable
            if month_for_period(taken_period) > self.months:
                continue
            program = F.program_for("WMT", "scan_back", period_start(period))
            shipped = [s for s in self.tables["shipments"] if s["customer_id"] == "WMT" and s["period"] == period]
            sold = Decimal(sum(self.net_cases(s) for s in shipped)) * redemption
            segs = retail_segments(period)
            dim = (period_end(period) - period_start(period)).days + 1
            ty, tm = (int(x) for x in taken_period.split("-"))
            for k, (stream, share) in enumerate(F.WALMART_STREAMS):
                stream_units = int(round(sold * share))
                # Weeks sell unevenly; equal weeks with equal units would look like duplicates.
                weights = [((e - s).days + 1) / dim * self.rng.uniform(0.9, 1.1) for s, e in segs]
                total_w = sum(weights)
                allocated = 0
                for i, (s, e) in enumerate(segs):
                    if i == len(segs) - 1:
                        units = stream_units - allocated
                    else:
                        units = int(round(stream_units * weights[i] / total_w))
                    allocated += units
                    rate = F.true_rate(program, s)
                    taken = date(ty, tm, 2 + 4 * i + 2 * k)
                    ded = self.add(
                        "deductions", invoice_id=self.invoice_before("WMT", taken), customer_id="WMT",
                        program_id=program.id if self.rng.random() < F.WALMART_PROGRAM_CITED else None,
                        amount=money(units * rate), reason_code=stream, claimed_rate=rate,
                        taken_date=taken, claimed_period=period, claim_start=s, claim_end=e,
                        cleared_by=None, approved_by=None, available_at=taken,
                        _kind="wmt_scan", _program=program, _units=units)
                    ded["_backup"] = self.add(
                        "claim_backup", deduction_id=ded, scan_units=units, scan_rate=rate,
                        proof_of_performance=False, notes=None, received_date=taken, available_at=taken)

    # ── Kroger display claims ───────────────────────────────────────────────
    def kroger_claims(self) -> None:
        for m in range(1, self.months + 1):
            period = period_for_month(m)
            taken_period = add_months(period, F.KROGER_CLAIM_LAG_MONTHS)
            day = self.rng.randint(10, 18)
            cited = self.rng.random() < 0.7
            if month_for_period(taken_period) > self.months:
                continue
            program = F.program_for("KR", "display", period_start(period))
            ty, tm = (int(x) for x in taken_period.split("-"))
            taken = date(ty, tm, day)
            start = period_start(period)
            ded = self.add(
                "deductions", invoice_id=self.invoice_before("KR", taken), customer_id="KR",
                program_id=program.id if cited else None, amount=money(program.rate),
                reason_code="DISPLAY", claimed_rate=None, taken_date=taken, claimed_period=period,
                claim_start=start + timedelta(days=7), claim_end=start + timedelta(days=20),
                cleared_by=None, approved_by=None, available_at=taken, _kind="kr_display", _program=program)
            ded["_backup"] = self.add(
                "claim_backup", deduction_id=ded, scan_units=None, scan_rate=None,
                proof_of_performance=True, notes=None, received_date=taken, available_at=taken)

    # ── Costco MDF instalments ──────────────────────────────────────────────
    def costco_mdf(self) -> None:
        for m in range(1, self.months + 1):
            period = period_for_month(m)
            program = F.program_for("COST", "mdf", period_start(period))
            y, mo = (int(x) for x in period.split("-"))
            taken = date(y, mo, F.COSTCO_MDF_DAY)
            self.add(
                "deductions", invoice_id=self.invoice_before("COST", taken), customer_id="COST",
                program_id=program.id, amount=money(program.rate / 12), reason_code="MDF",
                claimed_rate=None, taken_date=taken, claimed_period=period,
                claim_start=period_start(period), claim_end=period_end(period),
                cleared_by=None, approved_by=None, available_at=taken, _kind="cost_mdf", _program=program)

    # ── the moment ──────────────────────────────────────────────────────────
    def compute_moment(self) -> None:
        a = F.AMENDMENT
        program = F.PROGRAM_BY_ID[a.program_id]
        delta = a.new_rate - program.rate
        restated = [period_for_month(m) for m in range(month_for_period(period_of(a.effective_date)),
                                                       month_for_period(period_of(a.available_at)))]
        by_period = []
        for period in restated:
            eligible = [s for s in self.tables["shipments"]
                        if s["program_id"] == program.id and s["period"] == period
                        and s["ship_date"] >= a.effective_date]
            net = sum(self.net_cases(s) for s in eligible)
            by_period.append({
                "period": period,
                "net_cases_from_effective_date": net,
                "catch_up": money(Decimal(net) * program.projected_redemption * delta),
            })
        self.moment = {
            "program_id": program.id,
            "amendment_id": a.id,
            "rate_as_signed": program.rate,
            "rate_amended": a.new_rate,
            "effective_date": a.effective_date,
            "entered_on": a.available_at,
            "projected_redemption": program.projected_redemption,
            "formula": "per period: round(net shipped cases on or after effective_date "
                       "× projected_redemption × (amended rate − signed rate), 2)",
            "periods": by_period,
            "total_catch_up": sum((p["catch_up"] for p in by_period), Decimal("0")),
        }

    # ── opening balances, periods, clock, terms ─────────────────────────────
    def opening_journals(self) -> list[dict]:
        """Liability the prior-year team carried into 2026: shipped, accrued, not yet claimed."""
        cutoff = period_end(period_for_month(12))
        journals = []
        outstanding = defaultdict(list)   # program → [(origin period, amount)]
        claimed = {(d["_program"].id, d["claimed_period"]) for d in self.rows("deductions")
                   if d.get("_program") and d["available_at"] <= cutoff}
        for m in HISTORY_MONTHS:
            period = period_for_month(m)
            wmt = F.program_for("WMT", "scan_back", period_start(period))
            if (wmt.id, period) not in claimed:
                net = sum(self.net_cases(s) for s in self.tables["shipments"]
                          if s["program_id"] == wmt.id and s["period"] == period)
                outstanding[wmt.id].append((period, money(net * wmt.projected_redemption * wmt.rate)))
            kr = F.program_for("KR", "display", period_start(period))
            if (kr.id, period) not in claimed and m > 12 - F.KROGER_CLAIM_LAG_MONTHS:
                outstanding[kr.id].append((period, money(kr.rate)))
        for program_id, items in outstanding.items():
            p = F.PROGRAM_BY_ID[program_id]
            total = sum((amt for _, amt in items), Decimal("0"))
            journals.append({
                "customer_id": p.customer_id, "program_id": program_id,
                "period": period_for_month(12), "decision_time": at(cutoff, 23),
                "lines": [(Account.TRADE_PROMO_EXPENSE, total, Decimal("0"), f"Opening accrual {program_id}", cutoff)]
                         + [(Account.ACCRUED_TRADE_PROMO, Decimal("0"), amt,
                             f"Opening accrued liability {program_id}, shipments {origin}", period_end(origin))
                            for origin, amt in items],
            })
        return journals

    def periods(self) -> list[dict]:
        out = []
        for m in range(1, self.months + 1):
            period = period_for_month(m)
            closed = m in HISTORY_MONTHS
            for cid, _, _ in F.CUSTOMERS:
                out.append({
                    "period": period, "customer_id": cid, "state": "CLOSED" if closed else "OPEN",
                    "signed_by": "controller" if closed else None,
                    "signed_at": at(period_end(period) + timedelta(days=5), 17) if closed else None,
                })
        return out

    def program_terms(self) -> list[dict]:
        """Ground-truth extraction of every program. The extractor is scored against this;
        `seed.py --load-terms` loads it directly as a fallback."""
        clause = {"scan_back": "4.2", "off_invoice": "2.1", "mdf": "2.1", "display": "3.1"}
        rows, n = [], itertools.count(1)

        def term(p, rate, valid_from, valid_to, decided, amendment_id=None, clause_no=None):
            rows.append({
                "id": f"PT-{next(n):04d}", "program_id": p.id, "customer_id": p.customer_id,
                "program_type": p.program_type, "rate": rate, "rate_unit": p.rate_unit,
                "base_definition": p.base_definition, "projected_redemption": p.projected_redemption,
                "window_start": p.window_start, "window_end": p.window_end,
                "requires_proof": p.requires_proof,
                "source_clause_id": f"{amendment_id or p.id}#{clause_no or clause[p.program_type]}",
                "amendment_id": amendment_id, "valid_from": valid_from, "valid_to": valid_to,
                "decision_time": decided,
            })

        a = F.AMENDMENT
        for p in F.PROGRAMS:
            term(p, p.rate, p.window_start, None, at(p.signed_date))
            if p.id == a.program_id:
                learned = at(a.available_at)
                term(p, p.rate, p.window_start, a.effective_date - timedelta(days=1), learned)
                term(p, a.new_rate, a.effective_date, None, learned, a.id, "4.2")
        return rows

    # ── finalize ────────────────────────────────────────────────────────────
    def finalize(self) -> Dataset:
        for table, (prefix, width, key) in ID_SPEC.items():
            live = sorted(self.rows(table), key=key)
            for i, row in enumerate(live, 1):
                row["id"] = f"{prefix}-{i:0{width}d}"

        def resolve(v):
            if isinstance(v, dict) and "_seq" in v:
                if v.get("_deleted"):
                    raise SeedError(f"reference to deleted row {v.get('id')}")
                return v["id"]
            if isinstance(v, list):
                return [resolve(x) for x in v]
            return v

        tables = {}
        for table, rows in self.tables.items():
            clean = [{k: resolve(v) for k, v in r.items() if not k.startswith("_")} for r in rows if not r.get("_deleted")]
            cols = list(dict.fromkeys(k for r in clean for k in r))
            tables[table] = [{c: r.get(c) for c in cols} for r in clean]

        answer_key = {
            "seed": self.seed,
            "months": self.months,
            "moment": self.moment,
            "planted": [{k: resolve(v) for k, v in row.items()} for row in self.planted],
            "behavioural": [{k: resolve(v) for k, v in row.items()} for row in self.behavioural],
            "controls_truth": self.controls_truth(),
        }
        return Dataset(self.seed, self.months, tables, self.opening_journals(), self.periods(),
                       {"current_period": period_for_month(13), "sim_date": period_end(period_for_month(12))},
                       self.program_terms(), answer_key)

    def controls_truth(self) -> list[dict]:
        from tpa.seed.plant import CONTROL_SPEC
        precedents = defaultdict(list)
        for d in self.rows("historical_decisions"):
            precedents[d["_control"]].append(d["id"])
        return [{"id": cid, **spec, "precedent_ids": precedents.get(cid, []),
                 "learned": not precedents.get(cid)} for cid, spec in CONTROL_SPEC.items()]


def build(seed: int = 1337, months: int = 24) -> Dataset:
    from tpa.seed import plant

    b = Builder(seed, months)
    b.reference()
    b.shipments()
    plant.late_returns(b)        # before claims: Walmart's sell-through is net of returns
    b.walmart_claims()
    b.kroger_claims()
    b.costco_mdf()
    plant.history(b)
    plant.live(b)
    b.compute_moment()
    plant.moment(b)
    return b.finalize()
