"""gui/tabs/shared_order_logic.py against verbatim copies of the code it was moved out of.

The ``_original_*`` functions below are the inner functions of ``_open_shared_orders_window`` exactly as they were before
the move (only the closure variables became parameters).  Every new function must return what its original returned for
a wide spread of inputs, so the move cannot have changed behaviour.
"""
import itertools
import random
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from exporters.biglietti.records import OrderRecord
from gui.tabs import shared_order_logic as logic
from utility.master_data import raw_articolo_for


# ------------------------------------------------------------------ the original code, verbatim
def _original_display_value(name, value):
    if name not in {"Consegna", "Delivery Date"} or value in (None, ""):
        return value
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip()
    for parser in (
        lambda: datetime.fromisoformat(text.replace("Z", "+00:00")),
        lambda: datetime.strptime(text, "%Y/%m/%d"),
        lambda: datetime.strptime(text, "%d/%m/%Y"),
    ):
        try:
            return parser().strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            pass
    return text


def _original_values_for(record, selected, excel_columns):
    polmon = ""
    if record.customer_code == "3004":
        parts = [part.strip() for part in str(record.additional_raw or "").split("-")]
        polmon = parts[4] if len(parts) > 4 and "POLMON" in parts[4].upper() else ""
    values = {
        "Dispo/Riga": record.dispo, "Cliente": record.customer_name,
        "Articolo": record.article, "Titolo": record.title, "Formato": record.formato,
        "Ordine": record.order_no, "Codice": record.color_code, "Colore": record.color_name,
        "Rocche": record.quantity_cones, "KG": record.kg, "M/C": record.machine,
        "Partita Col": record.colored_batch, "Consegna": record.delivery,
        "Commento": record.commento, "Bagno": record.bagno, "Partita GG": record.raw_batch,
        "Delivery Date": record.delivery_date, "Partita MED": record.partita_med,
        "Cliente MED": record.cliente_med, "POLMON": polmon, "Color Tube": record.color_tube,
        "VMM22": record.vmm22, "Prezzo": record.prezzo, "Densita` (360-390)": record.densita,
        "Print": record.print_flag,
    }
    return tuple(
        ["☑" if selected else "☐"]
        + [_original_display_value(name, values.get(name, "")) for name in excel_columns]
    )


def _original_partita_sort_key(pair):
    value = str(pair[1].colored_batch or "").strip().replace(",", ".")
    try:
        number = float(value)
        return (False, number, "")
    except ValueError:
        return (True, 0, value.casefold())


def _original_normal_partita(value):
    text = str(value or "").strip()
    try:
        number = float(text.replace(",", "."))
        return str(int(number)) if number.is_integer() else str(number)
    except ValueError:
        return text.casefold()


def _original_normalize_article(value):
    article = str(value or "").strip().upper()
    return "C" + article[1:] if article.startswith("G") else article


class _Recorder:
    """Stands in for availability_var / availability_label / availability_state of the original closure."""
    def __init__(self):
        self.state = {"ready": False, "valid": "unset", "article_mismatch": "unset"}
        self.texts, self.color = [], "unset"


def _original_refresh_availability(rec, partita_text, article_text, stock_by_partita):
    key = _original_normal_partita(partita_text)
    article = article_text.strip().upper()
    expected = raw_articolo_for(article)
    if not rec.state["ready"]:
        rec.texts.append(f"Expected raw article: {expected} — loading Magazino...")
        return
    if not key:
        rec.state["valid"] = False
        rec.state["article_mismatch"] = False
        rec.texts.append("Partita GG is blank — the row will remain in PG-X")
        rec.color = "#666666"
        return
    items = stock_by_partita.get(key, [])
    item = next((candidate for candidate in items if candidate[1] == expected), None)
    if not items:
        rec.state["valid"] = False
        rec.state["article_mismatch"] = False
        rec.texts.append(f"Expected raw article: {expected} — Partita not found")
        rec.color = "#c62828"
    else:
        available, article = item if item is not None else items[0]
        valid = item is not None
        rec.state["valid"] = valid
        rec.state["article_mismatch"] = not valid
        rec.texts.append(f"Available: {available:g} rocche — raw article: {article}")
        rec.color = "#2e7d32" if valid else "#c62828"
        if not valid:
            rec.texts.append(f"Wrong article. Expected {expected}, found {article} ({available:g} rocche)")


