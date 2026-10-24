"""The evaluator against a seeded database and a simulated, perfect finder."""

import json
from datetime import datetime

import pytest

from tpa.constants import Control
from tpa.evaluate import ids_in, metrics, resolve_period
from tpa.seed.generate import build
from tpa.seed.load import _jsonable, load


@pytest.fixture(scope="module")
def key_and_ds():
    ds = build(1337, 24)
    # The evaluator reads the key from disk, so round-trip it through JSON.
    return json.loads(json.dumps(ds.answer_key, default=_jsonable)), ds


@pytest.fixture
def seeded(conn, key_and_ds):
    key, ds = key_and_ds
    load(conn, ds)
    with conn.cursor() as cur:
        for c in key["controls_truth"]:
            cur.execute(
                """INSERT INTO controls (id, name, condition, threshold, threshold_unit, owner_role, precedent_ids,
                                         mined_at, learned) VALUES (%s, %s, 'true', %s, %s, %s, %s, %s, %s)""",
                (c["id"], c["name"], c["threshold"], c["threshold_unit"], c["owner_role"], c["precedent_ids"],
                 datetime(2025, 12, 31), c["learned"]),
            )
    conn.commit()
    return conn, key


def add_finding(cur, fid, row, *, escalation_type=None, escalate=False):
    cur.execute(
        """INSERT INTO findings (id, period, customer_id, control_id, severity, state, escalation_type, evidence, created_at)
           VALUES (%s, %s, %s, %s, 'medium', 'open', %s, %s, %s)""",
        (fid, row["period"], row["customer_id"], row.get("expected_control_id") or Control.RATE_CONFLICT,
         escalation_type, json.dumps({"rows": row["evidence"]}), datetime(2026, 1, 1)),
    )
    if escalate:
        cur.execute("INSERT INTO escalations (id, finding_id, to_role, question, created_at) VALUES (%s, %s, 'controller', '?', %s)",
                    (f"ESC-{fid}", fid, datetime(2026, 1, 1)))


def perfect_finder(cur, key):
    for i, row in enumerate(key["planted"]):
        if row["expected_outcome"] == "pass":
            continue
        if row["expected_outcome"] == "gate_fail":
            accrual = next(e for e in row["evidence"] if e.startswith("accrual:"))
            cur.execute("""UPDATE periods SET gate_results = %s WHERE period = %s AND customer_id = %s""",
                        (json.dumps({"no_stale_accruals": {"passed": False, "violations": [{"key": accrual}]}}),
                         row["period"], row["customer_id"]))
            continue
        add_finding(cur, f"FN-{i}", row, escalation_type="sod" if row["expected_outcome"] == "throw" else None)
    for i, row in enumerate(key["behavioural"]):
        add_finding(cur, f"FN-B{i}", row)


def test_perfect_finder_scores_perfectly(seeded):
    conn, key = seeded
    with conn.cursor() as cur:
        perfect_finder(cur, key)
        m = metrics(cur, key, "month-12")
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["counts"]["planted_errors"] == 50 - 8                     # 6 within tolerance + 2 transpositions below it
    assert m["missed"] == [] and m["false_positives"] == []


def test_flagging_a_true_negative_costs_precision(seeded):
    conn, key = seeded
    negative = next(r for r in key["planted"] if r["type"] == "within_tolerance")
    with conn.cursor() as cur:
        perfect_finder(cur, key)
        add_finding(cur, "FN-FP", negative)
        m = metrics(cur, key, "month-12")
    assert m["precision"] < 1.0
    assert m["false_positives"] == [{"finding_id": "FN-FP", "period": negative["period"],
                                     "control_id": Control.RATE_CONFLICT, "matched_negative": [negative["error_id"]]}]


def test_a_finding_on_the_target_does_not_count_as_the_sod_block(seeded):
    conn, key = seeded
    kr = next(r for r in key["planted"] if r["type"] == "sales_lead_self_approval" and r["customer_id"] == "KR")
    with conn.cursor() as cur:
        add_finding(cur, "FN-1", kr)                                   # no escalation_type 'sod'
        m = metrics(cur, key, "month-12")
    assert kr["error_id"] in {x["error_id"] for x in m["missed"]}


def test_window_and_escalation_rate(seeded):
    conn, key = seeded
    early = [r for r in key["planted"] if r["period"] <= "2026-01" and r["expected_outcome"] not in ("pass", "gate_fail")]
    with conn.cursor() as cur:
        for i, row in enumerate(early):
            add_finding(cur, f"FN-{i}", row, escalate=(i == 0))
        m = metrics(cur, key, "month-1")
    assert m["as_of"] == "2026-01"
    assert m["counts"]["planted_errors"] == len([r for r in key["planted"]
                                                 if r["period"] <= "2026-01" and r["expected_outcome"] != "pass"])
    assert m["escalation_rate"] == round(1 / len(early), 4)
    assert m["autonomy"] == 0.0                                        # nothing signed yet


def test_helpers():
    assert ids_in({"a": ["DD-1", {"b": "RT-2"}], "n": 3}) == {"DD-1", "RT-2"}
    assert resolve_period("month-9") == "2026-09"
    assert resolve_period("2026-03") == "2026-03"
