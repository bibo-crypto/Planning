"""End-to-end scenarios on the shared "Create" workbook (Orders / PG-X sheets), the way the Biglietti pages use it.

Every test builds a workbook with the production headers through the public functions and checks what a planner would
see: which sheet a row is on, what is sorted where, what is kept, what the SQLite history says.  They do not repeat the
implementation; the expected values are the business rules (rows without raw yarn wait in PG-X, Partita Col is the key,
rows are sorted numerically, a shipped delete is archived, ...).
"""
import os
import time
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from exporters.biglietti import shared_workbook as sw
from exporters.biglietti.records import OrderRecord
from utility import orders_db

HEADERS = sw.CREATE_EXCEL_HEADERS
COL = {name: index + 1 for index, name in enumerate(HEADERS)}


def rec(partita, gg="", customer="Acme", code="1001", **fields):
    base = dict(customer_code=code, customer_name=customer, article="C101", description="d", additional_raw="",
                color_code="00123", color_name="Red", order_no="O-1", order_row="1", colored_batch=partita, raw_batch=gg,
                quantity_cones=10, raw_weight=None, dispo="D1", bagno="B1", delivery="2026-11-14", machine="7",
                title="30/1", formato="7777", commento="", kg=3.5)
    base.update(fields)
    return OrderRecord(**base)


def sheet(path, name):
    """[(Partita Col, Partita GG)] of one sheet, in sheet order."""
    wb = load_workbook(path)
    try:
        ws = wb[name]
        return [(ws.cell(r, COL["Partita Col"]).value, ws.cell(r, COL["Partita GG"]).value) for r in range(2, ws.max_row + 1)]
    finally:
        wb.close()


def keys(path, name):
    return [str(partita) for partita, _gg in sheet(path, name)]


def row_of(path, name, partita):
    wb = load_workbook(path)
    try:
        ws = wb[name]
        for r in range(2, ws.max_row + 1):
            if str(ws.cell(r, COL["Partita Col"]).value) == str(partita):
                return {header: ws.cell(r, column).value for header, column in COL.items()}
    finally:
        wb.close()
    return None


def history(path, which):
    """History rows of THIS workbook (the history database is shared between tests, keyed by file)."""
    rows = {"open": orders_db.list_open, "all": orders_db.list_history, "shipped": orders_db.list_shipped}[which]()
    return [row for row in rows if Path(row["source_file"]) == path]


@pytest.fixture
def workbook(tmp_path):
    path = tmp_path / "shared.xlsx"
    sw.append_create_excel(path, [rec("10", "12"), rec("2", "13"), rec("5", ""), rec("abc", "14"), rec("3", "", customer="MED srl", code="3004")], "Acme")
    return path


# ------------------------------------------------------------------ Orders / PG-X
def test_a_new_workbook_puts_rows_without_raw_yarn_in_pgx_and_sorts_numerically(workbook):
    assert sheet(workbook, "Orders") == [("2", "13"), ("10", "12"), ("abc", "14")]            # numbers ascending, text last
    assert sorted(keys(workbook, "PG-X")) == ["3", "5"]                                        # blank Partita GG waits (MED included)
    headers = [cell.value for cell in load_workbook(workbook)["Orders"][1]]
    assert headers[: len(HEADERS)] == HEADERS and "Print" in headers


def test_appending_the_same_records_again_changes_nothing(workbook, tmp_path):
    before = (sheet(workbook, "Orders"), sheet(workbook, "PG-X"))
    result = sw.append_create_excel(workbook, [rec("10", "12"), rec("5", "")], "Acme")
    assert result["added"] == 0 and result["skipped"] == 2
    assert (sheet(workbook, "Orders"), sheet(workbook, "PG-X")) == before


def test_new_records_are_added_and_existing_ones_are_not_duplicated(workbook):
    result = sw.append_create_excel(workbook, [rec("10", "12"), rec("7", "15"), rec("8", "")], "Acme")
    assert (result["added"], result["skipped"]) == (2, 1)
    assert keys(workbook, "Orders") == ["2", "7", "10", "abc"] and sorted(keys(workbook, "PG-X")) == ["3", "5", "8"]


# ------------------------------------------------------------------ Partita GG
def test_assigning_a_partita_gg_moves_the_row_to_orders_and_keeps_its_data(workbook):
    before = row_of(workbook, "PG-X", "5")
    result = sw.save_pg_x_partita(workbook, "5", "12")
    assert result["updated"] == 1 and result["partita_gg"] == "12"
    assert "5" not in keys(workbook, "PG-X") and keys(workbook, "Orders") == ["2", "5", "10", "abc"]
    after = row_of(workbook, "Orders", "5")
    assert after["Partita GG"] == "12"
    assert {k: v for k, v in after.items() if k not in {"Partita GG", "Print"}} == {k: v for k, v in before.items() if k not in {"Partita GG", "Print"}}