def _apply(view, rec):
    """What the window does with an Availability (the same three effects the original performed)."""
    rec.texts.append(view.text)
    if view.valid is not None:
        rec.state["valid"] = view.valid
        rec.state["article_mismatch"] = view.article_mismatch
    if view.color is not None:
        rec.color = view.color


# ------------------------------------------------------------------ inputs
DATE_VALUES = [None, "", "2026-11-14", "2026-11-14T10:30:00Z", "2026-11-14T10:30:00+02:00", "2026/11/14", "14/11/2026",
               " 14/11/2026 ", "31/02/2026", "garbage", "14-11-2026", 45000, 45000.5, 0, date(2026, 11, 14),
               datetime(2026, 11, 14, 9, 5), "  ", b"x"]
PARTITAS = ["12", "12,5", "12.5", "12.0", " 7 ", "abc", "ABC", "", None, 0, 12, 12.0, "nan", "inf", "1e3", "A-1", "٣", "0012", "-4"]


def _record(rng, **overrides):
    text = lambda: rng.choice(["", "x", "ABC-1", "a - b - c - d - POLMON 77 - e", "1-2-3-4-polmon-5", "p-q"])
    fields = dict(
        customer_code=rng.choice(["3004", "1001", "", None]), customer_name=text(), article=rng.choice(["C101", "G101", "c9", ""]),
        description=text(), additional_raw=text(), color_code=text(), color_name=text(), order_no=text(), order_row=text(),
        colored_batch=rng.choice(PARTITAS), raw_batch=rng.choice(PARTITAS), quantity_cones=rng.choice([None, 0, 12, 12.5]),
        raw_weight=None, dispo=text(), bagno=text(), delivery=rng.choice(DATE_VALUES), machine=rng.choice(["", "7", 7]),
        title=text(), formato=rng.choice(["7777", "", None]), commento=text(), partita_med=text(), cliente_med=text(), kg=rng.choice([None, 3, 3.5]),
        densita=rng.choice(["", 370, "380"]), color_tube=text(), vmm22=rng.choice([None, 1.5]), prezzo=rng.choice(["", 4.5]),
        delivery_date=rng.choice(DATE_VALUES), print_flag=rng.choice(["", "☑", "yes"]),
    )
    fields.update(overrides)
    return OrderRecord(**fields)


# ------------------------------------------------------------------ the comparisons
@pytest.mark.parametrize("name, value", list(itertools.product(["Consegna", "Delivery Date", "KG", "Cliente"], DATE_VALUES)))
def test_date_cells_format_exactly_like_the_original(name, value):
    assert logic.format_date_cell(name, value) == _original_display_value(name, value)


def test_a_date_cell_is_shown_as_dd_mm_yyyy():
    assert logic.format_date_cell("Consegna", "2026-11-14") == "14/11/2026"
    assert logic.format_date_cell("Delivery Date", datetime(2026, 11, 14, 9, 5)) == "14/11/2026"
    assert logic.format_date_cell("KG", "2026-11-14") == "2026-11-14"             # other columns are untouched
    assert logic.format_date_cell("Consegna", "garbage") == "garbage"


def test_row_values_are_identical_to_the_original_for_many_records():
    rng = random.Random(20261114)
    for index in range(400):
        record = _record(rng)
        selected = bool(index % 2)
        assert logic.order_row_values(record, selected) == _original_values_for(record, selected, logic.ORDER_TABLE_COLUMNS)


def test_the_table_has_the_print_box_plus_the_25_excel_columns():
    row = logic.order_row_values(_record(random.Random(1)), True)
    assert len(row) == 1 + len(logic.ORDER_TABLE_COLUMNS) == 26 and row[0] == "☑"
    assert logic.order_row_values(_record(random.Random(1)), False)[0] == "☐"


@pytest.mark.parametrize("code, extra, expected", [
    ("3004", "a-b-c-d-POLMON 12-e", "POLMON 12"),
    ("3004", "a-b-c-d-polmon-e", "polmon"),
    ("3004", "a-b-c-d-OTHER-e", ""),
    ("3004", "a-b", ""),
    ("3004", None, ""),
    ("1001", "a-b-c-d-POLMON 12-e", ""),                 # only MED (3004) orders carry a POLMON
])
def test_polmon_is_taken_only_from_med_orders(code, extra, expected):
    assert logic.extract_polmon(code, extra) == expected


