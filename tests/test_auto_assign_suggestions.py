"""Smart Auto-Assign: the matching of PG-X rows to Magazino Filato stock (gui/tabs/shared_order_logic.build_auto_assign_suggestions).

The algorithm used to sit inside ``_smart_auto_assign_pg_x`` (a GUI method) and had no test.  It was moved unchanged;
``_original_suggestions`` below is that code verbatim (generated from the file before the move), so the first group of tests
proves the move changed nothing, and the second group states the business rules a planner relies on.
"""
import random

import pandas as pd
import pytest

from calculate.raw_batch import is_assigned_raw
from exporters.biglietti.fields import requested_lotto_for
from exporters.biglietti.records import OrderRecord
from gui.tabs.shared_order_logic import build_auto_assign_suggestions
from utility.master_data import raw_articolo_for


# ------------------------------------------------------------------ the original code, verbatim
def _original_suggestions(pgx_records, magazino_summary):
    stock_pool = {}
    stock_by_lotto = {}
    for row in magazino_summary.itertuples(index=False):
        art = str(getattr(row, "articolo", "") or "").strip().upper()
        partita = str(getattr(row, "partita", "") or "").strip()
        lotto = str(getattr(row, "lotto", "") or "").strip()
        rocche = float(getattr(row, "mag_rocche", 0) or 0)
        peso = float(getattr(row, "mag_peso", 0) or 0)
        if art and partita and rocche > 0:
            item = {"partita": partita, "rocche": rocche, "peso": peso, "lotto": lotto, "articolo": art}
            stock_pool.setdefault(art, []).append(item)
            if lotto:
                stock_by_lotto.setdefault(lotto.casefold(), []).append(item)

    for art in stock_pool:
        stock_pool[art].sort(key=lambda b: b["rocche"])

    suggestions = []
    used_capacity = {}

    for record in pgx_records:
        if is_assigned_raw(record.raw_batch, record.customer_code):
            continue                      # already holds one of our raw batches

        raw_art = str(record.article or "").strip().upper()
        if raw_art.startswith("C"):
            raw_art = raw_articolo_for(raw_art)

        need_rocche = float(record.quantity_cones or 0)
        requested_lotto = requested_lotto_for(record)
        candidates = stock_by_lotto.get(requested_lotto.casefold(), []) if requested_lotto else []
        # Lotto is authoritative when present. If no matching Lotto exists,
        # use the requested color's raw article as the fallback.
        if not candidates:
            candidates = stock_pool.get(raw_art, [])

        matching_batch = None
        for b in candidates:
            rem = b["rocche"] - used_capacity.get(b["partita"], 0)
            if rem >= need_rocche:
                matching_batch = b
                break

        if matching_batch:
            used_capacity[matching_batch["partita"]] = used_capacity.get(matching_batch["partita"], 0) + need_rocche
            suggestions.append({
                "record": record,
                "partita_col": str(record.colored_batch or ""),
                "cliente": str(record.customer_name or ""),
                "articolo": str(record.article or ""),
                "codice": str(record.color_code or ""),
                "colore": str(record.color_name or ""),
                "rocche": record.quantity_cones,
                "suggested_partita": matching_batch["partita"],
                "available_rocche": matching_batch["rocche"],
            })
    return suggestions


# ------------------------------------------------------------------ helpers
def record(partita, article="C101", cones=10, raw_batch="", customer_code="1001", commento="", **fields):
    base = dict(customer_code=customer_code, customer_name="Acme", article=article, description="", additional_raw="",
                color_code="00123", color_name="Red", order_no="O-1", order_row="1", colored_batch=partita,
                raw_batch=raw_batch, quantity_cones=cones, raw_weight=None, dispo="D1", bagno="B1", commento=commento)
    base.update(fields)
    return OrderRecord(**base)


def stock(*rows):
    """rows: (articolo, partita, rocche[, lotto])"""
    return pd.DataFrame([
        {"articolo": r[0], "partita": r[1], "mag_rocche": r[2], "mag_peso": r[2] * 2.0, "lotto": r[3] if len(r) > 3 else ""} for r in rows
    ])


def summary(suggestions):
    return [(s["partita_col"], s["suggested_partita"], s["available_rocche"]) for s in suggestions]


# ------------------------------------------------------------------ the move changed nothing
def _random_case(rng):
    articles = ["C101", "C102", "G101", "c103", "", "C999"]
    lots = ["", "837756", "159266", "52_LOT 1251B.3", "L1"]
    stock_rows = [(rng.choice(["G101", "G102", "G103", "g101", "", "G999"]), rng.choice(["159001", "159002", "", "159003", "159004", "159005"]),
                   rng.choice([0, 5, 10, 24, 40, 100, None, -3]), rng.choice(lots)) for _ in range(rng.randint(0, 12))]
    frame = pd.DataFrame([{"articolo": a, "partita": p, "mag_rocche": r, "mag_peso": rng.choice([0, 12.5, None]), "lotto": lot} for a, p, r, lot in stock_rows],
                         columns=["articolo", "partita", "mag_rocche", "mag_peso", "lotto"])
    records = []
    for index in range(rng.randint(0, 14)):
        code = rng.choice(["1001", "3004", "3009", ""])
        raw = rng.choice(["", "X", "PG-X", "159001", "837756", "52_LOT 1251B.3", "L1"])
        comment = rng.choice(["", "PG-837756-PM", "PG-X(159266)-PM", "PG-X-PM", "no token", "PG-L1-x"])
        records.append(record(str(index + 1), article=rng.choice(articles), cones=rng.choice([0, 1, 5, 10, 24, 40, 100, 7.5, None]),
                              raw_batch=raw, customer_code=code, commento=comment))
    return records, frame


