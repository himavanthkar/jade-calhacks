"""The answer key has to be exact, so the seeder is tested like the ledger."""

import json
from collections import Counter, defaultdict
from decimal import Decimal

import pytest

from tpa.constants import PLANTED_ERROR_COUNTS, Control
from tpa.seed import fiction as F
from tpa.seed.generate import build
from tpa.seed.load import _jsonable, load

TOLERANCE = Decimal("0.005")


@pytest.fixture(scope="module")
def ds():
    return build(1337, 24)


def dump(d):
    return json.dumps({"tables": d.tables, "key": d.answer_key, "opening": d.opening_journals,
                       "terms": d.program_terms}, default=_jsonable, sort_keys=True)


def by_id(ds, table):
    return {r["id"]: r for r in ds.tables[table]}


def variance(ded, backup):
    base = Decimal(backup["scan_units"]) * backup["scan_rate"]
    return abs(ded["amount"] - base) / base


def test_deterministic(ds):
    assert dump(ds) == dump(build(1337, 24))
    assert dump(ds) != dump(build(1338, 24))


def test_planted_counts(ds):
    planted = ds.answer_key["planted"]
    assert Counter(r["type"] for r in planted) == Counter(PLANTED_ERROR_COUNTS)
    assert len(planted) == 50
    assert len({r["error_id"] for r in planted}) == 50


def test_evidence_resolves(ds):
    known = set(F.PROGRAM_BY_ID) | {F.AMENDMENT.id}
    for table in ("deductions", "returns", "shipments", "scripted_events"):
        known |= set(by_id(ds, table))
    for row in ds.answer_key["planted"] + ds.answer_key["behavioural"]:
        for ev in row["evidence"]:
            assert ev in known or ev.startswith("accrual:"), (row["error_id"] if "error_id" in row else row, ev)


def test_each_deduction_has_one_cause(ds):
    planted = [r for r in ds.answer_key["planted"] if r["type"] != "sales_lead_self_approval"]
    owners = Counter(ev for row in planted for ev in set(row["evidence"]) if ev.startswith("DD-"))
    behavioural = {ev for row in ds.answer_key["behavioural"] for ev in row["evidence"]}
    assert max(owners.values()) == 1
    assert not (set(owners) & behavioural)
    # The Kroger self-approval targets a behavioural no-proof claim, and only that.
    (kr,) = [r for r in ds.answer_key["planted"] if r["type"] == "sales_lead_self_approval" and r["customer_id"] == "KR"]
    assert kr["evidence"][1] in behavioural


def test_no_accidental_duplicates(ds):
    """Legitimate claims never repeat (customer, claimed period, amount); only planted duplicates do."""
    dups = {ev for r in ds.answer_key["planted"] if r["type"] == "duplicate_deduction" for ev in r["evidence"]}
    dups |= {d["subject_id"] for d in ds.tables["historical_decisions"] if "earlier deduction" in d["reason"]}
    groups = defaultdict(list)
    for d in ds.tables["deductions"]:
        groups[(d["customer_id"], d["claimed_period"], d["amount"])].append(d["id"])
    for ids in groups.values():
        if len(ids) > 1:
            assert len(ids) == 2 and set(ids) & dups, ids


def test_variance_plants_straddle_the_tolerance(ds):
    deds = by_id(ds, "deductions")
    backup = {b["deduction_id"]: b for b in ds.tables["claim_backup"]}
    for r in ds.answer_key["planted"]:
        if r["type"] in ("within_tolerance", "transposed_digits"):
            (dd,) = r["evidence"]
            v = variance(deds[dd], backup[dd])
            if r["expected_outcome"] == "pass":
                assert Decimal("0") < v < TOLERANCE, (r["error_id"], v)
            else:
                assert v > TOLERANCE, (r["error_id"], v)


def test_clean_scan_claims_tie_to_backup(ds):
    """Unplanted Walmart claims match their backup to the cent, so every variance is a plant."""
    touched = {ev for r in ds.answer_key["planted"] for ev in r["evidence"]}
    touched |= {d["subject_id"] for d in ds.tables["historical_decisions"]}
    deds = by_id(ds, "deductions")
    for b in ds.tables["claim_backup"]:
        d = deds[b["deduction_id"]]
        if d["customer_id"] == "WMT" and d["id"] not in touched:
            assert abs(d["amount"] - b["scan_units"] * b["scan_rate"]) < Decimal("0.01"), d["id"]