def test_assigning_to_a_partita_that_is_not_in_pgx_is_an_error_not_a_silent_no_op(workbook):
    with pytest.raises(ValueError, match="'999' was not found in PG-X"):
        sw.save_pg_x_partita(workbook, "999", "12")
    assert sheet(workbook, "Orders") == [("2", "13"), ("10", "12"), ("abc", "14")]


def test_a_partita_gg_of_the_wrong_raw_article_is_refused_and_the_row_stays_in_pgx(workbook):
    import pandas as pd
    stock = pd.DataFrame([{"articolo": "G999", "partita": "12", "mag_rocche": 5.0}])        # colour article C101 needs raw G101
    with pytest.raises(ValueError, match="Partita GG 12 does not belong to article G101 required by color article C101"):
        sw.save_pg_x_partita(workbook, "5", "12", magazino_summary=stock)
    assert "5" in keys(workbook, "PG-X") and "5" not in keys(workbook, "Orders")


def test_a_wrong_raw_article_can_be_assigned_when_the_planner_confirms(workbook):
    import pandas as pd
    stock = pd.DataFrame([{"articolo": "G999", "partita": "12", "mag_rocche": 5.0}])
    result = sw.save_pg_x_partita(workbook, "5", "12", magazino_summary=stock, allow_article_mismatch=True)
    assert result["updated"] == 1 and "5" in keys(workbook, "Orders")


def test_the_available_stock_of_the_right_raw_article_is_reported(workbook):
    import pandas as pd
    stock = pd.DataFrame([{"articolo": "G101", "partita": "12", "mag_rocche": 40.0}])
    assert sw.save_pg_x_partita(workbook, "5", "12", magazino_summary=stock)["available"] == 40.0


# ------------------------------------------------------------------ update / move / delete
def test_editing_an_order_changes_only_that_row(workbook):
    others = {p: row_of(workbook, "Orders", p) for p in ("2", "abc")}
    result = sw.update_order_row(workbook, "10", {"Commento": "call the customer"})
    assert result == {"updated": 1, "moved_to_pgx": False}
    assert row_of(workbook, "Orders", "10")["Commento"] == "call the customer"
    assert {p: row_of(workbook, "Orders", p) for p in ("2", "abc")} == others


def test_clearing_partita_gg_of_an_order_sends_it_back_to_pgx(workbook):
    result = sw.update_order_row(workbook, "2", {"Partita GG": ""})
    assert result["moved_to_pgx"] is True
    assert "2" not in keys(workbook, "Orders") and "2" in keys(workbook, "PG-X")


def test_editing_an_unknown_order_is_an_error(workbook):
    with pytest.raises(ValueError, match="'999' was not found in Orders"):
        sw.update_order_row(workbook, "999", {"Commento": "x"})


def test_a_pgx_row_can_be_edited_without_assigning_yarn(workbook):
    assert sw.update_pg_x_row(workbook, "5", {"Commento": "waiting for yarn"}) == 1
    assert row_of(workbook, "PG-X", "5")["Commento"] == "waiting for yarn" and "5" in keys(workbook, "PG-X")


def test_a_pgx_row_can_be_moved_to_orders_by_hand(workbook):
    assert sw.move_pg_x_to_orders(workbook, "3") == 1
    assert "3" in keys(workbook, "Orders") and "3" not in keys(workbook, "PG-X")
    assert sw.move_pg_x_to_orders(workbook, "999") == 0                                     # nothing to move: reported as 0


def test_deleting_rows_removes_only_the_selected_ones_from_the_chosen_sheet(workbook):
    assert sw.delete_shared_rows(workbook, ["5"], "PG-X") == 1
    assert keys(workbook, "PG-X") == ["3"] and keys(workbook, "Orders") == ["2", "10", "abc"]
    assert sw.delete_shared_rows(workbook, ["10", "2"], "Orders") == 2
    assert keys(workbook, "Orders") == ["abc"]
    assert sw.delete_shared_rows(workbook, ["999"], "Orders") == 0


# ------------------------------------------------------------------ shipped / history
def test_a_shipped_delete_is_archived_in_the_shipped_history(workbook):
    assert sw.delete_shipped_shared_rows(workbook, ["abc"], "Orders") == 1
    assert "abc" not in keys(workbook, "Orders")
    shipped = history(workbook, "shipped")
    assert [(row["sheet_name"], row["partita_col"]) for row in shipped] == [("Orders", "abc")]
    assert "abc" not in {row["partita_col"] for row in history(workbook, "open")}


def test_a_plain_delete_is_archived_but_is_not_shipped(workbook):
    sw.delete_shared_rows(workbook, ["10"], "Orders")
    archived = [row for row in history(workbook, "all") if row["partita_col"] == "10"]
    assert archived and archived[0]["status"] == "archived" and history(workbook, "shipped") == []