def test_the_extracted_algorithm_gives_exactly_what_the_original_gave():
    rng = random.Random(20261115)
    matched = 0
    for _ in range(600):
        records, frame = _random_case(rng)
        expected = _original_suggestions(records, frame)
        actual = build_auto_assign_suggestions(records, frame)
        assert actual == expected
        matched += len(actual)
    assert matched > 300, "the random cases must actually produce matches, otherwise the comparison proves nothing"


# ------------------------------------------------------------------ the business rules
def test_a_row_is_matched_to_the_stock_of_its_raw_article():
    suggestions = build_auto_assign_suggestions([record("1", "C101", 10)], stock(("G101", "159001", 40)))
    assert summary(suggestions) == [("1", "159001", 40.0)]
    first = suggestions[0]
    assert (first["cliente"], first["articolo"], first["codice"], first["colore"], first["rocche"]) == ("Acme", "C101", "00123", "Red", 10)


def test_a_batch_without_enough_rocche_is_not_suggested():
    assert build_auto_assign_suggestions([record("1", "C101", 50)], stock(("G101", "159001", 40))) == []


def test_the_smallest_batch_that_is_big_enough_is_used_first():
    suggestions = build_auto_assign_suggestions([record("1", "C101", 10)], stock(("G101", "159001", 100), ("G101", "159002", 12), ("G101", "159003", 8)))
    assert summary(suggestions) == [("1", "159002", 12.0)]


def test_rocche_promised_to_an_earlier_row_are_not_offered_again():
    rows = [record("1", "C101", 30), record("2", "C101", 30), record("3", "C101", 30)]
    suggestions = build_auto_assign_suggestions(rows, stock(("G101", "159001", 50), ("G101", "159002", 40)))
    # 40 -> row 1 (30 used), 50 -> row 2 (30 used); row 3 finds only 10 and 20 left: no match
    assert summary(suggestions) == [("1", "159002", 40.0), ("2", "159001", 50.0)]
    two_small = build_auto_assign_suggestions([record("1", "C101", 20), record("2", "C101", 20)], stock(("G101", "159001", 50)))
    assert summary(two_small) == [("1", "159001", 50.0), ("2", "159001", 50.0)]         # 20 + 20 fit in 50: the same batch twice


def test_a_row_that_already_holds_one_of_our_batches_is_left_alone():
    rows = [record("1", "C101", 10, raw_batch="159001"), record("2", "C101", 10)]
    assert summary(build_auto_assign_suggestions(rows, stock(("G101", "159005", 40)))) == [("2", "159005", 40.0)]


def test_a_med_customer_lot_does_not_count_as_assigned_and_is_looked_up_by_lotto():
    med = record("1", "C101", 10, raw_batch="837756", customer_code="3004")               # the customer's lot, not our batch
    other = ("G101", "159001", 40, "111111")
    wanted = ("G101", "159002", 40, "837756")
    assert summary(build_auto_assign_suggestions([med], stock(other, wanted))) == [("1", "159002", 40.0)]


def test_the_lotto_in_the_comment_wins_over_the_article_when_the_stock_has_it():
    row = record("1", "C101", 10, commento="PG-837756-PM")
    by_article = ("G101", "159001", 40, "")
    by_lotto = ("G777", "159002", 40, "837756")                                            # another article, but the requested lotto
    assert summary(build_auto_assign_suggestions([row], stock(by_article, by_lotto))) == [("1", "159002", 40.0)]


def test_when_the_requested_lotto_is_not_in_stock_the_raw_article_is_the_fallback():
    row = record("1", "C101", 10, commento="PG-837756-PM")
    assert summary(build_auto_assign_suggestions([row], stock(("G101", "159001", 40, "")))) == [("1", "159001", 40.0)]


def test_a_waiting_pgx_comment_without_a_lotto_uses_the_article():
    row = record("1", "C101", 10, commento="PG-X-PM")
    assert requested_lotto_for(row) == ""
    assert summary(build_auto_assign_suggestions([row], stock(("G101", "159001", 40)))) == [("1", "159001", 40.0)]


def test_stock_without_a_partita_or_without_rocche_is_ignored():
    frame = stock(("G101", "", 40), ("G101", "159001", 0), ("G101", "159002", 25))
    assert summary(build_auto_assign_suggestions([record("1", "C101", 10)], frame)) == [("1", "159002", 25.0)]


def test_nothing_matches_an_empty_or_unrelated_stock():
    assert build_auto_assign_suggestions([record("1", "C101", 10)], stock(("G555", "159001", 40))) == []
    assert build_auto_assign_suggestions([record("1", "C101", 10)], stock()) == []
    assert build_auto_assign_suggestions([], stock(("G101", "159001", 40))) == []


def test_the_raw_article_of_a_delave_colour_is_resolved_by_the_master_data_rule():
    assert raw_articolo_for("C101") == "G101"
    row = record("1", "c101", 10)                                                        # lower case is normalised
    assert summary(build_auto_assign_suggestions([row], stock(("g101", "159001", 40)))) == [("1", "159001", 40.0)]


def test_the_algorithm_does_not_modify_its_inputs():
    rows = [record("1", "C101", 10), record("2", "C101", 10)]
    frame = stock(("G101", "159001", 15))
    frame_before = frame.copy()
    build_auto_assign_suggestions(rows, frame)
    pd.testing.assert_frame_equal(frame, frame_before)
    assert [r.raw_batch for r in rows] == ["", ""]