def test_no_backup_plants_have_no_backup(ds):
    has_backup = {b["deduction_id"] for b in ds.tables["claim_backup"]}
    for r in ds.answer_key["planted"]:
        if r["type"] == "scan_back_no_backup":
            assert r["evidence"][0] not in has_backup


def test_moment_recomputes_from_rows(ds):
    m = ds.answer_key["moment"]
    assert [p["period"] for p in m["periods"]] == ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    returned = Counter()
    for r in ds.tables["returns"]:
        returned[r["shipment_id"]] += r["cases"]
    total = Decimal("0")
    for p in m["periods"]:
        net = sum(s["cases"] - returned[s["id"]] for s in ds.tables["shipments"]
                  if s["program_id"] == "TP-0214" and s["period"] == p["period"] and s["ship_date"] >= F.AMENDMENT.effective_date)
        assert net == p["net_cases_from_effective_date"]
        catch_up = (Decimal(net) * Decimal("0.92") * Decimal("0.40")).quantize(Decimal("0.01"))
        assert catch_up == p["catch_up"]
        total += catch_up
    assert total == m["total_catch_up"]


def test_amended_rate_claims_only_after_effective_date(ds):
    for d in ds.tables["deductions"]:
        if d["claimed_rate"] == F.AMENDMENT.new_rate:
            assert d["claim_start"] >= F.AMENDMENT.effective_date
            assert d["available_at"] >= F.AMENDMENT.effective_date


def test_every_mined_control_has_history(ds):
    truth = {c["id"]: c for c in ds.answer_key["controls_truth"]}
    assert set(truth) == set(Control.ALL)
    assert len(truth[Control.CLAIM_VS_BACKUP]["precedent_ids"]) == 24      # 22 accepted, 2 escalated
    assert len(truth[Control.DED_GT_ACCRUAL]["precedent_ids"]) == 7
    assert len(truth[Control.SCAN_NO_BACKUP]["precedent_ids"]) == 3
    assert len(truth[Control.OUTSIDE_WINDOW]["precedent_ids"]) == 1
    assert len(truth[Control.STALE_ACCRUAL]["precedent_ids"]) == 4
    assert [c for c, t in truth.items() if t["learned"]] == [Control.REDEMPTION_DRIFT]


def test_loads_into_schema(conn, ds):
    load(conn, ds, load_terms=True)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM deductions")
        assert cur.fetchone()[0] == len(ds.tables["deductions"])
        cur.execute("SELECT SUM(debit) = SUM(credit) FROM ledger_entries")
        assert cur.fetchone()[0]
        cur.execute("SELECT DISTINCT state FROM periods WHERE period < '2026-01'")
        assert cur.fetchall() == [("CLOSED",)]
        cur.execute("SELECT current_period FROM sim_clock")
        assert cur.fetchone()[0] == "2026-01"
        # Before the amendment lands the terms say $3.80; after, $4.20 from 2026-02-14.
        cur.execute("""SELECT rate FROM program_terms WHERE program_id = 'TP-0214'
                       AND decision_time <= '2026-08-01' AND valid_from <= '2026-03-01'
                       AND (valid_to IS NULL OR valid_to >= '2026-03-01')""")
        assert cur.fetchall() == [(Decimal("3.800000"),)]
        cur.execute("""SELECT rate FROM program_terms WHERE program_id = 'TP-0214'
                       AND decision_time <= '2026-08-31' AND valid_from <= '2026-03-01'
                       AND (valid_to IS NULL OR valid_to >= '2026-03-01')
                       ORDER BY decision_time DESC, valid_from DESC LIMIT 1""")
        assert cur.fetchone()[0] == Decimal("4.200000")


def test_the_seed_is_byte_for_byte_reproducible():
    """Everyone on seed 1337 holds the same data. If this changes, the fiction changed: say so in the
    commit and tell the team to re-seed, because the answer key and the demo numbers move with it."""
    from tpa.seed.load import fingerprint
    assert fingerprint(build(1337, 24)) == "72a7f2811d410a9d"
