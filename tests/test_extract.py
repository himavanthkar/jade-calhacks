"""Layer 1: the agreements are read, not handed over. The generator's terms are the answer key."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from tpa.asof import terms_as_of
from tpa.extract import ExtractionError, compare_with_truth, extract_landed, read_agreement, read_amendment
from tpa.seed.generate import build
from tpa.seed.load import load


@pytest.mark.parametrize("seed", [1337, 42])
def test_every_term_read_from_the_documents_matches_the_answer_key(conn, seed):
    ds = build(seed, 24)
    load(conn, ds)
    with conn.cursor() as cur:
        read = extract_landed(cur, date(2026, 12, 31))
        assert not [r for r in read if r.get("error")]
        assert compare_with_truth(cur, ds.program_terms) == []


def test_the_amendment_is_known_only_from_the_day_it_arrived(conn):
    load(conn, build(1337, 24))
    with conn.cursor() as cur:
        extract_landed(cur, date(2026, 12, 31))
        assert terms_as_of(cur, "TP-0214", date(2026, 3, 1), datetime(2026, 8, 19, 8))["rate"] == Decimal("3.80")
        after = terms_as_of(cur, "TP-0214", date(2026, 3, 1), datetime(2026, 8, 19, 9))
    assert after["rate"] == Decimal("4.20") and after["source_clause_id"] == "AM-02#4.2"


def test_ambiguous_clauses_are_reported():
    ds = build(1337, 24)
    docs = {p["id"]: p["document_text"] for p in ds.tables["trade_programs"]}
    assert {pid for pid, text in docs.items() if read_agreement(text)["ambiguities"]} == {"TP-0222", "TP-0232", "TP-0233"}


def test_an_unreadable_document_is_refused_never_guessed():
    ds = build(1337, 24)
    tp0214 = next(p["document_text"] for p in ds.tables["trade_programs"] if p["id"] == "TP-0214")
    with pytest.raises(ExtractionError, match="no clause states a rate"):
        read_agreement(tp0214.replace("4.2 The allowance is $3.80 per case", "4.2 The allowance is as agreed per case"))
    with pytest.raises(ExtractionError, match="projected redemption"):
        read_agreement(tp0214.replace("projected redemption 92%", "projected redemption TBD"))
    with pytest.raises(ExtractionError, match="states no rate"):
        read_amendment("AMENDMENT AM-09 TO TRADE PROMOTION AGREEMENT TP-0214\nClause 4.2 is replaced in full, "
                       "effective 2026-03-01:\n4.2 The allowance changes.\n")
