"""Pure rules of the "Select Orders for Biglietti" window -- no Tk, no I/O.

These used to be inner functions of ``SharedOrdersWindowMixin._open_shared_orders_window`` (a 550-line method), where
they could only be exercised by opening the whole window.  They are moved here unchanged and tested on their own
(tests/test_shared_order_logic.py compares each one with a verbatim copy of the original code).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

# The Excel columns of the table (after the "Print" tick-box), in display order.
ORDER_TABLE_COLUMNS = (
    "Dispo/Riga", "Cliente", "Articolo", "Titolo", "Formato", "Ordine", "Codice",
    "Colore", "Rocche", "KG", "M/C", "Partita Col", "Consegna", "Commento",
    "Bagno", "Partita GG", "Delivery Date", "Partita MED", "Cliente MED", "POLMON",
    "Color Tube", "VMM22", "Prezzo", "Densita` (360-390)", "Print",
)
DATE_COLUMNS = frozenset({"Consegna", "Delivery Date"})

NEUTRAL, GOOD, BAD = "#666666", "#2e7d32", "#c62828"      # availability message colours


def format_date_cell(name: str, value):
    """Format a Consegna / Delivery Date value as dd/mm/yyyy; other columns are returned unchanged."""
    if name not in DATE_COLUMNS or value in (None, ""):
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


def extract_polmon(customer_code, additional_raw) -> str:
    """For MED orders (customer 3004) the POLMON part of the additional text, else ""."""
    if customer_code == "3004":
        parts = [part.strip() for part in str(additional_raw or "").split("-")]
        return parts[4] if len(parts) > 4 and "POLMON" in parts[4].upper() else ""
    return ""


def order_row_values(record, is_selected: bool, columns=ORDER_TABLE_COLUMNS) -> tuple:
    """The table cells of one order record: the Print tick-box, then *columns* (dates formatted for display)."""
    values = {
        "Dispo/Riga": record.dispo, "Cliente": record.customer_name,
        "Articolo": record.article, "Titolo": record.title, "Formato": record.formato,
        "Ordine": record.order_no, "Codice": record.color_code, "Colore": record.color_name,
        "Rocche": record.quantity_cones, "KG": record.kg, "M/C": record.machine,
        "Partita Col": record.colored_batch, "Consegna": record.delivery,
        "Commento": record.commento, "Bagno": record.bagno, "Partita GG": record.raw_batch,
        "Delivery Date": record.delivery_date, "Partita MED": record.partita_med,
        "Cliente MED": record.cliente_med, "POLMON": extract_polmon(record.customer_code, record.additional_raw),
        "Color Tube": record.color_tube, "VMM22": record.vmm22, "Prezzo": record.prezzo,
        "Densita` (360-390)": record.densita, "Print": record.print_flag,
    }
    return tuple(["☑" if is_selected else "☐"] + [format_date_cell(name, values.get(name, "")) for name in columns])


def partita_sort_key(colored_batch):
    """Sort key for Partita Col: numbers first (ascending as numbers), then text (case-insensitive)."""
    value = str(colored_batch or "").strip().replace(",", ".")
    try:
        number = float(value)
        return (False, number, "")
    except ValueError:
        return (True, 0, value.casefold())


def normal_partita(value) -> str:
    """A Partita as a comparison key: 12.0 and "12" are the same batch; text compares case-insensitively."""
    text = str(value or "").strip()
    try:
        number = float(text.replace(",", "."))
        return str(int(number)) if number.is_integer() else str(number)
    except ValueError:
        return text.casefold()


def partita_choice_sort_key(value):
    return (normal_partita(value).casefold(), str(value))


def normalize_article(value) -> str:
    """Upper-case article; a raw-yarn "G..." article is shown as its finished "C..." article."""
    article = str(value or "").strip().upper()
    return "C" + article[1:] if article.startswith("G") else article


@dataclass(frozen=True)
class Availability:
    """What the row editor shows about the typed Partita GG.

    ``valid`` / ``article_mismatch`` are None when the editor's remembered state must stay as it is, and ``color`` is
    None when the message colour must stay as it is (that is what the original did while Magazino was still loading).
    """
    text: str
    color: str | None = None
    valid: bool | None = None
    article_mismatch: bool | None = None


def describe_availability(*, ready: bool, key: str, expected: str, stock_by_partita: dict) -> Availability:
    """Check a Partita GG (*key*, already passed through normal_partita) against the Magazino stock.

    *stock_by_partita* maps a normalised partita to ``[(available rocche, raw article), ...]``; *expected* is the raw
    article the colour's article needs.
    """
    if not ready:
        return Availability(f"Expected raw article: {expected} — loading Magazino...")
    if not key:
        return Availability("Partita GG is blank — the row will remain in PG-X", NEUTRAL, False, False)
    items = stock_by_partita.get(key, [])
    item = next((candidate for candidate in items if candidate[1] == expected), None)
    if not items:
        return Availability(f"Expected raw article: {expected} — Partita not found", BAD, False, False)
    available, article = item if item is not None else items[0]
    valid = item is not None
    if valid:
        return Availability(f"Available: {available:g} rocche — raw article: {article}", GOOD, True, False)
    return Availability(f"Wrong article. Expected {expected}, found {article} ({available:g} rocche)", BAD, False, True)


def delete_confirmation(sheet: str, partita_cols: list[str]) -> tuple[str, str]:
    """Title and question of the "delete the selected rows" confirmation (at most 8 batches are listed)."""
    preview = ", ".join(partita_cols[:8])
    suffix = "..." if len(partita_cols) > 8 else ""
    return (f"Delete {sheet} Rows",
            f"Delete {len(partita_cols)} selected {sheet} row(s)?\n\nPartita Col: {preview}{suffix}")