def test_partita_sort_key_matches_the_original_and_orders_numbers_before_text():
    rng = random.Random(3)
    for value in PARTITAS:
        record = SimpleNamespace(colored_batch=value)
        # repr(): a batch text like "nan" gives a NaN key in both versions, and nan != nan
        assert repr(logic.partita_sort_key(value)) == repr(_original_partita_sort_key((None, record)))
    batches = ["10", "9", "abc", "2,5", "B2", "", "100"]
    ordered = sorted(batches, key=logic.partita_sort_key)
    assert ordered == ["2,5", "9", "10", "100", "", "abc", "B2"]       # numbers as numbers first, then text
    rng.shuffle(batches)
    assert sorted(batches, key=logic.partita_sort_key) == ordered


@pytest.mark.parametrize("value", PARTITAS + ["  Lot 5 ", "1,0", "0.50"])
def test_normal_partita_matches_the_original(value):
    assert logic.normal_partita(value) == _original_normal_partita(value)


def test_normal_partita_treats_equal_numbers_as_the_same_batch():
    assert {logic.normal_partita(v) for v in ("12", "12.0", " 12,0 ", 12, 12.0)} == {"12"}
    assert logic.normal_partita("Abc") == "abc" and logic.normal_partita(None) == ""


@pytest.mark.parametrize("value", ["g101", "G101", " c101 ", "", None, "GG", "x"])
def test_normalize_article_matches_the_original(value):
    assert logic.normalize_article(value) == _original_normalize_article(value)


def test_availability_matches_the_original_for_every_situation():
    stock = {
        "12": [(40.0, "G101")],                       # right raw article
        "13": [(5.0, "G999")],                         # wrong raw article
        "14": [(5.0, "G999"), (7.5, "G101")],          # the right one is second
        "15": [(0.0, "G101")],
    }
    for ready, partita, article in itertools.product([False, True], ["", "12", "12.0", "13", "14", "15", "99", "abc"], ["C101", "c101", "", "C777"]):
        original, new = _Recorder(), _Recorder()
        original.state["ready"] = new.state["ready"] = ready
        _original_refresh_availability(original, partita, article, stock)
        expected = raw_articolo_for(article.strip().upper())
        view = logic.describe_availability(ready=ready, key=logic.normal_partita(partita), expected=expected, stock_by_partita=stock)
        _apply(view, new)
        assert (new.state, new.color) == (original.state, original.color), (ready, partita, article)
        assert new.texts[-1] == original.texts[-1], (ready, partita, article)


def test_availability_messages():
    stock = {"13": [(5.0, "G999")], "12": [(40.0, "G101")]}
    good = logic.describe_availability(ready=True, key="12", expected="G101", stock_by_partita=stock)
    assert (good.valid, good.article_mismatch, good.color) == (True, False, logic.GOOD) and "Available: 40 rocche" in good.text
    wrong = logic.describe_availability(ready=True, key="13", expected="G101", stock_by_partita=stock)
    assert (wrong.valid, wrong.article_mismatch, wrong.color) == (False, True, logic.BAD)
    assert wrong.text == "Wrong article. Expected G101, found G999 (5 rocche)"
    assert logic.describe_availability(ready=True, key="99", expected="G101", stock_by_partita=stock).text.endswith("Partita not found")
    loading = logic.describe_availability(ready=False, key="12", expected="G101", stock_by_partita=stock)
    assert loading.valid is None and loading.color is None and "loading Magazino" in loading.text   # state left as it was


def test_delete_confirmation_lists_at_most_eight_batches():
    title, text = logic.delete_confirmation("PG-X", ["1", "2", "3"])
    assert title == "Delete PG-X Rows" and text == "Delete 3 selected PG-X row(s)?\n\nPartita Col: 1, 2, 3"
    _title, text = logic.delete_confirmation("Orders", [str(n) for n in range(12)])
    assert text.endswith("Partita Col: 0, 1, 2, 3, 4, 5, 6, 7...") and "12 selected" in text
