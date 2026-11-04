"""دوال صغيرة تستخرج وتنظّف حقول الأمر (Commento / Polmoni / Dispo / أسماء الملفات).

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from calculate.raw_batch import MED_CODE, is_customer_lot
from exporters.biglietti.records import OrderRecord


def _clean(v: Any) -> str:
    return " ".join(str(v or "").replace("\xa0", " ").split())


def _key(v: Any) -> str:
    # ``\w`` keeps Arabic headers (e.g. وزن and تحضير خام) as well as
    # the synthetic positional keys used for blank ERP headers.
    return re.sub(r"[^\w]+", " ", _clean(v).lower(), flags=re.UNICODE).strip()


def _number(v: Any) -> float | int | None:
    s = _clean(v).replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        n = float(s)
        return int(n) if n.is_integer() else n
    except ValueError:
        return None


def _kamal_kg(v: Any) -> float | int | None:
    """Read Kamal's ERP KG value in real kilograms.

    The Kamal ERP export stores whole-number weights in tenths of a kilogram
    (``525`` means ``52.5``). Values that already contain a decimal point are
    already expressed in kilograms and are kept unchanged.
    """
    parsed = _number(v)
    if parsed is None:
        return None
    text = _clean(v).replace(" ", "")
    if "." not in text and "," not in text and float(parsed).is_integer():
        value = float(parsed) / 10
        return int(value) if value.is_integer() else value
    return parsed


def _order_number(v: Any) -> str:
    s = _clean(v)
    if "/" in s:
        s = s.rsplit("/", 1)[-1]
    return s.lstrip("0") or "0"


def _first_match(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.I)
    return m.group(1) if m else ""


def _raw_batch_from_comment(additional: str, customer_code: str) -> str:
    """The raw batch / lot of a MED or ELVY order line, read ONLY from its comment.

    "PG-159233-PM-X" -> "159233": one of our own raw batches (digits starting with 1).
    "PG-X(837756)-PM-X" / "PG-X(52_LOT 1251B.3)-PO-1500-2026" -> the customer's lot, which
    is not a raw batch: the row has none yet, so it waits in PG-X and the lot is what
    Smart Auto-Assign looks up.  MED lots are numbers; ELVY lots are numbers and letters.
    "PG-X-..." names nothing: "".
    """
    batch = requested_lotto_from_comment(additional)
    if not batch:
        return ""
    if customer_code == MED_CODE:
        return batch if batch.isdigit() else ""            # a MED lot is always a number
    return batch


def requested_lotto_for(record: "OrderRecord") -> str:
    """The lotto Smart Auto-Assign looks up in the stock for a PG-X row.

    A MED customer lot recorded in Partita GG (a number not starting with 1) wins;
    otherwise the lotto written in the row's comment ("" when it names none).
    """
    if is_customer_lot(record.raw_batch, record.customer_code):
        return _clean(record.raw_batch)
    return requested_lotto_from_comment(record.commento or record.additional_raw or "")


def requested_lotto_from_comment(comment: str) -> str:
    """The lotto an order comment asks for, used to find its stock in Magazino Filato.

    "PG-837756-PM..." / "PG-159266-PM..." -> "837756" / "159266"; the waiting form
    "PG-X(837756)-PM..." -> "837756"; a bare "PG-X-..." or no PG token -> "".
    """
    text = comment or ""
    waiting = re.search(r"(?i)PG-X\(\s*([^)]+?)\s*\)", text)          # the lot may hold spaces / dashes
    if waiting:
        return waiting.group(1).strip()
    token = re.search(r"(?i)PG-([^-\s(]+)", text)
    value = token.group(1).strip() if token else ""
    return "" if value.upper() == "X" else value


def _polmoni_segment(additional: str) -> str:
    """MED only: the 5th dash-separated segment of the additional
    description, kept as-is (e.g. '4 POLMONI') when it mentions Polmoni,
    matching the reference query's own POLMON output column -- this is
    text, not a number, and is what actually gets exported."""
    parts = [p.strip() for p in _clean(additional).split("-")]
    seg = parts[4] if len(parts) > 4 else ""
    return seg if "POLMON" in seg.upper() else ""


def _polmoni_extra(additional: str) -> int:
    """MED only: 'N POLMONI' adds N*4 Rocche worth of machine capacity
    (1 polmone stands in for 4 coni) -- used only for the M/C calculation,
    never exported directly."""
    seg = _polmoni_segment(additional)
    m = re.search(r"(\d+)\s*POLMON", seg, re.I) if seg else None
    return int(m.group(1)) * 4 if m else 0


_PG_PREFIX_RE = re.compile(r"^\s*PG-(?:X\([^)]*\)|[^-\s(]+)-", re.IGNORECASE)


def _commento_for(customer: str, additional: str) -> str:
    """Per-customer Commento, mirroring the reference query's dash-split
    on ALL '-' occurrences:
    ELVY keeps everything after the 2nd '-' (e.g. 'PG-157474-PO-1466-2026'
    -> 'PO-1466-2026'); MED keeps the 6th segment (.6), which is usually
    absent -> blank, confirmed against real MED data."""
    if customer == "ELVY":
        # "PG-<partita>-" or "PG-X(<lot>)-" is dropped as a whole, so a lot containing a
        # dash ("PG-X(AB-12)-PO-1500-2026") cannot shift the split.
        text = _clean(additional)
        prefix = _PG_PREFIX_RE.match(text)
        if prefix:
            return text[prefix.end():].strip()
    parts = [p.strip() for p in _clean(additional).split("-")]
    if customer == "ELVY":
        return "-".join(parts[2:]).strip() if len(parts) > 2 else ""
    return parts[5].strip() if len(parts) > 5 else ""


def _segment(additional: str, index: int) -> str:
    """1-based dash-segment of the additional description, 'X' treated as
    unassigned/blank (matches the reference query's own X->null rule)."""
    parts = [p.strip() for p in _clean(additional).split("-")]
    seg = parts[index - 1].strip() if len(parts) >= index else ""
    return "" if seg.upper() == "X" else seg


def _partita_med(additional: str) -> str:
    """Descrizione aggiuntiva ordine.4 -> 'Partita MED' in the reference
    query. Not a PO number for MED orders (that pattern is ELVY-only)."""
    return _segment(additional, 4)


def _cliente_med(additional: str) -> str:
    """Descrizione aggiuntiva ordine.5 -> 'Cliente MED'. The raw segment
    (e.g. 'ORDINE CAM') is expanded through _CLIENTE_MED_EXPANSIONS when
    recognised -- 'ORDINE CAM' -> 'ORDINE CAMPIONARIO' was confirmed
    against 3 real pre-existing tickets in the file the user sent, but
    this is the only code seen so far; ask the user for the rest of the
    mapping if other order-type abbreviations show up blank/unexpanded."""
    seg = _segment(additional, 5)
    return _CLIENTE_MED_EXPANSIONS.get(seg.upper(), seg)


_CLIENTE_MED_EXPANSIONS: dict[str, str] = {
    "ORDINE CAM": "ORDINE CAMPIONARIO",
}


def _po_token(additional: str) -> str:
    """Everything from the word 'PO' onward, e.g. 'PO-1466-2026'.
    ELVY-only naming convention -- MED orders use PM/dispo, not PO."""
    m = re.search(r"\bPO\b[-\s]*[0-9][0-9\-]*", additional, re.I)
    return m.group(0).strip() if m else ""


def _dispo_number(dispo: str) -> str:
    """Numeric part of a Dispo value like 'D-00505450-001' -> '505450'."""
    m = re.search(r"D-0*([0-9]+)", _clean(dispo), re.I)
    if m:
        return m.group(1)
    return _clean(dispo).lstrip("0") or _clean(dispo)


def _dispo_suffix(dispo: str) -> str:
    """The per-row sequence suffix of a Dispo value, e.g.
    'D-00505449-001' -> '1' -- this is what Sheet1's own 'Riga' column
    matches against (confirmed against real data: Riga=1,2,3,4 lines up
    with Dispo-Bagno rows -001,-002,-003,-004 in a different physical
    order than Sheet1 itself). Also accepts a bare number so it can be
    used directly on a Riga value too."""
    s = _clean(dispo)
    m = re.search(r"-0*([0-9]+)\s*$", s)
    if m:
        return str(int(m.group(1)))
    n = _number(s)
    return str(int(n)) if n is not None else ""


_PO_COMMENTO_RE = re.compile(r"^\s*PO[-\s]*(\d+)(?:[-\s]*(\d{4}))?", re.IGNORECASE)


def _elvy_file_stem(records: list["OrderRecord"]) -> str:
    """Name of the ELVY files, built from the values of the Excel's Commento column.

    One PO -> 'PO-1500-2026'.  The same Commento repeated is written once.  Several
    POs are written together, numbers sharing a year being merged:
    'PO-1500-2026' + 'PO-1501-2026' -> 'PO-1500 & 1501-2026'.  A Commento that is not
    a PO is used as it is; with no Commento at all the name is just 'ELVY'.
    """
    commenti: list[str] = []
    for record in records:
        value = _commento_for("ELVY", record.additional_raw)
        if value and value not in commenti:
            commenti.append(value)
    numbers_by_year: dict[str, list[str]] = {}
    others: list[str] = []
    for value in commenti:
        match = _PO_COMMENTO_RE.match(value)
        if match:
            numbers = numbers_by_year.setdefault(match.group(2) or "", [])
            if match.group(1) not in numbers:
                numbers.append(match.group(1))
        else:
            cleaned = re.sub(r'[<>:"/\\|?*]', "_", value).strip(" .")
            if cleaned and cleaned not in others:
                others.append(cleaned)
    parts = [
        "PO-" + " & ".join(numbers) + (f"-{year}" if year else "")
        for year, numbers in numbers_by_year.items()
    ]
    return " & ".join(parts + others) or "ELVY"


def build_output_stem(records: list["OrderRecord"], customer: str) -> str:
    """The name (without extension) of a customer's output files, e.g. 'PO-1500-2026'
    (ELVY, from its Commento values) or 'MED-D-505450-2026'.
    """
    if customer == "ELVY":
        return _elvy_file_stem(records)
    dispo_num = _dispo_number(records[0].dispo) if records else ""
    year = str(datetime.now().year)
    return f"MED-D-{dispo_num}-{year}" if dispo_num else f"MED-{year}"