def test_the_open_history_always_matches_what_is_in_the_workbook(workbook):
    sw.save_pg_x_partita(workbook, "5", "12")
    sw.update_order_row(workbook, "2", {"Partita GG": ""})
    sw.move_pg_x_to_orders(workbook, "3")
    sw.delete_shared_rows(workbook, ["10"], "Orders")
    open_now = sorted((row["sheet_name"], row["partita_col"]) for row in history(workbook, "open"))
    in_workbook = sorted([("Orders", k) for k in keys(workbook, "Orders")] + [("PG-X", k) for k in keys(workbook, "PG-X")])
    assert open_now == in_workbook
    # a row that moved between the sheets is open on exactly one of them
    assert sum(1 for sheet_name, key in open_now if key == "5") == 1 and sum(1 for sheet_name, key in open_now if key == "2") == 1


# ------------------------------------------------------------------ Excel round trip
def test_records_survive_the_excel_round_trip_without_changing_values(workbook):
    records = {r.colored_batch: r for r in sw.load_create_excel_records(workbook)}
    assert set(records) == {"2", "10", "abc"}
    r = records["10"]
    assert (r.color_code, r.customer_name, r.article, r.raw_batch) == ("00123", "Acme", "C101", "12")       # leading zeros kept
    assert (r.quantity_cones, r.kg) == (10, 3.5)
    assert [x.colored_batch for x in sw.load_create_excel_records(workbook, partita_gg="12")] == ["10"]       # filter by Partita GG
    assert sorted(x.colored_batch for x in sw.load_create_excel_records(workbook, sheet_name="PG-X")) == ["3", "5"]


def test_a_missing_file_is_reported_and_not_created_by_a_read_or_update(tmp_path):
    missing = tmp_path / "nope.xlsx"
    for call in (lambda: sw.load_create_excel_records(missing), lambda: sw.update_pg_x_row(missing, "1", {"Commento": "x"})):
        with pytest.raises(FileNotFoundError):
            call()
    assert not missing.exists()


# ------------------------------------------------------------------ older workbooks
def test_a_workbook_from_an_older_version_is_migrated_on_the_next_append(tmp_path):
    """Older files: no Print column, no PG-X sheet, and rows still waiting for yarn sitting on Orders."""
    path = tmp_path / "old.xlsx"
    old_headers = [h for h in HEADERS if h != "Print"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(old_headers)
    for partita, gg in (("4", "12"), ("6", ""), ("1", "15")):
        row = dict.fromkeys(old_headers, "")
        row.update({"Cliente": "Acme", "Articolo": "C101", "Partita Col": partita, "Partita GG": gg})
        ws.append([row[h] for h in old_headers])
    wb.save(path)
    wb.close()

    result = sw.append_create_excel(path, [rec("9", "13")], "Acme")
    assert result["added"] == 1
    assert keys(path, "Orders") == ["1", "4", "9"] and keys(path, "PG-X") == ["6"]            # the waiting row moved to PG-X
    for name in ("Orders", "PG-X"):
        assert "Print" in [cell.value for cell in load_workbook(path)[name][1]]
    assert row_of(path, "Orders", "4")["Cliente"] == "Acme"                                  # existing data kept


def test_a_workbook_without_a_partita_col_column_is_refused_and_left_alone(tmp_path):
    path = tmp_path / "other.xlsx"
    wb = Workbook()
    wb.active.append(["Something", "Else"])
    wb.save(path)
    wb.close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match="no 'Partita Col' column"):
        sw.append_create_excel(path, [rec("1", "1")], "Acme")
    assert path.read_bytes() == before


# ------------------------------------------------------------------ failures and size
def test_a_save_that_fails_leaves_the_workbook_exactly_as_it_was(workbook, monkeypatch):
    """On Windows a workbook open in Excel cannot be replaced: the save fails, the file must stay intact, no temp file left."""
    from utility import excel_io
    before = workbook.read_bytes()

    def locked(*_args, **_kwargs):
        raise PermissionError("[WinError 32] The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(excel_io.os, "replace", locked)
    with pytest.raises(RuntimeError, match="The Excel file is open or locked. Close it in Excel"):     # a clear message, not a raw WinError
        sw.delete_shared_rows(workbook, ["10"], "Orders")
    assert workbook.read_bytes() == before
    assert [p.name for p in workbook.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_a_large_workbook_is_handled_correctly_and_in_reasonable_time(tmp_path):
    path = tmp_path / "large.xlsx"
    records = [rec(str(n), str(1000 + n) if n % 4 else "") for n in range(1, 1501)]
    started = time.time()
    result = sw.append_create_excel(path, records, "Acme")
    sw.update_order_row(path, "1", {"Commento": "edited"})
    sw.save_pg_x_partita(path, "4", "5000")
    elapsed = time.time() - started
    assert result["added"] == 1500
    orders, pgx = keys(path, "Orders"), keys(path, "PG-X")
    assert len(orders) + len(pgx) == 1500 and len(set(orders + pgx)) == 1500              # nothing lost, nothing duplicated
    assert pgx and all(int(a) < int(b) for a, b in zip(orders, orders[1:]))             # numeric order, not text order
    assert row_of(path, "Orders", "1")["Commento"] == "edited" and "4" in orders
    assert elapsed < 90, f"1500 rows took {elapsed:.0f}s"
